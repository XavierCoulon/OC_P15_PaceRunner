"""StrategyGenerator via une API LLM OpenAI-compatible (Ollama local ou HF, cf. ADR-4).

Un seul appel : on injecte la donnée nettoyée dans le prompt, on demande une sortie JSON
(`response_format`), puis on valide contre `PaceStrategy`. Un retry est tenté si la réponse
n'est pas un JSON conforme ; au-delà, l'erreur remonte (le fallback baseline est géré en G2).
"""

import json
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.domain.models import (
    AthleteProfile,
    CourseProfile,
    PaceStrategy,
    RaceContext,
    SurfaceContext,
    WeatherContext,
)
from app.prompts.strategy_system import (
    STRATEGY_SYSTEM_PROMPT,
    STRATEGY_SYSTEM_PROMPT_AUTONOMOUS,
)

_RETRY_INSTRUCTION = (
    "Ta réponse précédente n'était pas un JSON conforme au schéma. "
    "Renvoie UNIQUEMENT l'objet JSON valide, sans texte autour."
)

Message = dict[str, str]


class LLMGenerationError(RuntimeError):
    """La génération LLM a échoué (transport ou sortie non conforme après retry)."""


class OpenAICompatibleStrategyGenerator:
    """Implémente le port `StrategyGenerator`."""

    def __init__(self, settings: Settings | None = None) -> None:
        config = settings or get_settings()
        self._base_url = config.llm_base_url.rstrip("/")
        self._model = config.llm_model
        self._api_key = config.llm_api_key.get_secret_value() if config.llm_api_key else None
        self._timeout = config.llm_timeout_seconds

    async def generate(
        self,
        course: CourseProfile,
        race: RaceContext,
        athlete: AthleteProfile | None,
        weather: WeatherContext | None,
        surface: SurfaceContext | None,
        baseline: PaceStrategy | None = None,
        autonomous: bool = False,
    ) -> PaceStrategy:
        # Mode autonome : le LLM conçoit seul la stratégie (prompt dédié, pas de baseline injectée).
        system = STRATEGY_SYSTEM_PROMPT_AUTONOMOUS if autonomous else STRATEGY_SYSTEM_PROMPT
        anchor = None if autonomous else baseline
        messages: list[Message] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": _build_user_message(course, race, athlete, weather, surface, anchor),
            },
        ]
        raw = await self._chat(messages)
        try:
            return _parse_strategy(raw)
        except (json.JSONDecodeError, ValidationError):
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": _RETRY_INSTRUCTION})
            retry = await self._chat(messages)
            try:
                return _parse_strategy(retry)
            except (json.JSONDecodeError, ValidationError) as exc:
                raise LLMGenerationError("Sortie LLM non conforme après retry.") from exc

    async def _chat(self, messages: list[Message]) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            content: str = response.json()["choices"][0]["message"]["content"]
            return content


def _parse_strategy(raw: str) -> PaceStrategy:
    data = json.loads(raw)
    strategy = PaceStrategy.model_validate(data)
    # On ne fait pas confiance au champ renvoyé : la provenance est imposée côté serveur.
    return strategy.model_copy(update={"generated_by": "llm"})


def _build_user_message(
    course: CourseProfile,
    race: RaceContext,
    athlete: AthleteProfile | None,
    weather: WeatherContext | None,
    surface: SurfaceContext | None,
    baseline: PaceStrategy | None = None,
) -> str:
    payload: dict[str, Any] = {
        "course": {
            "distance_km": course.distance_km,
            "elevation_gain_m": course.elevation_gain_m,
            "elevation_loss_m": course.elevation_loss_m,
            "segments": [
                {
                    "km_index": s.km_index,
                    "distance_km": s.distance_km,
                    "gradient_pct": s.gradient_pct,
                }
                for s in course.segments
            ],
        },
        "race": {"datetime": race.race_datetime.isoformat()},
        "athlete": athlete.model_dump() if athlete is not None else None,
        "weather": weather.model_dump() if weather is not None else None,
        "surface": surface.model_dump() if surface is not None else None,
    }
    if baseline is not None:
        # Référence déterministe réaliste (grade-adjusted) : point de départ à ajuster.
        payload["baseline_pace_sec_per_km"] = [
            {"km_index": p.km_index, "pace_sec_per_km": p.target_pace_sec_per_km}
            for p in baseline.km_plans
        ]
    return json.dumps(payload, ensure_ascii=False)
