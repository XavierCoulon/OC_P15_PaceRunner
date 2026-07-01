"""Tests du découpage déterministe en tranches + assemblage du narratif (anti-hallucination)."""

import json

from app.adapters.llm_openai import _attach_section_narrative, _extract_section_notes
from app.domain.models import CourseProfile, ElevationSegment
from app.prompts.strategy_system import STRATEGY_SYSTEM_PROMPT
from app.services.baseline_strategy import build_baseline_strategy, segment_course


def _course(gradients: list[float]) -> CourseProfile:
    segments = [
        ElevationSegment(
            km_index=i + 1,
            distance_km=1.0,
            elevation_gain_m=max(g, 0.0),
            elevation_loss_m=max(-g, 0.0),
            gradient_pct=g,
        )
        for i, g in enumerate(gradients)
    ]
    return CourseProfile(
        distance_km=float(len(gradients)),
        elevation_gain_m=0.0,
        elevation_loss_m=0.0,
        start_lat=43.0,
        start_lon=-1.0,
        segments=segments,
    )


def test_segment_course_groups_consecutive_efforts() -> None:
    course = _course([0.0, 0.5, 5.0, 6.0, -4.0, -5.0, 0.0])
    sections = segment_course(course)
    assert [(s.start_km, s.end_km, s.effort) for s in sections] == [
        (1, 2, "steady"),
        (3, 4, "hard"),
        (5, 6, "easy"),
        (7, 7, "steady"),
    ]


def test_narrative_bounds_come_from_server_not_llm() -> None:
    course = _course([0.0, 5.0, -5.0])  # 3 tranches d'1 km
    sections = segment_course(course)
    strategy = build_baseline_strategy(course, None)
    raw = json.dumps({"section_notes": ["pars calme", "monte régulier", "relance"]})
    out = _attach_section_narrative(strategy, sections, raw)
    assert [(n.start_km, n.end_km) for n in out.section_narrative] == [(1, 1), (2, 2), (3, 3)]
    assert out.section_narrative[1].note == "monte régulier"


def test_narrative_covers_all_sections_with_fallback() -> None:
    course = _course([0.0, 5.0, -5.0])  # steady / hard / easy
    sections = segment_course(course)
    strategy = build_baseline_strategy(course, None)
    # Trop peu de notes LLM → les tranches manquantes prennent un repli déterministe (terrain).
    out = _attach_section_narrative(strategy, sections, json.dumps({"section_notes": ["x"]}))
    assert len(out.section_narrative) == 3  # toutes les tranches couvertes
    assert out.section_narrative[0].note == "x"  # note du LLM
    assert "montée" in out.section_narrative[1].note  # repli (hard)
    assert "descente" in out.section_narrative[2].note  # repli (easy)
    # Aucune note LLM → repli déterministe partout, plan complet.
    out2 = _attach_section_narrative(strategy, sections, json.dumps({"distance_km": 3}))
    assert len(out2.section_narrative) == 3
    assert all(n.note for n in out2.section_narrative)


def test_extract_section_notes_tolerant() -> None:
    assert _extract_section_notes('{"section_notes": ["a", 2, "b"]}') == ["a", "b"]
    assert _extract_section_notes("pas du json") == []
    assert _extract_section_notes('{"section_notes": "oops"}') == []


def test_anchored_prompt_drops_minetti_digest_and_adds_sections() -> None:
    # Le digest chiffré de Minetti a disparu du prompt ancré (la baseline porte la physique).
    assert "+1% ≈ +15" not in STRATEGY_SYSTEM_PROMPT
    assert "≈ +110 s/km" not in STRATEGY_SYSTEM_PROMPT
    # Recentré sur la tactique + narratif par tranche.
    assert "TACTICS" in STRATEGY_SYSTEM_PROMPT
    assert "section_notes" in STRATEGY_SYSTEM_PROMPT
