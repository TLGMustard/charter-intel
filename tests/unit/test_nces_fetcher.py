"""
tests/unit/test_nces_fetcher.py

Unit tests for nces_fetcher helpers — focused on national parquet path
and graceful fallback when files are absent.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _ROOT)

import pipeline.utils.nces_fetcher as nf


def _write_finance_parquet(tmp_path, rows: list[dict]) -> None:
    """Write a minimal finance parquet at data/raw/national/nces_lea_finance.parquet."""
    nat_dir = tmp_path / "data" / "raw" / "national"
    nat_dir.mkdir(parents=True)
    df = pd.DataFrame(rows).set_index("LEAID")
    df.to_parquet(nat_dir / "nces_lea_finance.parquet", compression="snappy")


# ─────────────────────────────────────────────────────────────────────────────
# _read_finance — national parquet path
# ─────────────────────────────────────────────────────────────────────────────

def test_read_finance_returns_none_when_parquet_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # No national parquet present — must return None, not raise.
    result = nf._read_finance("3500060", "NM")
    assert result is None


def test_read_finance_returns_none_when_tx_parquet_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = nf._read_finance("4800001", "TX")
    assert result is None


def test_read_finance_reads_from_national_parquet(tmp_path, monkeypatch):
    """Finance is read from data/raw/national/nces_lea_finance.parquet, not state-specific paths."""
    monkeypatch.chdir(tmp_path)
    _write_finance_parquet(tmp_path, [
        {"LEAID": "4800001", "STABBR": "TX",
         "MEMBERSCH": 5000, "TOTALREV": 50000000, "TFEDREV": 5000000,
         "TSTREV": 20000000, "TLOCREV": 25000000, "TOTALEXP": 48000000},
    ])
    result = nf._read_finance("4800001", "TX")
    assert result is not None
    assert result["MEMBERSCH"] == 5000


def test_read_finance_returns_none_for_unknown_leaid(tmp_path, monkeypatch):
    """LEAID not present in parquet returns None, not an exception."""
    monkeypatch.chdir(tmp_path)
    _write_finance_parquet(tmp_path, [
        {"LEAID": "4800001", "STABBR": "TX",
         "MEMBERSCH": 5000, "TOTALREV": 50000000, "TFEDREV": 5000000,
         "TSTREV": 20000000, "TLOCREV": 25000000, "TOTALEXP": 48000000},
    ])
    result = nf._read_finance("9999999", "TX")
    assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# get_district_data — state param threads into _read_finance
# ─────────────────────────────────────────────────────────────────────────────

def test_get_district_data_passes_state_to_read_finance(monkeypatch):
    """get_district_data must pass state to _read_finance (not hardcode 'nm')."""
    calls = []

    def fake_load_nces_map(state):
        return {"tx-austin": "4800001"}

    def fake_read_finance(leaid, state):
        calls.append(state)
        return None  # trigger early return — we only care that state was passed

    monkeypatch.setattr(nf, "_load_nces_map", fake_load_nces_map)
    monkeypatch.setattr(nf, "_read_finance", fake_read_finance)

    nf.get_district_data("tx-austin", "TX")

    assert calls == ["TX"]


# ─────────────────────────────────────────────────────────────────────────────
# per_pupil_revenue_avg null → parquet fallback; Oxford score in [5.5, 6.5]
# ─────────────────────────────────────────────────────────────────────────────

def test_state_avg_ppr_null_uses_parquet_fallback_oxford_score_range(tmp_path, monkeypatch):
    """When per_pupil_revenue_avg is null in states.yaml, _get_state_avg_ppr falls
    back to the national finance parquet (non-null result). With real Oxford FY2023
    values, the resulting per_pupil_revenue_vs_state_avg_pct is near zero — Oxford's
    total revenue per pupil ($16,176) ≈ the MS state average ($16,244 in this fixture)
    — placing the funding_environment threshold score in [5.5, 6.5].

    This test guards against reintroduction of the stale $12,500 hardcode that
    inflated Oxford's premium to 29.4% and its score to 9.0.
    """
    monkeypatch.chdir(tmp_path)

    # Minimal states.yaml: MS per_pupil_revenue_avg is null so the parquet fallback fires.
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "states.yaml").write_text(
        "MS:\n"
        "  per_pupil_revenue_avg: null\n"
        "  nces_district_map:\n"
        "    ms-oxford-2803450: '2803450'\n"
        "    ms-peer-a: '2800010'\n"
        "    ms-peer-b: '2800020'\n"
    )

    # Parquet: Oxford + two peers chosen so state avg ≈ $16,244/pupil.
    #   Oxford:  TOTALREV=$77,094,000 / 4,766 members = $16,175.83/pupil
    #   Peer-A:  TOTALREV=$48,834,000 / 3,000         = $16,278.00/pupil
    #   Peer-B:  TOTALREV=$81,390,000 / 5,000         = $16,278.00/pupil
    #   Mean: ($16,175.83 + $16,278 + $16,278) / 3 ≈ $16,243.94/pupil
    _write_finance_parquet(tmp_path, [
        {"LEAID": "2803450", "STABBR": "MS", "MEMBERSCH": 4766, "TOTALREV": 77094000,
         "TFEDREV": 7932000, "TSTREV": 28776000, "TLOCREV": 40386000, "TOTALEXP": 80803000},
        {"LEAID": "2800010", "STABBR": "MS", "MEMBERSCH": 3000, "TOTALREV": 48834000,
         "TFEDREV": 4883400, "TSTREV": 19533600, "TLOCREV": 24416900, "TOTALEXP": 49000000},
        {"LEAID": "2800020", "STABBR": "MS", "MEMBERSCH": 5000, "TOTALREV": 81390000,
         "TFEDREV": 8139000, "TSTREV": 32556000, "TLOCREV": 40695000, "TOTALEXP": 82000000},
    ])

    # Part 1: parquet fallback produces a non-null state average.
    avg = nf._get_state_avg_ppr("MS")
    assert avg is not None, (
        "_get_state_avg_ppr must return a non-null value when parquet is present "
        "and states.yaml per_pupil_revenue_avg is null"
    )
    assert avg > 0

    # Part 2: Oxford's premium is near zero → funding_environment score in [5.5, 6.5].
    result = nf.get_district_data("ms-oxford-2803450", "MS")
    assert result is not None
    pct = result.get("per_pupil_revenue_vs_state_avg_pct")
    assert pct is not None

    # Oxford PPR ($16,176) ≈ state avg ($16,244): premium ≈ -0.4%.
    # Allow ±5 pct-point tolerance for parquet vintage variation.
    assert -5.0 <= pct <= 5.0, (
        f"Oxford per_pupil_revenue_vs_state_avg_pct={pct:.1f}% expected near 0% "
        f"on a total-revenue-vs-total-revenue basis; was 29.4% with stale $12,500 hardcode"
    )

    # Inline threshold lookup (mirrors scoring_weights.yaml funding_environment).
    # direction=direct: <= -20→2, <= -10→4, <= 0→6, <= 10→7, <= 20→8, >20→9
    def _threshold_score(p: float) -> float:
        for max_val, score in [(-20, 2.0), (-10, 4.0), (0, 6.0), (10, 7.0), (20, 8.0)]:
            if p <= max_val:
                return score
        return 9.0

    score = _threshold_score(pct)
    assert 5.5 <= score <= 6.5, (
        f"funding_environment threshold score {score} expected in [5.5, 6.5]; "
        f"per_pupil_revenue_vs_state_avg_pct={pct:.1f}%"
    )
