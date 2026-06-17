"""Spike d'authentification COROS via client MCP (OAuth 2.1 + PKCE).

But (go/no-go) : vérifier qu'un client MCP tiers (notre futur backend FastAPI) peut
s'authentifier au serveur MCP COROS distant et appeler un outil read-only.

Déroulé : connexion -> flux OAuth (consentement navigateur, une fois) -> list_tools()
-> appel `queryFitnessAssessmentOverview` -> affichage. Le token est persisté localement
(`.coros_tokens.json`) pour éviter de réautoriser à chaque exécution.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.stdout.reconfigure(line_buffering=True)  # sortie temps réel (pas de buffer)

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

SERVER_URL = "https://mcpeu.coros.com/mcp"
CALLBACK_HOST = "localhost"
CALLBACK_PORT = 3030
CALLBACK_PATH = "/callback"
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"

TOKENS_FILE = Path(__file__).parent / ".coros_tokens.json"
CLIENT_FILE = Path(__file__).parent / ".coros_client.json"
AUTH_URL_FILE = Path(__file__).parent / ".auth_url.txt"
RESULT_FILE = Path(__file__).parent / ".result.txt"


class FileTokenStorage(TokenStorage):
    """Persiste tokens + enregistrement client sur disque (suffisant pour un spike mono-utilisateur)."""

    async def get_tokens(self) -> OAuthToken | None:
        if TOKENS_FILE.exists():
            return OAuthToken.model_validate_json(TOKENS_FILE.read_text())
        return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        TOKENS_FILE.write_text(tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        if CLIENT_FILE.exists():
            return OAuthClientInformationFull.model_validate_json(CLIENT_FILE.read_text())
        return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        CLIENT_FILE.write_text(client_info.model_dump_json())


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict[str, str | None] = {}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        qs = parse_qs(parsed.query)
        _CallbackHandler.result = {
            "code": qs.get("code", [None])[0],
            "state": qs.get("state", [None])[0],
            "error": qs.get("error", [None])[0],
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<h2>COROS auth recue. Vous pouvez fermer cet onglet.</h2>")

    def log_message(self, *args: object) -> None:  # silence
        return


async def redirect_handler(authorization_url: str) -> None:
    AUTH_URL_FILE.write_text(authorization_url)  # relayée à l'utilisateur via le chat
    print("\n[OAuth] URL de consentement écrite dans .auth_url.txt", flush=True)
    print(authorization_url, flush=True)
    try:
        webbrowser.open(authorization_url)
    except Exception:  # noqa: BLE001 - l'URL est de toute façon dans le fichier
        pass


async def callback_handler() -> tuple[str, str | None]:
    """Lance un mini-serveur local, attend le redirect OAuth, renvoie (code, state)."""
    _CallbackHandler.result = {}
    server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    while thread.is_alive():
        await asyncio.sleep(0.2)
    server.server_close()
    res = _CallbackHandler.result
    if res.get("error"):
        raise RuntimeError(f"OAuth error renvoyée par COROS : {res['error']}")
    code = res.get("code")
    if not code:
        raise RuntimeError("Pas de code d'autorisation reçu sur le callback.")
    return code, res.get("state")


async def main() -> None:
    client_metadata = OAuthClientMetadata(
        client_name="PaceRunner Spike",
        redirect_uris=[REDIRECT_URI],  # type: ignore[list-item]
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )

    oauth = OAuthClientProvider(
        server_url=SERVER_URL,
        client_metadata=client_metadata,
        storage=FileTokenStorage(),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    print(f"[MCP] Connexion à {SERVER_URL} ...")
    async with streamablehttp_client(SERVER_URL, auth=oauth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("[MCP] Session initialisée ✅")

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"[MCP] {len(names)} outils exposés : {names}")

            target = "queryFitnessAssessmentOverview"
            if target not in names:
                print(f"[!] Outil {target} absent — voir liste ci-dessus.")
                return

            print(f"[MCP] Appel {target} ...")
            result = await session.call_tool(target, {})
            texts = [getattr(b, "text", "") for b in result.content if getattr(b, "text", None)]
            payload = "\n".join(texts)
            print("\n=== Résultat COROS ===")
            print(payload)
            RESULT_FILE.write_text(f"OK\n{payload}")


if __name__ == "__main__":
    for f in (AUTH_URL_FILE, RESULT_FILE):
        f.unlink(missing_ok=True)
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - on veut le diagnostic complet dans le fichier
        import traceback

        RESULT_FILE.write_text(f"ERROR\n{exc!r}\n\n{traceback.format_exc()}")
        print(f"[ERREUR] {exc!r}", flush=True)
        raise
