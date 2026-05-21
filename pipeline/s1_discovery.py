"""
pipeline/s1_discovery.py
Stage 1: Community Discovery

PURPOSE:
  Parse the state's charter school roster and identify all charter-active
  communities (grouped by municipality). No LLM is used. Pure data processing.

INPUT:
  - State charter school roster (downloaded CSV/Excel from state PED)
  - states.yaml (community boundary rules)

OUTPUT:
  - data/processed/{state}/community_list.json
  - A list of CommunityStub objects, each identifying a unique charter-active municipality

NOTES:
  - This stage is idempotent. Re-running it with the same source data produces
    identical output.
  - The roster must be downloaded manually (or via a state-specific scraper)
    and placed in data/raw/{state}/charter_roster.csv before running.
  - This stage does NOT fetch the roster from the internet.
"""

from __future__ import annotations
import csv
import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Optional

from pipeline import (
    PipelineConfig, StageResult, StageStatus, ValidationResult,
    build_community_id, today_str
)
from pipeline.utils.cache import CacheManager
from pipeline.utils.schema_validator import validate_against_schema


STAGE_ID = "s1_discovery"


# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────

@dataclass
class SchoolStub:
    """Minimal school record from the PED roster."""
    school_name: str
    state: str
    city: str
    county: Optional[str]
    authorizer_name: Optional[str]
    grades: Optional[str]
    school_type: str          # "CHARTER" always for this pipeline
    status: str               # "ACTIVE" | "PENDING" | "CLOSED"
    source_row: int           # row number in source CSV for debugging


@dataclass
class CommunityStub:
    """Minimal community record — expanded by later stages."""
    community_id: str
    name: str
    state: str
    school_count: int
    school_names: list[str]
    county: Optional[str]
    boundary_type: str        # from states.yaml
    discovered_at: str
    source_file: str


# ─────────────────────────────────────────────
# FIELD MAPPING
# ─────────────────────────────────────────────
# Maps state-specific column names to canonical field names.
# Add a new entry when onboarding a new state.

ROSTER_FIELD_MAPS: dict[str, dict[str, str]] = {
    "NM": {
        "school_name":    "School Name",      # TODO: verify exact NM PED column names
        "city":           "City",
        "county":         "County",
        "authorizer":     "Authorizer",
        "grades":         "Grade Levels",
        "status":         "Status",
    },
    # Add additional states here
}


# ─────────────────────────────────────────────
# MAIN STAGE FUNCTION
# ─────────────────────────────────────────────

def run(
    community_id: str,  # Not used in S1 — discovery runs at state level
    state: str,
    config: PipelineConfig,
    **kwargs
) -> StageResult:
    """
    Discover all charter-active communities in the given state.
    
    Returns a StageResult where output_data contains a list of CommunityStub dicts.
    Also writes community_list.json to data/processed/{state}/.
    """
    start = _now()
    roster_path = _roster_path(state)

    # --- Validate prerequisites ---
    validation = validate_prerequisites(state, roster_path)
    if not validation:
        return StageResult(
            stage_id=STAGE_ID,
            community_id="ALL",
            state=state,
            status=StageStatus.ERROR,
            errors=validation.errors
        )

    # --- Check cache ---
    cache = CacheManager(config)
    cache_key = f"state/{state}/s1_community_list_{today_str()}.json"
    if config.cache_enabled and not config.force_refresh:
        cached = cache.get(cache_key)
        if cached:
            return StageResult(
                stage_id=STAGE_ID, community_id="ALL", state=state,
                status=StageStatus.SUCCESS, output_data=cached,
                cache_hit=True
            )

    # --- Parse roster ---
    schools = parse_roster(roster_path, state)
    communities = group_by_community(schools, state)

    # --- Apply community filter (if config specifies specific communities) ---
    if config.communities:
        communities = [c for c in communities if c.community_id in config.communities]

    output = {
        "state": state,
        "discovered_at": today_str(),
        "source_file": roster_path,
        "total_schools": len(schools),
        "total_communities": len(communities),
        "communities": [asdict(c) for c in communities]
    }

    # --- Write output ---
    out_path = _output_path(state)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    # --- Cache ---
    cache.set(cache_key, output)

    duration = _elapsed(start)
    return StageResult(
        stage_id=STAGE_ID,
        community_id="ALL",
        state=state,
        status=StageStatus.SUCCESS,
        output_path=out_path,
        output_data=output,
        duration_seconds=duration
    )


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def parse_roster(roster_path: str, state: str) -> list[SchoolStub]:
    """Parse the state CSV roster into SchoolStub objects."""
    field_map = ROSTER_FIELD_MAPS.get(state, {})
    schools = []

    with open(roster_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):  # Row 1 = header
            city = _clean_city(row.get(field_map.get("city", "City"), "").strip())
            status = row.get(field_map.get("status", "Status"), "ACTIVE").strip().upper()

            if status == "CLOSED":
                continue  # Exclude closed schools from active analysis

            if not city:
                # TODO: log and route to manual review
                continue

            schools.append(SchoolStub(
                school_name=row.get(field_map.get("school_name", "School Name"), "").strip(),
                state=state,
                city=city,
                county=row.get(field_map.get("county", "County"), "").strip() or None,
                authorizer_name=row.get(field_map.get("authorizer", "Authorizer"), "").strip() or None,
                grades=row.get(field_map.get("grades", "Grades"), "").strip() or None,
                school_type="CHARTER",
                status=status,
                source_row=i
            ))

    return schools


def group_by_community(schools: list[SchoolStub], state: str) -> list[CommunityStub]:
    """Group schools by municipality and return CommunityStub list."""
    grouped: dict[str, list[SchoolStub]] = {}

    for school in schools:
        cid = build_community_id(state, school.city)
        if cid not in grouped:
            grouped[cid] = []
        grouped[cid].append(school)

    communities = []
    for cid, school_list in sorted(grouped.items()):
        sample = school_list[0]
        communities.append(CommunityStub(
            community_id=cid,
            name=sample.city,
            state=state,
            school_count=len(school_list),
            school_names=[s.school_name for s in school_list],
            county=sample.county,
            boundary_type="MUNICIPALITY",
            discovered_at=today_str(),
            source_file=_roster_path(state)
        ))

    return communities


def validate_prerequisites(state: str, roster_path: str) -> ValidationResult:
    """Check that inputs are present before running."""
    errors = []
    if not os.path.exists(roster_path):
        errors.append(
            f"Charter roster not found at {roster_path}. "
            f"Download from the state PED site (see config/states.yaml) "
            f"and place at this path before running S1."
        )
    if state not in ROSTER_FIELD_MAPS:
        errors.append(
            f"No field mapping defined for state '{state}' in ROSTER_FIELD_MAPS. "
            f"Add an entry in s1_discovery.py."
        )
    return ValidationResult(valid=len(errors) == 0, errors=errors)


def _clean_city(city: str) -> str:
    """Normalize city strings — strip whitespace, title-case, remove suffixes."""
    city = city.strip().title()
    # Remove common suffixes that appear in PED data
    city = re.sub(r"\s*(,\s*NM|,\s*New Mexico)\s*$", "", city, flags=re.IGNORECASE)
    return city


def _roster_path(state: str) -> str:
    return f"data/raw/{state.lower()}/charter_roster.csv"


def _output_path(state: str) -> str:
    return f"data/processed/{state.lower()}/community_list.json"


def _now() -> float:
    import time
    return time.time()


def _elapsed(start: float) -> float:
    import time
    return round(time.time() - start, 2)
