"""Client MCP brut (httpx) — contourne le SDK pour diagnostiquer/récupérer la donnée COROS.

Refait à la main le handshake Streamable HTTP : initialize -> notifications/initialized
-> tools/call(querySportRecords), en lisant correctement la réponse SSE ou JSON.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import httpx

SERVER_URL = "https://mcpeu.coros.com/mcp"
TOKENS_FILE = Path(__file__).parent / ".coros_tokens.json"
PROTOCOL = "2025-06-18"

access_token = json.loads(TOKENS_FILE.read_text())["access_token"]
TODAY = date.today()
START = TODAY - timedelta(days=45)


def base_headers(session_id: str | None) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {access_token}",
        "MCP-Protocol-Version": PROTOCOL,
    }
    if session_id:
        h["Mcp-Session-Id"] = session_id
    return h


def parse_body(resp: httpx.Response) -> dict | None:
    """Renvoie le 1er message JSON-RPC, que la réponse soit JSON pur ou SSE."""
    ctype = resp.headers.get("content-type", "")
    text = resp.text
    if ctype.startswith("application/json"):
        return json.loads(text)
    if "text/event-stream" in ctype:
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[len("data:"):].strip())
    return None


def main() -> None:
    with httpx.Client(timeout=30) as client:
        # 1) initialize
        init_req = {
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                       "clientInfo": {"name": "pacerunner", "version": "0.1.0"}},
        }
        r = client.post(SERVER_URL, headers=base_headers(None), json=init_req)
        print(f"[initialize] {r.status_code} ct={r.headers.get('content-type')}", flush=True)
        sid = r.headers.get("mcp-session-id")
        print(f"[initialize] session id = {sid}", flush=True)
        print(f"[initialize] body = {parse_body(r)}", flush=True)

        # 2) notifications/initialized
        r = client.post(SERVER_URL, headers=base_headers(sid),
                        json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        print(f"[initialized] {r.status_code}", flush=True)

        # 3) tools/call querySportRecords
        args = {
            "startDate": START.strftime("%Y%m%d"), "endDate": TODAY.strftime("%Y%m%d"),
            "sportTypeCodes": [100, 101, 102, 103],
            "minDistanceKm": None, "maxDistanceKm": None,
            "minDurationMinutes": None, "maxDurationMinutes": None,
            "maxAveragePace": None, "locationKeyword": None,
            "limit": 1, "timezone": "Europe/Paris",
        }
        call_req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "querySportRecords", "arguments": args}}
        print(f"\n[tools/call] envoi querySportRecords {args['startDate']}→{args['endDate']} ...", flush=True)
        r = client.post(SERVER_URL, headers=base_headers(sid), json=call_req)
        print(f"[tools/call] {r.status_code} ct={r.headers.get('content-type')}", flush=True)
        body = parse_body(r)
        print("\n=== RÉPONSE COROS ===", flush=True)
        print(json.dumps(body, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
