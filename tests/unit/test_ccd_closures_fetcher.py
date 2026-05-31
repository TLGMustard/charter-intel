"""
tests/unit/test_ccd_closures_fetcher.py

Unit tests for pipeline/utils/ccd_closures_fetcher.py.
Mocks the network and the filesystem cache; zero real network calls. Fixtures
are trimmed from REAL Urban Institute CCD directory responses for NM
(Gallup / McKinley county). Verifies status-code filtering (only 2 & 6),
client-side county filtering (the county_code query param is ignored server-side),
dedup by ncessch, pagination, valid-zero vs None-on-error, and cache stability.
"""
from __future__ import annotations

import json
import os
import sys
import unittest.mock as mock

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pipeline.utils.ccd_closures_fetcher as ccd

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_disk_cache(monkeypatch):
    monkeypatch.setattr(ccd, "_read_cache", lambda key: None)
    monkeypatch.setattr(ccd, "_write_cache", lambda key, data: None)


def _rec(ncessch, status, leaid="3501110", county="35031", name="SCHOOL"):
    return {
        "ncessch": ncessch, "leaid": leaid, "school_name": name,
        "school_status": status, "county_code": county, "year": 2020,
    }


# Real-shaped Gallup district rows: open(1), closed(2), temp-closed(6), new(3).
DISTRICT_ROWS = [
    _rec("350111000299", 1, name="CATHERINE A. MILLER ELEMENTARY"),
    _rec("350111000900", 2, name="CLOSED ELEM"),          # closed
    _rec("350111000901", 6, name="TEMP CLOSED MIDDLE"),   # temporarily closed
    _rec("350111000902", 3, name="BRAND NEW SCHOOL"),     # new -> ignored
]
# County rows: the two district-closed schools, one county-only closed school
# (different leaid, same county), and a closed school in ANOTHER county that the
# client-side filter must drop (the server ignores county_code).
COUNTY_ROWS = [
    _rec("350111000900", 2),
    _rec("350111000901", 6),
    _rec("350222000502", 2, leaid="3502220", name="COUNTY-ONLY CLOSED"),
    _rec("359999000999", 2, leaid="3599990", county="35099", name="OTHER COUNTY CLOSED"),
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
    def test_200_returns_dict(self):
        with mock.patch("urllib.request.urlopen", return_value=_resp({"results": [], "next": None})):
            assert ccd._get("http://x")["results"] == []

    def test_non_200_returns_none(self):
        with mock.patch("urllib.request.urlopen", return_value=_resp({}, status=500)):
            assert ccd._get("http://x") is None

    def test_exception_returns_none(self):
        with mock.patch("urllib.request.urlopen", side_effect=Exception("boom")):
            assert ccd._get("http://x") is None


# ── _fetch_paged ──────────────────────────────────────────────────────────────

class TestFetchPaged:
    def test_follows_next_chain(self):
        p1 = {"results": [_rec("a", 1)], "next": "http://next"}
        p2 = {"results": [_rec("b", 2)], "next": None}
        with mock.patch.object(ccd, "_get", side_effect=[p1, p2]) as m:
            rows = ccd._fetch_paged("http://first")
        assert len(rows) == 2
        assert m.call_count == 2

    def test_first_request_failure_returns_none(self):
        with mock.patch.object(ccd, "_get", side_effect=[None]):
            assert ccd._fetch_paged("http://first") is None


# ── _closed_records: status + client-side guards ──────────────────────────────

class TestClosedRecords:
    def test_only_status_2_and_6_counted(self):
        recs = ccd._closed_records(DISTRICT_ROWS, "district", 2020, leaid="3501110")
        statuses = {r["school_status"] for r in recs}
        assert statuses == {2, 6}
        assert len(recs) == 2

    def test_county_client_side_filter_drops_other_counties(self):
        recs = ccd._closed_records(COUNTY_ROWS, "county", 2020, county_fips="35031")
        ncessch = {r["ncessch"] for r in recs}
        assert "359999000999" not in ncessch     # the 35099 record is dropped
        assert len(recs) == 3

    def test_trimmed_record_shape(self):
        rec = ccd._closed_records([_rec("n1", 2)], "district", 2021, leaid="3501110")[0]
        assert set(rec) == {"ncessch", "school_name", "year", "school_status", "scope"}
        assert rec["year"] == 2021 and rec["scope"] == "district"


# ── get_closed_schools ────────────────────────────────────────────────────────

def _fake_fetch_full(url):
    """District query -> DISTRICT_ROWS; county query -> COUNTY_ROWS (every year)."""
    if "leaid=" in url:
        return list(DISTRICT_ROWS)
    return list(COUNTY_ROWS)


class TestGetClosedSchools:
    def test_counts_dedup_and_county_derivation(self):
        with mock.patch.object(ccd, "_fetch_paged", side_effect=_fake_fetch_full):
            r = ccd.get_closed_schools("3501110", "35")
        # closures repeat across years but dedupe by ncessch
        assert r["district_closed_count"] == 2
        assert r["county_closed_count"] == 3        # 2 district + 1 county-only
        assert r["closed_count_total"] == 3         # union deduped
        assert r["county_fips"] == "35031"          # derived from district rows
        assert len(r["years_queried"]) == ccd.DIRECTORY_YEARS
        assert "demolished" in r["caveat"]

    def test_valid_zero_when_no_closures(self):
        open_only = [_rec("350111000299", 1)]
        with mock.patch.object(ccd, "_fetch_paged", side_effect=lambda url: list(open_only)):
            r = ccd.get_closed_schools("3501110", "35")
        assert r is not None
        assert r["district_closed_count"] == 0
        assert r["county_closed_count"] == 0
        assert r["closed_count_total"] == 0

    def test_none_when_no_year_available(self):
        # every district query empty -> no available directory year -> None
        with mock.patch.object(ccd, "_fetch_paged", side_effect=lambda url: []):
            assert ccd.get_closed_schools("3501110", "35") is None

    def test_none_without_leaid(self):
        assert ccd.get_closed_schools(None, "35") is None

    def test_explicit_county_fips_respected(self):
        with mock.patch.object(ccd, "_fetch_paged", side_effect=_fake_fetch_full):
            r = ccd.get_closed_schools("3501110", "35", county_fips="35031")
        assert r["county_fips"] == "35031"

    def test_cache_hit_skips_fetch(self, monkeypatch):
        canned = {"closed_count_total": 9}
        monkeypatch.setattr(ccd, "_read_cache", lambda key: canned)
        with mock.patch.object(ccd, "_fetch_paged") as m:
            r = ccd.get_closed_schools("3501110", "35")
        m.assert_not_called()
        assert r == canned

    def test_cache_key_stable_for_same_args(self):
        k1 = f"closed_3501110_auto_{ccd.DIRECTORY_YEARS}y"
        # mirror the key construction in get_closed_schools
        assert ccd._cache_path(k1).endswith(f"closed_3501110_auto_{ccd.DIRECTORY_YEARS}y.json")
