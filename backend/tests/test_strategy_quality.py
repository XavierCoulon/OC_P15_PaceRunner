"""Tests de la métrique qualité (M4)."""

import logging

import pytest

from app.domain.models import KmPlan, PaceStrategy
from app.services.strategy_quality import compute_quality, log_quality


def _strategy(avg: float, generated_by: str = "llm") -> PaceStrategy:
    return PaceStrategy(
        distance_km=2.0,
        estimated_time_sec=avg * 2,
        average_pace_sec_per_km=avg,
        km_plans=[
            KmPlan(km_index=1, target_pace_sec_per_km=avg, effort="steady", gradient_pct=0.0)
        ],
        generated_by=generated_by,
    )


def test_compute_quality_for_accepted_llm() -> None:
    quality = compute_quality(
        _strategy(330.0, "llm"),
        _strategy(300.0, "baseline"),
        llm_guardrails_passed=True,
        latency_ms=1234.56,
    )
    assert quality.generated_by == "llm"
    assert quality.llm_guardrails_passed is True
    assert quality.deviation_vs_baseline_pct == 10.0
    assert quality.latency_ms == 1234.6


def test_compute_quality_for_fallback() -> None:
    baseline = _strategy(300.0, "baseline")
    quality = compute_quality(baseline, baseline, llm_guardrails_passed=False, latency_ms=10.0)
    assert quality.generated_by == "baseline"
    assert quality.llm_guardrails_passed is False
    assert quality.deviation_vs_baseline_pct == 0.0


def test_log_quality_emits_structured_record(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="pacerunner.quality"):
        log_quality(
            compute_quality(
                _strategy(300.0), _strategy(300.0), llm_guardrails_passed=True, latency_ms=5.0
            )
        )
    assert any("strategy_quality" in record.message for record in caplog.records)
