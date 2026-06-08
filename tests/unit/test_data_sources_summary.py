"""
tests/unit/test_data_sources_summary.py

Tests for the Session 10 Item 3 "Data Sources & Confidence" summary:
  - _build_data_sources state-awareness + status logic
  - the block renders in all three brief templates for all four states
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from jinja2 import Environment, FileSystemLoader
from pipeline.s6_synthesis import _build_data_sources

pytestmark = pytest.mark.unit

_TEMPLATES = ["greenfield_brief.html.j2", "strategic_brief.html.j2", "ineligible_brief.html.j2"]


def _fact(k, y):
    return {"fact_key": k, "value_year": y}


def _bundle(state, has_prof):
    facts = [
        _fact("iep_pct", 2021), _fact("chronic_absenteeism_pct", 2021),
        _fact("teacher_median_wage", 2025), _fact("ell_pct", 2022),
        _fact("charter_enrollment_share_pct", 2023),
    ]
    if state.upper() == "MS":
        facts.append(_fact("district_accountability_rating", 2024))
    if has_prof:
        facts.append(_fact("district_proficiency_ela_pct", 2023))
    return {"has_proficiency_data": has_prof, "facts": facts}


# ── _build_data_sources logic ───────────────────────────────────────────────────

class TestBuildDataSources:
    def test_ms_includes_mde_and_msrc(self):
        rows = _build_data_sources({}, _bundle("MS", True), "MS")
        sources = {r["source"] for r in rows}
        assert "MDE Ratings" in sources
        assert any("MSRC" in s for s in sources)
        bls = next(r for r in rows if r["source"] == "BLS OEWS")
        assert bls["status_icon"] == "✓" and bls["vintage"] == "2025"

    def test_tn_proficiency_not_yet_available(self):
        rows = _build_data_sources({}, _bundle("TN", False), "TN")
        prof = next(r for r in rows if "TCAP" in r["source"])
        assert prof["status"] == "Not yet available"
        assert prof["status_icon"] == "✗"
        # MDE ratings row is MS-only
        assert all(r["source"] != "MDE Ratings" for r in rows)

    def test_wi_proficiency_label(self):
        rows = _build_data_sources({}, _bundle("WI", False), "WI")
        assert any("Forward Exam" in r["source"] for r in rows)

    def test_nm_proficiency_label_when_present(self):
        rows = _build_data_sources({}, _bundle("NM", True), "NM")
        prof = next(r for r in rows if "NM PED" in r["source"])
        assert prof["status_icon"] in {"✓", "⚠"}  # has data → not the ✗ path

    def test_status_icons_are_known(self):
        rows = _build_data_sources({}, _bundle("MS", True), "MS")
        assert all(r["status_icon"] in {"✓", "⚠", "✗"} for r in rows)

    def test_never_raises_on_empty_bundle(self):
        rows = _build_data_sources({}, {}, "TN")
        assert isinstance(rows, list) and len(rows) >= 1


# ── template rendering ────────────────────────────────────────────────────────────

def _render(template_name, state, has_prof):
    env = Environment(loader=FileSystemLoader(os.path.join(_ROOT, "templates")), autoescape=True)
    data_sources = _build_data_sources({}, _bundle(state, has_prof), state)
    brief = {
        "community_name": "Testville", "state": state, "composite_score": 6.0,
        "confidence_overall": "MODERATE", "data_through": "2023-12-31",
        "data_coverage_tier": "reliable", "executive_snapshot": "x",
        "classification": "Established", "market_type": "established", "verdict": "ELIGIBLE",
        "statutory_barrier": None, "data_sources": data_sources,
        "scorecard_summary": {"tier_display_label": "Moderate", "composite_score": 6.0,
                               "top_drivers": [], "dimension_table": [],
                               "excluded_dimensions": [], "override_flags": []},
        "recommendations": [], "quick_reads": {"facilities": "a", "political": "b", "authorizer": "c"},
        "needs_verification": [], "sources": [], "top_charter_schools": [], "local_authorizers": [],
    }
    return env.get_template(template_name).render(
        brief=brief,
        debug={"run_id": "x", "timestamp": "t", "depth": "standard", "token_rows": [], "warn_lines": []},
        schools=[], pci_promoted=False,
    )


@pytest.mark.parametrize("template", _TEMPLATES)
@pytest.mark.parametrize("state,has_prof", [("MS", True), ("NM", True), ("TN", False), ("WI", False)])
def test_data_sources_block_renders(template, state, has_prof):
    html = _render(template, state, has_prof)
    assert "Data Sources &amp; Confidence" in html or "Data Sources & Confidence" in html
    assert "BLS OEWS" in html
    if state == "MS":
        assert "MDE Ratings" in html
    if not has_prof:
        assert "Not yet available" in html
