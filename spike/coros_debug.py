"""Debug : voir le trafic HTTP réel entre le SDK MCP et le serveur COROS.

Active les logs httpx + mcp, fait initialize puis un tools/call avec timeout court,
et affiche tout (y compris l'exception) pour diagnostiquer le blocage post-initialize.
"""

from __future__ import annotations

import asyncio
import logging

from coros_auth import (
    FileTokenStorage,
    OAuthClientMetadata,
    OAuthClientProvider,
    REDIRECT_URI,
    SERVER_URL,
)
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
for noisy in ("httpcore",):
    logging.getLogger(noisy).setLevel(logging.INFO)


async def main() -> None:
    oauth = OAuthClientProvider(
        server_url=SERVER_URL,
        client_metadata=OAuthClientMetadata(
            client_name="PaceRunner Spike",
            redirect_uris=[REDIRECT_URI],  # type: ignore[list-item]
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        ),
        storage=FileTokenStorage(),
    )

    async with streamablehttp_client(SERVER_URL, auth=oauth) as (read, write, get_sid):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=20)
            sid = get_sid() if callable(get_sid) else None
            print(f"\n>>> initialize OK — session id = {sid}\n", flush=True)

            try:
                print(">>> tools/list (timeout 15s)...", flush=True)
                tools = await asyncio.wait_for(session.list_tools(), timeout=15)
                print(f">>> tools/list OK : {len(tools.tools)} outils", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f">>> tools/list ÉCHEC : {exc!r}", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print(f">>> FATAL : {exc!r}", flush=True)
