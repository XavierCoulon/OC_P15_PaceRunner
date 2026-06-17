"""Test de cause racine : le SDK bloque-t-il à cause du flux GET SSE concurrent ?

On neutralise `handle_get_stream` (no-op) puis on refait initialize + list_tools + un tool call
via le SDK. Si ça répond maintenant, c'est bien le flux GET qui faisait blocage côté COROS.
"""

from __future__ import annotations

import asyncio

import mcp.client.streamable_http as sh
from coros_auth import (
    FileTokenStorage,
    OAuthClientMetadata,
    OAuthClientProvider,
    REDIRECT_URI,
    SERVER_URL,
)
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# --- patch : ne pas ouvrir le flux GET SSE ---
async def _noop_get_stream(self, client, read_stream_writer):  # type: ignore[no-untyped-def]
    return


sh.StreamableHTTPTransport.handle_get_stream = _noop_get_stream  # type: ignore[assignment]


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

    async with streamablehttp_client(SERVER_URL, auth=oauth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=20)
            print(">>> initialize OK", flush=True)

            tools = await asyncio.wait_for(session.list_tools(), timeout=20)
            print(f">>> list_tools OK : {len(tools.tools)} outils ✅", flush=True)

            res = await asyncio.wait_for(
                session.call_tool("queryFitnessAssessmentOverview", {}), timeout=20
            )
            for b in res.content:
                if getattr(b, "text", None):
                    print(">>> call_tool OK ✅\n" + b.text, flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print(f">>> ÉCHEC : {exc!r}", flush=True)
