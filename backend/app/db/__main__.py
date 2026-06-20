"""Vérifie la connexion à la base : `make db-ping`."""

import asyncio

from app.db.engine import DatabaseNotConfiguredError, ping


async def _main() -> None:
    try:
        await ping()
        print("DB OK ✅ (SELECT 1)")
    except DatabaseNotConfiguredError:
        print("DATABASE_URL absent — renseigne-le dans .env")
    except Exception as exc:  # diagnostic de connexion
        print(f"Échec de connexion : {exc!r}")


if __name__ == "__main__":
    asyncio.run(_main())
