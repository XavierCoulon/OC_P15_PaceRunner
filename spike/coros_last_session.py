"""Réutilise le token COROS déjà obtenu (pas de navigateur) pour lire la dernière session running.

Valide que le chemin "backend via token stocké" récupère bien de la vraie donnée d'activité.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from coros_auth import (  # réutilise la même config + stockage de tokens
    FileTokenStorage,
    OAuthClientMetadata,
    OAuthClientProvider,
    REDIRECT_URI,
    SERVER_URL,
)
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

TODAY = date.today()
START = TODAY - timedelta(days=45)
RUN_CODES = [100, 101, 102, 103]  # outdoor/indoor/trail/track run


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

    print(f"[MCP] Connexion à {SERVER_URL} (token en cache, pas de navigateur)...", flush=True)
    async with streamablehttp_client(SERVER_URL, auth=oauth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=30)
            print("[MCP] Session initialisée ✅", flush=True)

            args = {
                "startDate": START.strftime("%Y%m%d"),
                "endDate": TODAY.strftime("%Y%m%d"),
                "sportTypeCodes": RUN_CODES,
                "minDistanceKm": None,
                "maxDistanceKm": None,
                "minDurationMinutes": None,
                "maxDurationMinutes": None,
                "maxAveragePace": None,
                "locationKeyword": None,
                "limit": 1,
                "timezone": "Europe/Paris",
            }
            print(f"[MCP] Appel querySportRecords {args['startDate']}→{args['endDate']} ...", flush=True)
            result = await asyncio.wait_for(
                session.call_tool("querySportRecords", args), timeout=60
            )
            print("\n=== Dernière session running COROS ===", flush=True)
            for block in result.content:
                text = getattr(block, "text", None)
                if text:
                    print(text, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
