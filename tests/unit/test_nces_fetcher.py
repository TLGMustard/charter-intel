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
