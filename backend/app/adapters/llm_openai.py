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
    CalibrationProfile,
    CourseProfile,
    CourseSection,
    GenerationMode,
    PaceStrategy,
    RaceContext,
    SectionNote,
    SurfaceContext,
    WeatherContext,
)
from app.prompts.strategy_system import (
    STRATEGY_SYSTEM_PROMPT,
    STRATEGY_SYSTEM_PROMPT_AUTONOMOUS,
    STRATEGY_SYSTEM_PROMPT_COT,
)
from app.services.baseline_strategy import segment_course
from app.services.calibration_compute import calibration_note

_SYSTEM_BY_MODE = {
    "anchored": STRATEGY_SYSTEM_PROMPT,
    "autonomous": STRATEGY_SYSTEM_PROMPT_AUTONOMOUS,
    "cot": STRATEGY_SYSTEM_PROMPT_COT,
}

_RETRY_INSTRUCTION = (
    "Ta réponse précédente n'était pas un JSON conforme au schéma. "
    "Renvoie UNIQUEMENT l'objet JSON valide, sans texte autour."
)

Message = dict[str, str]


class LLMGenerationError(RuntimeError):
    """La génération LLM a échoué (transport ou sortie non conforme après retry)."""


class OpenAICompatibleStrategyGenerator:
    """Implémente le port `StrategyGenerator`."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        config = settings or get_settings()
        # Overrides explicites (ex. second moteur HF pour la comparaison).
        default_key = config.llm_api_key.get_secret_value() if config.llm_api_key else None
        self._base_url = (base_url or config.llm_base_url).rstrip("/")
        self._model = model or config.llm_model
        self._api_key = api_key if api_key is not None else default_key
        self._timeout = config.llm_timeout_seconds

    async def generate(
        self,
        course: CourseProfile,
        race: RaceContext,
        athlete: AthleteProfile | None,
        weather: WeatherContext | None,
        surface: SurfaceContext | None,
        baseline: PaceStrategy | None = None,
        mode: GenerationMode = "anchored",
        calibration: CalibrationProfile | None = None,
    ) -> PaceStrategy:
        # anchored : ancré sur la baseline. autonomous/cot : le LLM conçoit seul (sans baseline).
        # cot : raisonnement explicite imposé → pas de mode JSON (le modèle réfléchit avant).
        anchor = baseline if mode == "anchored" else None
        # Le narratif par tranche n'existe qu'en mode ancré (découpage déterministe côté serveur).
        sections = segment_course(course) if mode == "anchored" else []
        json_mode = mode != "cot"
        messages: list[Message] = [
            {"role": "system", "content": _SYSTEM_BY_MODE[mode]},
            {
                "role": "user",
                "content": _build_user_message(
                    course, race, athlete, weather, surface, anchor, calibration, sections
                ),
            },
        ]
        raw = await self._chat(messages, json_mode=json_mode)
        strategy, used_raw = await self._parse_with_retry(messages, raw, json_mode=json_mode)
        if sections:
            strategy = _attach_section_narrative(strategy, sections, used_raw)
        return strategy

    async def _parse_with_retry(
        self, messages: list[Message], raw: str, *, json_mode: bool
    ) -> tuple[PaceStrategy, str]:
        """Parse la sortie (un retry si JSON non conforme). Renvoie (stratégie, brut retenu)."""
        try:
            return _parse_strategy(raw), raw
        except (json.JSONDecodeError, ValidationError):
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": _RETRY_INSTRUCTION})
            retry = await self._chat(messages, json_mode=json_mode)
            try:
                return _parse_strategy(retry), retry
            except (json.JSONDecodeError, ValidationError) as exc:
                raise LLMGenerationError("Sortie LLM non conforme après retry.") from exc

    async def _chat(self, messages: list[Message], *, json_mode: bool = True) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            content: str = response.json()["choices"][0]["message"]["content"]
            return content


def _parse_strategy(raw: str) -> PaceStrategy:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = _extract_json(raw)  # sortie CoT : JSON après le raisonnement
    strategy = PaceStrategy.model_validate(data)
    # On ne fait pas confiance au champ renvoyé : la provenance est imposée côté serveur.
    return strategy.model_copy(update={"generated_by": "llm"})


def _extract_json(text: str) -> dict[str, Any]:
    """Extrait le dernier objet JSON équilibré (le raisonnement peut contenir des accolades)."""
    text = text.replace("```json", "").replace("```", "")
    end = text.rfind("}")
    depth = 0
    for i in range(end, -1, -1):
        if text[i] == "}":
            depth += 1
        elif text[i] == "{":
            depth -= 1
            if depth == 0:
                return json.loads(text[i : end + 1])  # type: ignore[no-any-return]
    raise json.JSONDecodeError("aucun objet JSON", text, 0)


def _attach_section_narrative(
    strategy: PaceStrategy, sections: list[CourseSection], raw: str
) -> PaceStrategy:
    """Assemble le narratif : les **bornes viennent du serveur** (sections), le LLM ne fournit que
    le texte (`section_notes`). Appariement dans l'ordre — toute longueur en trop est tronquée.
    """
    notes = _extract_section_notes(raw)
    narrative = [
        SectionNote(start_km=section.start_km, end_km=section.end_km, note=note.strip())
        for section, note in zip(sections, notes, strict=False)
        if note.strip()
    ]
    return strategy.model_copy(update={"section_narrative": narrative})


def _extract_section_notes(raw: str) -> list[str]:
    """Récupère la liste `section_notes` du JSON LLM (tolérant : ignore tout le reste)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            data = _extract_json(raw)
        except json.JSONDecodeError:
            return []
    notes = data.get("section_notes") if isinstance(data, dict) else None
    if not isinstance(notes, list):
        return []
    return [n for n in notes if isinstance(n, str)]


def _build_user_message(
    course: CourseProfile,
    race: RaceContext,
    athlete: AthleteProfile | None,
    weather: WeatherContext | None,
    surface: SurfaceContext | None,
    baseline: PaceStrategy | None = None,
    calibration: CalibrationProfile | None = None,
    sections: list[CourseSection] | None = None,
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
    note = calibration_note(calibration)
    if note is not None:
        # Résumé qualitatif personnalisé (forme/efforts) — pas de stats brutes à recombiner.
        payload["calibration"] = note
    if sections:
        # Tranches déterministes à décrire (le LLM renvoie une note par tranche, dans l'ordre).
        payload["sections"] = [
            {
                "start_km": s.start_km,
                "end_km": s.end_km,
                "effort": s.effort,
                "avg_gradient_pct": s.avg_gradient_pct,
            }
            for s in sections
        ]
    return json.dumps(payload, ensure_ascii=False)
