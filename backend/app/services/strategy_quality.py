"""Métrique qualité d'un run de génération (M4).

Capture, pour chaque stratégie produite : l'origine, si la sortie LLM a passé les
garde-fous, l'écart à la baseline et la latence. Journalisé en logs structurés ici ; la
**persistance en base** (Neon `prediction_runs`) et l'agrégation `/stats` sont assurées par le
`PredictionRepository` (cf. `strategy_service._journal`).
"""

import logging

from pydantic import BaseModel

from app.domain.models import PaceStrategy
from app.services.strategy_metrics import deviation_vs_baseline_pct

_logger = logging.getLogger("pacerunner.quality")


class StrategyQuality(BaseModel):
    """Indicateurs qualité d'un run de génération."""

    generated_by: str
    llm_guardrails_passed: bool
    deviation_vs_baseline_pct: float
    latency_ms: float


def compute_quality(
    strategy: PaceStrategy,
    baseline: PaceStrategy,
    *,
    llm_guardrails_passed: bool,
    latency_ms: float,
) -> StrategyQuality:
    return StrategyQuality(
        generated_by=strategy.generated_by,
        llm_guardrails_passed=llm_guardrails_passed,
        deviation_vs_baseline_pct=deviation_vs_baseline_pct(strategy, baseline),
        latency_ms=round(latency_ms, 1),
    )


def log_quality(quality: StrategyQuality) -> None:
    """Journalise la métrique (sink = logs ; remplacé par la base en phase N)."""
    _logger.info("strategy_quality %s", quality.model_dump_json())
