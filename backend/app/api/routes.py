"""Routes de l'API. Pour l'instant : sonde de santé publique."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Sonde de disponibilité (publique, utilisée par le smoke test et le déploiement)."""
    return {"status": "ok"}
