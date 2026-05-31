"""
tests/unit/test_s5_feasibility_scoring.py

Unit tests for the facilities_feasibility and replication_feasibility scoring
added to pipeline/s5_scoring.py. Covers every threshold boundary, the cap at 8,
the operator/pipeline mean (incl. single-signal fallback), and the
source-unavailable -> neutral-default-with-tag contract (never a fabricated
number).
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pipeline.s5_scoring as s5

pytestmark = pytest.mark.unit


# ── Facilities threshold table (capped at 8) ──────────────────────────────────

class TestFacilitiesThresholds:
    @pytest.mark.parametrize("c,expected", [
        (0, 3.0), (1, 5.0),
        (2, 6.0), (3, 6.0),
        (4, 7.0), (5, 7.0), (6, 7.0),
        (7, 8.0), (8, 8.0), (50, 8.0),
    ])
    def test_boundaries(self, c, expected):
        assert s5._facilities_score_from_closed_count(c) == expected

    def test_never_exceeds_8(self):
        assert all(s5._facilities_score_from_closed_count(c) <= 8.0 for c in range(0, 200))


# ── Replication operator sub-signal boundaries ────────────────────────────────

class TestOperatorScore:
    @pytest.mark.parametrize("o,expected", [
        (0, 3.0), (1, 5.0), (2, 5.0),
        (3, 6.0), (5, 6.0),
        (6, 7.0), (10, 7.0),
        (11, 8.0), (28, 8.0),
    ])
    def test_boundaries(self, o, expected):
        assert s5._replication_operator_score(o) == expected


# ── Replication pipeline sub-signal boundaries ────────────────────────────────

class TestPipelineScore:
    @pytest.mark.parametrize("p,expected", [
        (0, 3.0), (199, 3.0),
        (200, 5.0), (499, 5.0),
        (500, 6.0), (999, 6.0),
        (1000, 7.0), (1999, 7.0),
        (2000, 8.0), (2351, 8.0),
    ])
    def test_boundaries(self, p, expected):
        assert s5._replication_pipeline_score(p) == expected


# ── Helpers to build a fact bundle ────────────────────────────────────────────

def _fact(fact_key, value, dim):
    return {
        "datapoint_id": f"dp_x_{fact_key}", "dimension": dim, "fact_key": fact_key,
        "value": value, "in_main_analysis": True, "confidence": "MODERATE",
    }


def _bundle(*facts):
    return {"facts": list(facts)}


# ── score_dimension: facilities ───────────────────────────────────────────────

class TestFacilitiesDimension:
    def test_scored_value(self):
        b = _bundle(_fact("facilities_closed_schools_count", 3, "facilities_feasibility"))
        out = s5.score_dimension("facilities_feasibility", {}, b, 0.1)
        assert out["score"] == 6.0
        assert out["used_default"] is False
        assert out["confidence"] == "MODERATE"
        assert "unscored_reason" not in out

    def test_zero_is_a_valid_scored_value(self):
        b = _bundle(_fact("facilities_closed_schools_count", 0, "facilities_feasibility"))
        out = s5.score_dimension("facilities_feasibility", {}, b, 0.1)
        assert out["score"] == 3.0
        assert out["used_default"] is False

    def test_missing_source_defaults_with_tag(self):
        out = s5.score_dimension("facilities_feasibility", {}, _bundle(), 0.1)
        assert out["score"] == 5.0
        assert out["used_default"] is True
        assert out["unscored_reason"]               # non-empty reason present
        assert "unavailable" in out["unscored_reason"]


# ── score_dimension: replication ──────────────────────────────────────────────

class TestReplicationDimension:
    def test_mean_of_both_signals(self):
        b = _bundle(
            _fact("csp_distinct_operators", 4, "replication_feasibility"),   # ->6
            _fact("cip13_completers", 2351, "replication_feasibility"),      # ->8
        )
        out = s5.score_dimension("replication_feasibility", {}, b, 0.1)
        assert out["score"] == 7.0      # round(mean(6,8)) = 7
        assert out["used_default"] is False

    def test_single_signal_operator_only(self):
        b = _bundle(_fact("csp_distinct_operators", 1, "replication_feasibility"))  # ->5
        out = s5.score_dimension("replication_feasibility", {}, b, 0.1)
        assert out["score"] == 5.0
        assert out["used_default"] is False

    def test_single_signal_pipeline_only(self):
        b = _bundle(_fact("cip13_completers", 700, "replication_feasibility"))  # ->6
        out = s5.score_dimension("replication_feasibility", {}, b, 0.1)
        assert out["score"] == 6.0
        assert out["used_default"] is False

    def test_zero_operators_is_valid_scored_value(self):
        b = _bundle(_fact("csp_distinct_operators", 0, "replication_feasibility"))  # ->3
        out = s5.score_dimension("replication_feasibility", {}, b, 0.1)
        assert out["score"] == 3.0
        assert out["used_default"] is False

    def test_both_missing_defaults_with_tag(self):
        out = s5.score_dimension("replication_feasibility", {}, _bundle(), 0.1)
        assert out["score"] == 5.0
        assert out["used_default"] is True
        assert out["unscored_reason"]

    def test_round_half_uses_python_banker_rounding(self):
        # operators=1 (->5), completers<200 (->3): mean=4.0 exactly
        b = _bundle(
            _fact("csp_distinct_operators", 1, "replication_feasibility"),
            _fact("cip13_completers", 100, "replication_feasibility"),
        )
        out = s5.score_dimension("replication_feasibility", {}, b, 0.1)
        assert out["score"] == 4.0
