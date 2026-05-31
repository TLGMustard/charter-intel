"""
pipeline/utils/ccd_closures_fetcher.py
Utility: fetch closed-school counts from the free, keyless Urban Institute
Education Data API (NCES CCD directory).

Closed public schools are a weak-but-real proxy for facilities feasibility: a
community/county that has shed school buildings has, in principle, more
candidate real estate than one that has not. The signal feeds
facilities_feasibility scoring in S5.

IMPORTANT CAVEAT (carried into the injected datapoint): a closed school is NOT
confirmed-available real estate. It may have been demolished, sold, repurposed,
or consolidated. The count is an availability *signal*, not an inventory.

DATA SOURCE:
  GET https://educationdata.urban.org/api/v1/schools/ccd/directory/{year}/  (no auth)

VERIFIED (live probe, 2026-05-30):
  - `school_status` is an integer field. Codes observed in NM: 1=open, 2=closed,
    3=new, 4=added, 5=changed boundary/agency, 6=temporarily closed, 7=future,
    8=reopened. We count CLOSED_STATUS_CODES = {2, 6}.
  - `ncessch` is the stable school id used for dedup; `leaid` is the district id;
    `county_code` is the 5-digit county FIPS (e.g. "35031" = McKinley, NM).
  - The `leaid` query param IS honored by the endpoint.
  - The `county_code` query param is SILENTLY IGNORED (a fips=35&county_code=X
    query returns the entire state). County scoping is therefore applied
    CLIENT-SIDE against the returned `county_code` field. We still send the param
    (harmless) so the request matches the documented shape.
  - Pagination follows the `next` URL; directory data is available through 2024.

CACHE:
  Responses cached at data/cache/fetcher/ccd_closures/{key}.json. The cache key
  encodes leaid + county_fips + the year window so distinct lookups never
  collide. TTL: 90 days.

ERROR CONTRACT:
  - Any non-200 / exception on a page request -> the affected scope contributes
    nothing; if NO year is available at all, return None.
  - Zero closures across all years is a VALID ZERO result, not "no data".
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import time
import urllib.request
from collections import Counter
from typing import Optional

log = logging.getLogger(__name__)

# ── API config ──────────────────────────────────────────────────────────────

CCD_API_BASE = "https://educationdata.urban.org/api/v1/schools/ccd/directory"
SOURCE_TITLE = "Urban Institute Education Data API — NCES CCD school directory"
SOURCE_URL = "https://educationdata.urban.org/api/v1/schools/ccd/directory/"

# Closed + temporarily closed. Confirmed against the endpoint's status codes.
CLOSED_STATUS_CODES = frozenset({2, 6})

DIRECTORY_YEARS = 6      # number of available directory years to scan
_MAX_YEAR_LOOKBACK = 12  # how far back to search to find DIRECTORY_YEARS available
_MAX_PAGES = 50          # pagination safety cap

CAVEAT = (
    "A closed school is NOT confirmed-available real estate — it may have been "
    "demolished, sold, repurposed, or consolidated. This count is an "
    "availability signal, not a verified facilities inventory."
)

# ── Cache config ──────────────────────────────────────────────────────────────

_CACHE_DIR = "data/cache/fetcher/ccd_closures"
CACHE_TTL_DAYS = 90


def _cache_path(key: str) -> str:
    return os.path.join(_CACHE_DIR, f"{key}.json")


def _read_cache(key: str) -> Optional[dict]:
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    age_days = (time.time() - os.path.getmtime(path)) / 86400
    if age_days > CACHE_TTL_DAYS:
        log.info("ccd_closures_fetcher: cache expired for key %s (%.0f days old)", key, age_days)
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as exc:
        log.warning("ccd_closures_fetcher: cache read failed for key %s — %s", key, exc)
        return None


def _write_cache(key: str, data: dict) -> None:
    path = _cache_path(key)
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as exc:
        log.warning("ccd_closures_fetcher: cache write failed for key %s — %s", key, exc)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get(url: str) -> Optional[dict]:
    """GET a JSON page; return parsed dict, or None on non-200 / parse failure."""
    req = urllib.request.Request(url, headers={"User-Agent": "CLIP/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                return None
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        log.warning("ccd_closures_fetcher: request failed for %s — %s", url, exc)
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("ccd_closures_fetcher: JSON parse error for %s — %s", url, exc)
        return None


def _fetch_paged(first_url: str) -> Optional[list[dict]]:
    """Follow the `next` chain from first_url. Returns all rows, [] if none,
    or None if the first request fails (so the scope is treated as unavailable).
    """
    resp = _get(first_url)
    if resp is None:
        return None
    rows: list[dict] = list(resp.get("results", []))
    nxt = resp.get("next")
    pages = 1
    while nxt and pages < _MAX_PAGES:
        resp = _get(nxt)
        if resp is None:
            break  # partial data is better than discarding the whole scope
        rows.extend(resp.get("results", []))
        nxt = resp.get("next")
        pages += 1
    return rows


def _directory_url(year: int, query: str) -> str:
    return f"{CCD_API_BASE}/{year}/?{query}"


def _closed_records(rows: list[dict], scope: str, year: int,
                    county_fips: Optional[str] = None,
                    leaid: Optional[str] = None) -> list[dict]:
    """Return trimmed closed-school records ({2,6}) matching the client-side guard."""
    out = []
    for r in rows:
        if r.get("school_status") not in CLOSED_STATUS_CODES:
            continue
        if county_fips is not None and str(r.get("county_code")) != str(county_fips):
            continue
        if leaid is not None and str(r.get("leaid")) != str(leaid):
            continue
        out.append({
            "ncessch": r.get("ncessch"),
            "school_name": r.get("school_name"),
            "year": year,
            "school_status": r.get("school_status"),
            "scope": scope,
        })
    return out


# ── Public interface ──────────────────────────────────────────────────────────

def get_closed_schools(
    leaid: Optional[str],
    state_fips: str,
    county_fips: Optional[str] = None,
) -> Optional[dict]:
    """Return closed-school counts for a district and its county, or None.

    Parameters
    ----------
    leaid       : 7-digit NCES district id (e.g. "3501110"). Required.
    state_fips  : 2-digit state FIPS (e.g. "35").
    county_fips : 5-digit county FIPS. If None, derived from the district's own
                  schools (their county_code field).

    Return shape:
        {
            "district_closed_count": 4,        # distinct closed schools in the LEA
            "county_closed_count":   5,        # distinct closed schools in the county
            "closed_count_total":    5,        # union deduped by ncessch -> C for S5
            "leaid": "3501110",
            "county_fips": "35031",
            "state_fips": "35",
            "years_queried": [2024, 2023, ...],
            "closed_schools": [ ... trimmed records ... ],
            "caveat": "...",
            "source": "URBAN_CCD", "source_url": ..., "source_title": ...,
            "confidence": "MODERATE",
        }

    Returns None if leaid is missing or no directory year could be fetched.
    A genuine zero (no closures found) returns counts of 0 — a VALID value.
    """
    if not leaid:
        log.info("ccd_closures_fetcher: no leaid provided — skipping")
        return None

    cache_key = f"closed_{leaid}_{county_fips or 'auto'}_{DIRECTORY_YEARS}y"
    cached = _read_cache(cache_key)
    if cached is not None:
        log.info("ccd_closures_fetcher: cache hit for %s", cache_key)
        return cached

    current_year = datetime.date.today().year

    district_ncessch: set = set()
    county_ncessch: set = set()
    closed_records: list[dict] = []
    years_queried: list[int] = []
    resolved_county = county_fips

    year = current_year
    floor = current_year - _MAX_YEAR_LOOKBACK
    while year > floor and len(years_queried) < DIRECTORY_YEARS:
        # District scope — leaid filter is honored server-side.
        dist_rows = _fetch_paged(_directory_url(year, f"fips={state_fips}&leaid={leaid}"))
        if not dist_rows:
            # None  -> request failed (e.g. HTTP 500); []  -> directory not yet
            # loaded for this year (future years return 200 with count=0). Either
            # way the year is not an "available directory year" — skip it.
            year -= 1
            continue

        years_queried.append(year)

        # Derive the county from the district's schools if not provided.
        if resolved_county is None:
            counties = Counter(
                str(r.get("county_code")) for r in dist_rows
                if r.get("county_code") not in (None, "")
            )
            if counties:
                resolved_county = counties.most_common(1)[0][0]

        for rec in _closed_records(dist_rows, "district", year, leaid=leaid):
            district_ncessch.add(rec["ncessch"])
            closed_records.append(rec)

        # County scope — county_code param is ignored server-side, so we fetch
        # the state directory and filter client-side on the county_code field.
        if resolved_county is not None:
            county_rows = _fetch_paged(
                _directory_url(year, f"fips={state_fips}&county_code={resolved_county}")
            )
            if county_rows is not None:
                for rec in _closed_records(county_rows, "county", year, county_fips=resolved_county):
                    if rec["ncessch"] not in county_ncessch:
                        county_ncessch.add(rec["ncessch"])
                        # Avoid duplicating a record already captured as district scope.
                        if rec["ncessch"] not in district_ncessch:
                            closed_records.append(rec)

        year -= 1

    if not years_queried:
        log.warning("ccd_closures_fetcher: no directory year available for leaid %s", leaid)
        return None

    union = district_ncessch | county_ncessch
    result = {
        "district_closed_count": len(district_ncessch),
        "county_closed_count": len(county_ncessch),
        "closed_count_total": len(union),
        "leaid": str(leaid),
        "county_fips": resolved_county,
        "state_fips": str(state_fips),
        "years_queried": years_queried,
        "closed_schools": closed_records,
        "caveat": CAVEAT,
        "source": "URBAN_CCD",
        "source_url": SOURCE_URL,
        "source_title": SOURCE_TITLE,
        "confidence": "MODERATE",
    }
    log.info(
        "ccd_closures_fetcher: leaid %s county %s — district_closed=%d county_closed=%d C=%d over %d years",
        leaid, resolved_county, len(district_ncessch), len(county_ncessch), len(union), len(years_queried),
    )
    _write_cache(cache_key, result)
    return result
