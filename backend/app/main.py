"""Point d'entrée FastAPI : création de l'application et inclusion des routes."""

from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings


def create_app() -> FastAPI:
    """Construit l'application FastAPI (factory, facilite les tests)."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.include_router(router)
    return app


app = create_app()
