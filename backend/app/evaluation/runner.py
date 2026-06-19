"""Runner d'évaluation : compare la sortie LLM à la baseline sur chaque cas.

Mesure le **taux de respect des garde-fous** et l'**écart à la baseline** (allure moyenne).
N'effectue pas le fallback : on évalue la sortie LLM **brute** pour juger sa qualité.
"""

from dataclasses import dataclass

from app.domain.ports import StrategyGenerator
from app.evaluation.fixtures import EvalCase, eval_cases
from app.services.baseline_strategy import build_baseline_strategy
from app.services.strategy_generation import recompute_totals
from app.services.strategy_metrics import deviation_vs_baseline_pct, guardrails_passed


@dataclass(frozen=True)
class EvalRow:
    name: str
    distance_km: float
    generated_by: str
    guardrails_passed: bool
    baseline_pace: float
    llm_pace: float | None
    deviation_pct: float | None


async def run_evaluation(generator: StrategyGenerator) -> list[EvalRow]:
    rows: list[EvalRow] = []
    for case in eval_cases():
        rows.append(await _evaluate_case(generator, case))
    return rows


async def _evaluate_case(generator: StrategyGenerator, case: EvalCase) -> EvalRow:
    baseline = build_baseline_strategy(case.course, case.athlete)
    try:
        llm = await generator.generate(case.course, case.race, case.athlete, None, None)
        # Comme en production : on recalcule les totaux (l'arithmétique du LLM n'est pas fiable).
        llm = recompute_totals(llm, case.course)
    except Exception:
        return EvalRow(
            case.name,
            case.course.distance_km,
            "error",
            False,
            baseline.average_pace_sec_per_km,
            None,
            None,
        )
    return EvalRow(
        name=case.name,
        distance_km=case.course.distance_km,
        generated_by=llm.generated_by,
        guardrails_passed=guardrails_passed(llm, case.course, case.athlete),
        baseline_pace=baseline.average_pace_sec_per_km,
        llm_pace=llm.average_pace_sec_per_km,
        deviation_pct=deviation_vs_baseline_pct(llm, baseline),
    )


def _mmss(pace: float | None) -> str:
    if pace is None:
        return "—"
    minutes, seconds = divmod(round(pace), 60)
    return f"{minutes}:{seconds:02d}"


def format_report(rows: list[EvalRow]) -> str:
    lines = [
        f"{'cas':<22} {'dist':>5} {'origine':>9} {'garde-fous':>11} "
        f"{'baseline':>9} {'llm':>7} {'écart':>7}",
        "-" * 78,
    ]
    for r in rows:
        dev = f"{r.deviation_pct:+.1f}%" if r.deviation_pct is not None else "—"
        lines.append(
            f"{r.name:<22} {r.distance_km:>4.0f}k {r.generated_by:>9} "
            f"{'OK' if r.guardrails_passed else 'NON':>11} "
            f"{_mmss(r.baseline_pace):>9} {_mmss(r.llm_pace):>7} {dev:>7}"
        )
    passed = sum(1 for r in rows if r.guardrails_passed)
    lines.append("-" * 78)
    lines.append(f"Garde-fous respectés : {passed}/{len(rows)}")
    return "\n".join(lines)
