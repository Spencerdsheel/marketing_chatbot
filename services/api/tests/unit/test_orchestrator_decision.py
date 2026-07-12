"""Unit tests for the pure ``_decide`` confidence-band function (S10.2).

Covers the boundary semantics (decision 2/3): ``confidence >=
answer_threshold`` -> answer; ``[escalate_threshold, answer_threshold)`` ->
clarify; ``confidence < escalate_threshold`` -> escalate. Also covers the
collapsed-band case where the two thresholds are equal.
"""
from __future__ import annotations

from api.orchestrator.config_repository import OrchestratorConfig
from api.orchestrator.service import _decide


def _cfg(answer_threshold: float = 0.5, escalate_threshold: float = 0.35) -> OrchestratorConfig:
    return OrchestratorConfig(answer_threshold=answer_threshold, escalate_threshold=escalate_threshold)


def test_above_answer_threshold_is_answer() -> None:
    assert _decide(0.9, _cfg()) == "answer"


def test_at_answer_threshold_boundary_is_answer() -> None:
    """confidence == answer_threshold exactly -> answer (>=, not >)."""
    assert _decide(0.5, _cfg()) == "answer"


def test_middle_band_is_clarify() -> None:
    assert _decide(0.4, _cfg()) == "clarify"


def test_at_escalate_threshold_boundary_is_clarify() -> None:
    """confidence == escalate_threshold exactly -> clarify (>=, not escalate)."""
    assert _decide(0.35, _cfg()) == "clarify"


def test_just_below_escalate_threshold_is_escalate() -> None:
    assert _decide(0.349, _cfg()) == "escalate"


def test_zero_confidence_is_escalate() -> None:
    assert _decide(0.0, _cfg()) == "escalate"


def test_collapsed_band_never_returns_clarify() -> None:
    """escalate_threshold == answer_threshold -> only answer/escalate, no clarify."""
    cfg = _cfg(answer_threshold=0.5, escalate_threshold=0.5)

    assert _decide(0.5, cfg) == "answer"
    assert _decide(0.6, cfg) == "answer"
    assert _decide(0.49, cfg) == "escalate"
    assert _decide(0.0, cfg) == "escalate"


def test_custom_tenant_thresholds_honored() -> None:
    """A high answer_threshold demonstrates the function reads cfg, not a constant."""
    cfg = _cfg(answer_threshold=0.9, escalate_threshold=0.35)

    assert _decide(0.6, cfg) == "clarify"
    assert _decide(0.9, cfg) == "answer"
