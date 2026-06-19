"""Test du client MCP COROS « maison » : store de tokens, refresh, rotation, SSE, 401."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.adapters.coros_client import CorosClient, CorosError
from app.adapters.coros_token_store import CorosTokens
from app.config import Settings

_MCP = "https://mcpeu.coros.com/mcp"
_TOKEN = "https://mcpeu.coros.com/oauth2/token"


class _MemStore:
    def __init__(self, tokens: CorosTokens | None = None) -> None:
        self.tokens = tokens

    def load(self) -> CorosTokens | None:
        return self.tokens

    def save(self, tokens: CorosTokens) -> None:
        self.tokens = tokens


def _settings() -> Settings:
    return Settings(coros_client_id="cid", coros_refresh_token="rt")  # type: ignore[arg-type]


def _mcp_ok(request: httpx.Request) -> httpx.Response:
    method = json.loads(request.content).get("method")
    if method == "initialize":
        return httpx.Response(200, headers={"mcp-session-id": "sess-1"}, json={"result": {}})
    if method == "notifications/initialized":
        return httpx.Response(202)
    text = "VO2max: 45\nThreshold Pace: 4:52 /km"
    payload = {"result": {"content": [{"type": "text", "text": text}]}}
    return httpx.Response(
        200, headers={"content-type": "text/event-stream"}, text=f"data: {json.dumps(payload)}\n\n"
    )


@respx.mock
async def test_refreshes_token_parses_sse_and_persists() -> None:
    respx.post(_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "abc", "expires_in": 3600})
    )
    respx.post(_MCP).mock(side_effect=_mcp_ok)
    store = _MemStore()

    client = CorosClient(_settings(), token_store=store)
    text = await client.call_tool("queryFitnessAssessmentOverview", {})

    assert "Threshold Pace: 4:52 /km" in text
    assert b"grant_type=refresh_token" in respx.calls[0].request.content
    assert store.tokens is not None and store.tokens.access_token == "abc"


@respx.mock
async def test_reuses_valid_access_token_without_refresh() -> None:
    respx.post(_MCP).mock(side_effect=_mcp_ok)  # endpoint token NON mocké : ne doit pas être appelé
    store = _MemStore(
        CorosTokens(
            access_token="cached",
            refresh_token="r",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )

    text = await CorosClient(_settings(), token_store=store).call_tool("x", {})

    assert "VO2max: 45" in text
    assert all(str(call.request.url) == _MCP for call in respx.calls)  # pas de refresh


@respx.mock
async def test_refresh_persists_rotated_refresh_token() -> None:
    respx.post(_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "abc", "refresh_token": "rotated"})
    )
    respx.post(_MCP).mock(side_effect=_mcp_ok)
    store = _MemStore()

    await CorosClient(_settings(), token_store=store).call_tool("x", {})

    assert store.tokens is not None and store.tokens.refresh_token == "rotated"


@respx.mock
async def test_401_triggers_refresh_and_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") == "Bearer stale":
            return httpx.Response(401)
        return _mcp_ok(request)

    respx.post(_TOKEN).mock(return_value=httpx.Response(200, json={"access_token": "fresh"}))
    respx.post(_MCP).mock(side_effect=handler)
    store = _MemStore(
        CorosTokens(
            access_token="stale",
            refresh_token="r",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )

    text = await CorosClient(_settings(), token_store=store).call_tool("x", {})

    assert "VO2max: 45" in text
    assert store.tokens is not None and store.tokens.access_token == "fresh"


async def test_call_tool_without_credentials_raises() -> None:
    with pytest.raises(CorosError):
        await CorosClient(Settings(), token_store=_MemStore()).call_tool("x", {})
