"""Routes de l'API.

- `GET /health` : sonde publique.
- `POST /strategy` : protégé (Bearer). 1re tranche verticale — upload GPX + date/heure
  de course → renvoie le `CourseProfile`. La génération de stratégie (enrichissements +
  LLM) sera branchée dans les phases suivantes.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.adapters.gpx_parser import GpxParseError, parse_gpx
from app.api.security import require_api_token
from app.domain.models import CourseProfile, RaceContext

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Sonde de disponibilité (publique, utilisée par le smoke test et le déploiement)."""
    return {"status": "ok"}


@router.post(
    "/strategy",
    response_model=CourseProfile,
    dependencies=[Depends(require_api_token)],
)
async def create_strategy(
    gpx: Annotated[UploadFile, File(description="Fichier GPX du parcours.")],
    race_datetime: Annotated[datetime, Form(description="Date/heure de la course (ISO 8601).")],
    goal: Annotated[str | None, Form(description="Objectif (optionnel).")] = None,
) -> CourseProfile:
    """Parse le GPX et renvoie le profil de parcours.

    La date/heure et l'objectif sont validés (`RaceContext`) ; ils alimenteront la
    météo jour J et la génération de stratégie dans les phases ultérieures.
    """
    raw = await gpx.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Fichier GPX non décodable (UTF-8 attendu).",
        ) from exc

    try:
        profile = parse_gpx(content)
    except GpxParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    # Validé dès maintenant ; consommé par les enrichissements (F3) et le LLM (G1).
    RaceContext(race_datetime=race_datetime, goal=goal)
    return profile
