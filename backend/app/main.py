"""Point d'entrée FastAPI : création de l'application et inclusion des routes."""

from fastapi import FastAPI

from app.api.routes import router


def create_app() -> FastAPI:
    """Construit l'application FastAPI (factory, facilite les tests)."""
    app = FastAPI(title="PaceRunner", version="0.1.0")
    app.include_router(router)
    return app


app = create_app()
