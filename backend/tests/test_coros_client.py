"""Test du client MCP COROS « maison » (refresh OAuth + handshake + SSE), mocké via respx."""

import json

import httpx
import pytest
import respx

from app.adapters.coros_client import CorosClient, CorosError
from app.config import Settings

_MCP = "https://mcpeu.coros.com/mcp"
_TOKEN = "https://mcpeu.coros.com/oauth2/token"


def _settings() -> Settings:
    return Settings(coros_client_id="cid", coros_refresh_token="rt")  # type: ignore[arg-type]


def _mcp_handler(request: httpx.Request) -> httpx.Response:
    method = json.loads(request.content).get("method")
    if method == "initialize":
        return httpx.Response(200, headers={"mcp-session-id": "sess-1"}, json={"result": {}})
    if method == "notifications/initialized":
        return httpx.Response(202)
    if method == "tools/call":
        text = "VO2max: 45\nThreshold Pace: 4:52 /km"
        payload = {"result": {"content": [{"type": "text", "text": text}]}}
        sse = f"event: message\ndata: {json.dumps(payload)}\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=sse)
    return httpx.Response(400)


@respx.mock
async def test_call_tool_refreshes_token_and_parses_sse() -> None:
    respx.post(_TOKEN).mock(return_value=httpx.Response(200, json={"access_token": "abc"}))
    respx.post(_MCP).mock(side_effect=_mcp_handler)

    text = await CorosClient(_settings()).call_tool("queryFitnessAssessmentOverview", {})

    assert "Threshold Pace: 4:52 /km" in text
    # le token a bien été demandé en refresh_token
    token_request = respx.calls[0].request
    assert b"grant_type=refresh_token" in token_request.content


async def test_call_tool_without_credentials_raises() -> None:
    with pytest.raises(CorosError):
        await CorosClient(Settings()).call_tool("queryFitnessAssessmentOverview", {})
