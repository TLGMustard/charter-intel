"""
tests/unit/test_tn_wi_proficiency.py

Unit tests for the TN (TCAP) and WI (Forward Exam) proficiency adapters.

These mirror the MS adapter tests. Because the authoritative district files are
not yet downloaded into data/raw/{tn,wi}/, the adapters return None in the repo's
current state (graceful degradation). The happy-path tests point CSV_PATH at a
temp file so we exercise parsing without committing fabricated proficiency data.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pipeline.fetchers.tn_proficiency_fetcher as tn
import pipeline.fetchers.wi_proficiency_fetcher as wi

pytestmark = pytest.mark.unit

_REQUIRED_KEYS = {
    "ela_proficiency_pct", "math_proficiency_pct",
    "school_year", "source_url", "source_title", "confidence",
}

_CSV_HEADER = "LEAID,DistrictName,EntityID,ELAProficiencyPct,MathProficiencyPct,SchoolYear\n"


def _write_csv(tmp_path, rows: str):
    p = tmp_path / "prof.csv"
    p.write_text(_CSV_HEADER + rows, encoding="utf-8")
    return str(p)


# ── graceful degradation: no CSV present (the repo's real current state) ───────

class TestGracefulDegradation:
    def test_tn_returns_none_without_csv(self, monkeypatch):
        monkeypatch.setattr(tn, "CSV_PATH", "data/raw/tn/does_not_exist.csv")
        assert tn.fetch_tn_proficiency("4700148") is None
        assert tn.get_tn_district_data("tn-alamo-4700030") is None

    def test_wi_returns_none_without_csv(self, monkeypatch):
        monkeypatch.setattr(wi, "CSV_PATH", "data/raw/wi/does_not_exist.csv")
        assert wi.fetch_wi_proficiency("5509600") is None
        assert wi.get_wi_district_data("wi-abbotsford") is None


# ── happy path: temp CSV populated (no fabricated data committed) ──────────────

class TestTNAdapter:
    def test_parses_row(self, tmp_path, monkeypatch):
        csv_path = _write_csv(tmp_path, "4700148,MEMPHIS SHELBY CO,0001,28.5,22.1,2023-24\n")
        monkeypatch.setattr(tn, "CSV_PATH", csv_path)
        r = tn.fetch_tn_proficiency("4700148")
        assert r is not None
        assert _REQUIRED_KEYS.issubset(r.keys())
        assert r["ela_proficiency_pct"] == 28.5
        assert r["math_proficiency_pct"] == 22.1
        assert r["school_year"] == "2023-2024"
        assert "tn.gov" in r["source_url"]

    def test_missing_leaid_returns_none(self, tmp_path, monkeypatch):
        csv_path = _write_csv(tmp_path, "4700148,MEMPHIS,0001,28.5,22.1,2023-24\n")
        monkeypatch.setattr(tn, "CSV_PATH", csv_path)
        assert tn.fetch_tn_proficiency("9999999") is None

    def test_leading_zero_leaid(self, tmp_path, monkeypatch):
        csv_path = _write_csv(tmp_path, "4700030,ALAMO CITY,0002,40.0,35.0,2023-24\n")
        monkeypatch.setattr(tn, "CSV_PATH", csv_path)
        # stored 7-digit, queried with leading zero stripped form should still hit
        assert tn.fetch_tn_proficiency("4700030") is not None

    def test_community_id_lookup_uses_nces_map(self, tmp_path, monkeypatch):
        # tn-alamo-4700030 maps to LEAID 4700030 in states.yaml
        csv_path = _write_csv(tmp_path, "4700030,ALAMO CITY,0002,40.0,35.0,2023-24\n")
        monkeypatch.setattr(tn, "CSV_PATH", csv_path)
        r = tn.get_tn_district_data("tn-alamo-4700030")
        assert r is not None
        assert r["ela_proficiency_pct"] == 40.0


class TestWIAdapter:
    def test_parses_row(self, tmp_path, monkeypatch):
        csv_path = _write_csv(tmp_path, "5500030,ABBOTSFORD,0003,55.2,48.7,2023-24\n")
        monkeypatch.setattr(wi, "CSV_PATH", csv_path)
        r = wi.fetch_wi_proficiency("5500030")
        assert r is not None
        assert _REQUIRED_KEYS.issubset(r.keys())
        assert r["ela_proficiency_pct"] == 55.2
        assert "dpi.wi.gov" in r["source_url"]

    def test_community_id_lookup_uses_nces_map(self, tmp_path, monkeypatch):
        # wi-abbotsford maps to LEAID 5500030 in states.yaml
        csv_path = _write_csv(tmp_path, "5500030,ABBOTSFORD,0003,55.2,48.7,2023-24\n")
        monkeypatch.setattr(wi, "CSV_PATH", csv_path)
        r = wi.get_wi_district_data("wi-abbotsford")
        assert r is not None
        assert r["math_proficiency_pct"] == 48.7


# ── interface parity with the MS adapter ───────────────────────────────────────

def test_adapter_return_shape_matches_ms(tmp_path, monkeypatch):
    """TN/WI adapters must return the same key set as the MS adapter."""
    from pipeline.fetchers.ms_proficiency_fetcher import fetch_ms_proficiency
    ms = fetch_ms_proficiency("2803450")  # Oxford — real committed data
    assert ms is not None
    assert _REQUIRED_KEYS.issubset(ms.keys())

    tn_csv = _write_csv(tmp_path, "4700148,MEMPHIS,0001,28.5,22.1,2023-24\n")
    monkeypatch.setattr(tn, "CSV_PATH", tn_csv)
    assert set(tn.fetch_tn_proficiency("4700148").keys()) == set(ms.keys())
