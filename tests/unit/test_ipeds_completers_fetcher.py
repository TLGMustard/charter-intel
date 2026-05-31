"""
tests/unit/test_ipeds_completers_fetcher.py

Unit tests for pipeline/utils/ipeds_completers_fetcher.py.
Mocks the network and the filesystem cache; zero real network calls. Fixtures
are trimmed from REAL Urban Institute IPEDS completions-cip-2 responses for NM
(CIP 13). Verifies the aggregate-row summation (race=99/sex=99/majornum=1 only,
avoiding demographic double-counting), latest-year discovery past HTTP 500s,
valid-zero vs None-on-error, and cache stability.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import unittest.mock as mock

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pipeline.utils.ipeds_completers_fetcher as ipeds

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_disk_cache(monkeypatch):
    monkeypatch.setattr(ipeds, "_read_cache", lambda key: None)
    monkeypatch.setattr(ipeds, "_write_cache", lambda key, data: None)


def _r(race, sex, majornum, award_level, awards):
    return {
        "unitid": 1, "year": 2022, "fips": 35, "cipcode": 130000,
        "award_level": award_level, "majornum": majornum,
        "race": race, "sex": sex, "awards": awards,
    }


# Aggregate rows (race=99, sex=99, majornum=1) across two award levels -> 150,
# plus split rows that MUST be excluded to avoid triple-counting.
REAL_ROWS = [
    _r(99, 99, 1, 5, 100),    # counted
    _r(99, 99, 1, 7, 50),     # counted
    _r(1, 1, 1, 5, 30),       # race+sex split -> excluded
    _r(99, 99, 2, 5, 9),      # second major -> excluded
    _r(99, 1, 1, 5, 40),      # sex split -> excluded
    _r(99, 99, 1, 9, None),   # null awards -> treated as 0
]


def _resp(body: dict, status: int = 200):
    cm = mock.MagicMock()
    inner = cm.__enter__.return_value
    inner.status = status
    inner.read.return_value = json.dumps(body).encode("utf-8")
    cm.__exit__.return_value = False
    return cm


# ── _get ──────────────────────────────────────────────────────────────────────

class TestGet:
    def test_200(self):
        with mock.patch("urllib.request.urlopen", return_value=_resp({"results": [], "next": None})):
            assert ipeds._get("http://x") == {"results": [], "next": None}

    def test_500_returns_none(self):
        with mock.patch("urllib.request.urlopen", return_value=_resp({}, status=500)):
            assert ipeds._get("http://x") is None

    def test_exception_returns_none(self):
        with mock.patch("urllib.request.urlopen", side_effect=Exception("HTTP 500")):
            assert ipeds._get("http://x") is None


# ── _sum_completers: aggregate-row only ───────────────────────────────────────

class TestSumCompleters:
    def test_sums_only_aggregate_rows(self):
        assert ipeds._sum_completers(REAL_ROWS) == 150

    def test_empty(self):
        assert ipeds._sum_completers([]) == 0


# ── get_completers ────────────────────────────────────────────────────────────

class TestGetCompleters:
    def test_discovers_year_past_http_500s(self):
        # current year and current-1 fail (None); current-2 returns rows
        with mock.patch.object(ipeds, "_fetch_paged", side_effect=[None, None, REAL_ROWS]):
            r = ipeds.get_completers("35")
        assert r["completers"] == 150
        assert r["cipcode"] == ipeds.CIP_EDUCATION
        assert r["data_year"] == datetime.date.today().year - 2
        assert r["source"] == "IPEDS"

    def test_valid_zero_when_year_empty(self):
        with mock.patch.object(ipeds, "_fetch_paged", side_effect=lambda url: []):
            r = ipeds.get_completers("35")
        assert r is not None
        assert r["completers"] == 0

    def test_none_when_all_years_fail(self):
        with mock.patch.object(ipeds, "_fetch_paged", side_effect=lambda url: None):
            assert ipeds.get_completers("35") is None

    def test_none_without_state_fips(self):
        assert ipeds.get_completers("") is None

    def test_uses_6_digit_cipcode_constant(self):
        assert ipeds.CIP_EDUCATION == "130000"

    def test_cache_hit_skips_fetch(self, monkeypatch):
        canned = {"completers": 2351, "data_year": 2022}
        monkeypatch.setattr(ipeds, "_read_cache", lambda key: canned)
        with mock.patch.object(ipeds, "_fetch_paged") as m:
            r = ipeds.get_completers("35")
        m.assert_not_called()
        assert r == canned
