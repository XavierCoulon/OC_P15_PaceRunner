"""Client MCP « maison » pour COROS (httpx).

Le SDK MCP officiel bloque sur le serveur COROS (flux GET SSE concurrent) — cf. ADR-2.
On refait à la main le strict nécessaire du transport Streamable HTTP :

1. rafraîchissement de l'`access_token` via le refresh token OAuth (client public, PKCE) ;
2. `initialize` → `notifications/initialized` ;
3. `tools/call`, en lisant la réponse qu'elle soit JSON pur ou `text/event-stream`.

L'app étant mono-utilisateur, le refresh token vient d'un secret (`COROS_REFRESH_TOKEN`).
"""

import json
from typing import Any, Protocol

import httpx

from app.config import Settings, get_settings

_PROTOCOL_VERSION = "2025-06-18"


class CorosError(RuntimeError):
    """Échec d'un échange avec COROS (auth, transport, outil)."""


class MCPToolClient(Protocol):
    """Port minimal consommé par les providers COROS."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str: ...


class CorosClient:
    """Implémente `MCPToolClient` via le transport Streamable HTTP de COROS."""

    def __init__(self, settings: Settings | None = None) -> None:
        config = settings or get_settings()
        self._mcp_url = config.coros_mcp_url
        self._token_url = config.coros_token_url
        self._client_id = config.coros_client_id
        self._refresh_token = (
            config.coros_refresh_token.get_secret_value() if config.coros_refresh_token else None
        )
        self._timeout = config.http_timeout_seconds

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Rafraîchit le token, ouvre une session MCP et appelle un outil ; renvoie son texte."""
        if not self._refresh_token or not self._client_id:
            raise CorosError("Identifiants COROS absents (client_id / refresh_token).")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            access_token = await self._fetch_access_token(client)
            session_id = await self._initialize(client, access_token)
            return await self._invoke(client, access_token, session_id, name, arguments)

    async def _fetch_access_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            self._token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
            },
        )
        response.raise_for_status()
        access_token = response.json().get("access_token")
        if not access_token:
            raise CorosError("Aucun access_token renvoyé par COROS.")
        return str(access_token)

    def _headers(self, access_token: str, session_id: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {access_token}",
            "MCP-Protocol-Version": _PROTOCOL_VERSION,
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        return headers

    async def _initialize(self, client: httpx.AsyncClient, access_token: str) -> str | None:
        init_request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pacerunner", "version": "0.1.0"},
            },
        }
        response = await client.post(
            self._mcp_url, headers=self._headers(access_token), json=init_request
        )
        response.raise_for_status()
        session_id: str | None = response.headers.get("mcp-session-id")
        await client.post(
            self._mcp_url,
            headers=self._headers(access_token, session_id),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        return session_id

    async def _invoke(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        session_id: str | None,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = await client.post(
            self._mcp_url, headers=self._headers(access_token, session_id), json=request
        )
        response.raise_for_status()
        body = self._parse_body(response)
        result = (body or {}).get("result", {})
        if result.get("isError"):
            raise CorosError(f"L'outil COROS « {name} » a renvoyé une erreur.")
        texts = [
            block.get("text", "")
            for block in result.get("content", [])
            if block.get("type") == "text"
        ]
        text = "\n".join(t for t in texts if t)
        if not text:
            raise CorosError(f"Réponse COROS vide pour « {name} ».")
        return text

    @staticmethod
    def _parse_body(response: httpx.Response) -> dict[str, Any] | None:
        """Renvoie le 1er message JSON-RPC, que la réponse soit JSON pur ou SSE."""
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            parsed: dict[str, Any] = response.json()
            return parsed
        if "text/event-stream" in content_type:
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    loaded: dict[str, Any] = json.loads(line[len("data:") :].strip())
                    return loaded
        return None
