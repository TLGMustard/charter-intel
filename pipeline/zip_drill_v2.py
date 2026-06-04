"""
pipeline/zip_drill_v2.py
ZIP Drill v2 — Addendum to v1. Three new capabilities:

  1. ZCTA shapefiles (Census TIGER/Line 2023) — geographic context + SVG map
  2. Topological neighbor analysis — adjacent ZCTAs and their demand signals
  3. Transit access via Transitland v2 REST API (GTFS-based stop/route counts)

Invoked via:
  python3 main.py "Albuquerque" --mode zip_v2

Output:
  outputs/zip/{city_slug}/{city_slug}_zip_drill_v2.html

REQUIREMENTS:
  - Run scripts/download_zcta_shapefile.sh before first use
  - Set TRANSITLAND_API_KEY env var for transit data (gracefully skipped if absent)
  - Set CENSUS_API_KEY env var for Census ACS data (same requirement as v1)

CONSTRAINTS:
  - Does NOT modify any v1 logic in zip_drill.py
  - Does NOT change composite scoring weights or dimensions
  - Neighbor context is display-only; it does not affect ranking
  - Works for any city/state, not just Albuquerque/NM
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
from pathlib import Path
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    import geopandas as gpd
    from shapely.validation import make_valid
    _GEOPANDAS_AVAILABLE = True
except ImportError:
    _GEOPANDAS_AVAILABLE = False

# Import v1 data structures and pipeline steps unchanged
from pipeline.zip_drill import (
    CensusData,
    ZipInfo,
    ZipScore,
    aggregate_proficiency,
    discover_zips,
    fetch_census_acs,
    score_zips,
)

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).parent.parent
_SHAPEFILE_PATH = _REPO_ROOT / "data/raw/national/tl_2023_us_zcta520/tl_2023_us_zcta520.shp"
_ZCTA_COL = "ZCTA5CE20"                  # attribute column in TIGER 2023 ZCTA file
_TRANSIT_CACHE_DIR = "data/cache/zip/transit"
_TRANSITLAND_BASE = "https://transit.land/api/v2/rest"
_TRANSIT_RADIUS_METERS = 800             # ≈ 0.5 miles
_SHAPEFILE_BBOX_BUFFER = 0.25            # degrees; expanded region for neighbor search
_SVG_WIDTH = 820
_SVG_HEIGHT = 540
_SVG_PADDING = 32
_SVG_SIMPLIFY_TOLERANCE = 0.004          # degrees ≈ 400 m; reduces path complexity

_TIER_COLORS = {
    "high":     "#86efac",   # green-300 (score ≥ 7)
    "mid":      "#93c5fd",   # blue-300  (score 5–7)
    "low":      "#fde68a",   # amber-200 (score < 5)
    "excluded": "#e2e8f0",   # slate-200 (no Census data)
    "missing":  "#f1f5f9",   # slate-100 (not in score map)
}


# ── v2 data structures ────────────────────────────────────────────────────────

@dataclass
class TransitData:
    """Transitland stop and route counts within 0.5 miles of ZCTA centroid."""
    transit_stop_count: Optional[int]
    transit_route_count: Optional[int]


@dataclass
class NeighborContext:
    """Demand signal aggregates for topologically adjacent ZCTAs."""
    neighboring_zips: list[str] = field(default_factory=list)
    avg_school_age_pop: Optional[float] = None
    avg_poverty_rate_pct: Optional[float] = None
    avg_ell_pct: Optional[float] = None
    total_neighbor_charters: int = 0


@dataclass
class ZipScoreV2:
    """v1 ZipScore enriched with shapefile geometry, transit, and neighbor context."""
    base: ZipScore
    centroid_lat: Optional[float]         # WGS84 / NAD83 latitude of ZCTA centroid
    centroid_lon: Optional[float]         # WGS84 / NAD83 longitude of ZCTA centroid
    transit: TransitData
    neighbor_context: Optional[NeighborContext]


# ── Guard: geopandas availability ─────────────────────────────────────────────

def _require_geopandas() -> None:
    if not _GEOPANDAS_AVAILABLE:
        log.error(
            "geopandas and shapely are required for ZIP Drill v2 but are not installed. "
            "Run: pip install geopandas>=0.14.0 shapely>=2.0.0"
        )
        sys.exit(1)


# ── Capability 1: Shapefile loading ──────────────────────────────────────────

def load_zcta_shapefile(
    zip_codes: list[str],
) -> tuple["gpd.GeoDataFrame", "gpd.GeoDataFrame"]:
    """
    Load TIGER/Line 2023 ZCTA shapefile.

    Returns:
        city_gdf   — GeoDataFrame of city ZCTAs only
        region_gdf — GeoDataFrame of the surrounding region (city bbox + buffer),
                     used for topological neighbor detection

    Exits with an error message if the shapefile is not present.
    make_valid() applied defensively to all loaded geometries.
    """
    if not os.path.exists(_SHAPEFILE_PATH):
        log.error(
            "ZCTA shapefile not found at %s. "
            "Run scripts/download_zcta_shapefile.sh first.",
            _SHAPEFILE_PATH,
        )
        sys.exit(1)

    zip_set = set(zip_codes)

    # ── City ZCTAs: attribute filter (fast; avoids loading all 33 K rows) ─────
    zip_list_sql = ",".join(f"'{z}'" for z in zip_codes)
    try:
        city_gdf = gpd.read_file(
            _SHAPEFILE_PATH,
            where=f"{_ZCTA_COL} IN ({zip_list_sql})",
        ).copy()
    except Exception as exc:
        # Fallback: full load then Python-side filter (slower but guaranteed)
        log.warning(
            "zip_drill_v2: attribute-filtered shapefile load failed (%s); "
            "falling back to full load — may be slow.",
            exc,
        )
        full_gdf = gpd.read_file(_SHAPEFILE_PATH)
        city_gdf = full_gdf[full_gdf[_ZCTA_COL].isin(zip_set)].copy()

    if city_gdf.empty:
        log.error(
            "zip_drill_v2: no ZCTA geometries found for %s. "
            "Check that the ZIPs are valid ZCTAs (not PO Box or military-only).",
            zip_codes,
        )
        sys.exit(1)

    # Apply make_valid defensively before any spatial operations
    city_gdf["geometry"] = city_gdf["geometry"].apply(
        lambda g: make_valid(g) if g is not None else g
    )

    found = set(city_gdf[_ZCTA_COL].tolist())
    missing = zip_set - found
    if missing:
        log.warning(
            "zip_drill_v2: %d ZIP code(s) absent from shapefile "
            "(likely non-residential / PO Box): %s",
            len(missing),
            sorted(missing),
        )

    # ── Region GDF: bbox-filtered load for neighbor detection ─────────────────
    b = city_gdf.total_bounds          # (minx, miny, maxx, maxy) = (min_lon, min_lat, …)
    region_gdf = gpd.read_file(
        _SHAPEFILE_PATH,
        bbox=(
            b[0] - _SHAPEFILE_BBOX_BUFFER,
            b[1] - _SHAPEFILE_BBOX_BUFFER,
            b[2] + _SHAPEFILE_BBOX_BUFFER,
            b[3] + _SHAPEFILE_BBOX_BUFFER,
        ),
    ).copy()
    region_gdf["geometry"] = region_gdf["geometry"].apply(
        lambda g: make_valid(g) if g is not None else g
    )

    log.info(
        "zip_drill_v2: shapefile loaded — %d city ZCTAs, %d region ZCTAs (bbox buffer=%.2f°)",
        len(city_gdf),
        len(region_gdf),
        _SHAPEFILE_BBOX_BUFFER,
    )
    return city_gdf, region_gdf


# ── Capability 2: Topological neighbor detection ──────────────────────────────

def find_topological_neighbors(
    city_gdf: "gpd.GeoDataFrame",
    region_gdf: "gpd.GeoDataFrame",
) -> dict[str, list[str]]:
    """
    Identify ZCTAs that topologically adjoin each city ZCTA (shared boundary).

    Uses geopandas sjoin with predicate='touches'.
    TIGER/Line 2023 is topologically clean; shared edges reliably trigger 'touches'.

    Returns:
        {zip_code: [neighbor_zip_code, ...]}
    """
    left  = city_gdf [[_ZCTA_COL, "geometry"]].rename(columns={_ZCTA_COL: "city_zip"})
    right = region_gdf[[_ZCTA_COL, "geometry"]].rename(columns={_ZCTA_COL: "nbr_zip"})

    # Initialise result dict before attempting join (used in error fallback too)
    city_zips = left["city_zip"].tolist()
    neighbors: dict[str, list[str]] = {z: [] for z in city_zips}

    try:
        joined = gpd.sjoin(left, right, how="left", predicate="touches")
    except Exception as exc:
        log.warning(
            "zip_drill_v2: spatial join failed (%s). Neighbor context will be empty.",
            exc,
        )
        return neighbors

    seen: dict[str, set[str]] = {z: set() for z in city_zips}
    for _, row in joined.iterrows():
        city_zip = row["city_zip"]
        nbr_zip  = row.get("nbr_zip")
        if nbr_zip and nbr_zip != city_zip and nbr_zip not in seen.get(city_zip, set()):
            neighbors[city_zip].append(str(nbr_zip))
            seen[city_zip].add(str(nbr_zip))

    log.info(
        "zip_drill_v2: topological neighbors found — %s",
        {k: len(v) for k, v in neighbors.items()},
    )
    return neighbors


# ── Capability 3: Transitland transit data ────────────────────────────────────

def _transitland_api_key() -> Optional[str]:
    return os.environ.get("TRANSITLAND_API_KEY") or None


def _fetch_transitland_stops(
    zip_code: str,
    lat: float,
    lon: float,
    api_key: str,
) -> Optional[dict]:
    """Single Transitland v2 REST API call for stops near (lat, lon)."""
    params = {
        "lat":      f"{lat:.6f}",
        "lon":      f"{lon:.6f}",
        "radius":   str(_TRANSIT_RADIUS_METERS),
        "per_page": "500",
        "apikey":   api_key,
    }
    url = (
        _TRANSITLAND_BASE
        + "/stops?"
        + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CLIP/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        log.warning(
            "zip_drill_v2: Transitland request failed for %s — %s", zip_code, exc
        )
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning(
            "zip_drill_v2: Transitland JSON parse error for %s — %s", zip_code, exc
        )
        return None


def fetch_transit_data(
    centroids: dict[str, tuple[float, float]],
) -> dict[str, TransitData]:
    """
    Fetch Transitland GTFS stop and route counts for each ZCTA centroid.

    Caches each response to data/cache/zip/transit/{zip_code}.json.
    If TRANSITLAND_API_KEY is absent, returns TransitData(None, None) for all ZCTAs
    without failing the run.

    Args:
        centroids: {zip_code: (lat, lon)}

    Returns:
        {zip_code: TransitData}
    """
    api_key = _transitland_api_key()
    if not api_key:
        log.warning(
            "zip_drill_v2: TRANSITLAND_API_KEY not set — transit columns will show N/A. "
            "Set TRANSITLAND_API_KEY in .env for transit analysis."
        )
        return {z: TransitData(None, None) for z in centroids}

    os.makedirs(_TRANSIT_CACHE_DIR, exist_ok=True)
    results: dict[str, TransitData] = {}

    for zip_code, (lat, lon) in centroids.items():
        cache_path = os.path.join(_TRANSIT_CACHE_DIR, f"{zip_code}.json")

        # Serve from cache when available
        if os.path.exists(cache_path):
            try:
                with open(cache_path) as f:
                    cached = json.load(f)
                results[zip_code] = TransitData(
                    transit_stop_count=cached.get("stop_count"),
                    transit_route_count=cached.get("route_count"),
                )
                log.info("zip_drill_v2: transit cache hit — %s", zip_code)
                continue
            except Exception:
                pass   # stale / corrupt cache; fall through to re-fetch

        # Fetch from Transitland
        data = _fetch_transitland_stops(zip_code, lat, lon, api_key)
        if data is None:
            results[zip_code] = TransitData(None, None)
            continue

        stops = data.get("stops", [])
        stop_count = len(stops)

        # Collect unique route onestop_ids across all stops
        route_ids: set[str] = set()
        for stop in stops:
            for rs in stop.get("route_stops", []):
                route = rs.get("route") or {}
                oid = route.get("onestop_id")
                if oid:
                    route_ids.add(oid)
        route_count = len(route_ids)

        # Warn if results were paginated (unlikely at 0.5-mile radius)
        if (data.get("meta") or {}).get("next"):
            log.warning(
                "zip_drill_v2: %s transit results may be truncated "
                "(Transitland returned a next-page token).",
                zip_code,
            )

        # Write to cache
        with open(cache_path, "w") as f:
            json.dump(
                {
                    "zip_code":          zip_code,
                    "fetched_at":        datetime.date.today().isoformat(),
                    "lat":               lat,
                    "lon":               lon,
                    "radius_meters":     _TRANSIT_RADIUS_METERS,
                    "stop_count":        stop_count,
                    "route_count":       route_count,
                    "route_onestop_ids": sorted(route_ids),
                },
                f,
                indent=2,
            )

        results[zip_code] = TransitData(
            transit_stop_count=stop_count,
            transit_route_count=route_count,
        )
        log.info(
            "zip_drill_v2: %s — %d transit stops, %d routes",
            zip_code, stop_count, route_count,
        )

    return results


# ── Neighbor context builder ──────────────────────────────────────────────────

def build_neighbor_contexts(
    zip_codes: list[str],
    neighbors_dict: dict[str, list[str]],
    zip_infos_by_zip: dict[str, ZipInfo],
    combined_census: dict[str, CensusData],
) -> dict[str, NeighborContext]:
    """
    Aggregate demand signals for adjacent ZCTAs.

    Census data for neighbor-only ZCTAs (outside city discovery set) is pulled
    from combined_census, which merges city + neighbor-only ACS fetches.
    Charter counts are available only for ZCTAs in the city discovery set.

    Args:
        zip_codes:        city ZCTAs (the ones being scored)
        neighbors_dict:   {zip_code: [neighbor_zip, ...]}
        zip_infos_by_zip: {zip_code: ZipInfo} for city ZCTAs
        combined_census:  {zip_code: CensusData} for city + neighbor ZCTAs

    Returns:
        {zip_code: NeighborContext}
    """
    contexts: dict[str, NeighborContext] = {}

    for zip_code in zip_codes:
        nbr_zips = neighbors_dict.get(zip_code, [])
        if not nbr_zips:
            contexts[zip_code] = NeighborContext(neighboring_zips=[])
            continue

        school_age_pops: list[float] = []
        poverty_rates:   list[float] = []
        ell_pcts:        list[float] = []
        total_charters = 0

        for nbr in nbr_zips:
            cd = combined_census.get(nbr)
            if cd:
                if cd.school_age_pop is not None:
                    school_age_pops.append(float(cd.school_age_pop))
                if cd.poverty_rate is not None:
                    poverty_rates.append(cd.poverty_rate * 100.0)
                if cd.ell_pct is not None:
                    ell_pcts.append(cd.ell_pct * 100.0)
            # Charter count only available for city ZCTAs with NCES data
            nbr_info = zip_infos_by_zip.get(nbr)
            if nbr_info:
                total_charters += nbr_info.charter_count

        def _avg(lst: list[float]) -> Optional[float]:
            return round(sum(lst) / len(lst), 1) if lst else None

        contexts[zip_code] = NeighborContext(
            neighboring_zips=nbr_zips,
            avg_school_age_pop=_avg(school_age_pops),
            avg_poverty_rate_pct=_avg(poverty_rates),
            avg_ell_pct=_avg(ell_pcts),
            total_neighbor_charters=total_charters,
        )

    return contexts


# ── SVG map generation ────────────────────────────────────────────────────────

def _score_to_tier_key(score: float) -> str:
    if score >= 7.0:
        return "high"
    if score >= 5.0:
        return "mid"
    return "low"


def _ring_to_path_segment(coords: list[tuple], to_svg) -> str:
    """Convert a single coordinate ring to an SVG path segment (M…L…Z)."""
    if len(coords) < 2:
        return ""
    x0, y0 = to_svg(coords[0][0], coords[0][1])
    parts = [f"M {x0:.1f},{y0:.1f}"]
    for lon, lat in coords[1:]:
        x, y = to_svg(lon, lat)
        parts.append(f"L {x:.1f},{y:.1f}")
    parts.append("Z")
    return " ".join(parts)


def _geometry_to_svg_d(geom, to_svg) -> str:
    """Convert a shapely geometry to an SVG path `d` attribute string."""
    if geom is None or geom.is_empty:
        return ""

    def _poly(p) -> str:
        segs = [_ring_to_path_segment(list(p.exterior.coords), to_svg)]
        segs += [_ring_to_path_segment(list(i.coords), to_svg) for i in p.interiors]
        return " ".join(s for s in segs if s)

    t = geom.geom_type
    if t == "Polygon":
        return _poly(geom)
    if t == "MultiPolygon":
        return " ".join(_poly(p) for p in geom.geoms if not p.is_empty)
    # GeometryCollection or other — recurse on sub-geometries
    if hasattr(geom, "geoms"):
        parts = [_geometry_to_svg_d(g, to_svg) for g in geom.geoms]
        return " ".join(p for p in parts if p)
    return ""


def generate_svg_map(
    city_gdf: "gpd.GeoDataFrame",
    score_map: dict[str, ZipScoreV2],
) -> str:
    """
    Generate an inline SVG map of ZCTA polygons colored by composite score tier.
    Polygons are simplified to reduce path complexity.
    Returns the full <svg>…</svg> string.
    """
    if city_gdf.empty:
        return "<p><em>Map unavailable — no ZCTA geometries loaded.</em></p>"

    # Simplify geometries for SVG (~400 m tolerance at mid-latitudes)
    gdf = city_gdf.copy()
    gdf["geometry"] = gdf["geometry"].simplify(
        _SVG_SIMPLIFY_TOLERANCE, preserve_topology=True
    )

    b = gdf.total_bounds  # (minx, miny, maxx, maxy)
    lon_range = b[2] - b[0]
    lat_range = b[3] - b[1]
    if lon_range < 1e-9 or lat_range < 1e-9:
        return "<p><em>Map unavailable — degenerate bounding box.</em></p>"

    drawable_w = _SVG_WIDTH  - 2 * _SVG_PADDING
    drawable_h = _SVG_HEIGHT - 2 * _SVG_PADDING
    scale = min(drawable_w / lon_range, drawable_h / lat_range)

    # Centre the map within the canvas
    map_w = lon_range * scale
    map_h = lat_range * scale
    x_off = _SVG_PADDING + (drawable_w - map_w) / 2
    y_off = _SVG_PADDING + (drawable_h - map_h) / 2

    def to_svg(lon: float, lat: float) -> tuple[float, float]:
        x = (lon  - b[0]) * scale + x_off
        y = (b[3] - lat)  * scale + y_off   # flip Y: SVG ↓, latitude ↑
        return x, y

    path_elements: list[str] = []
    label_elements: list[str] = []

    for _, row in gdf.iterrows():
        zcta = row[_ZCTA_COL]
        geom = row["geometry"]
        if geom is None or geom.is_empty:
            continue

        v2 = score_map.get(zcta)
        if v2 is None:
            fill = _TIER_COLORS["missing"]
            score_label = "—"
        elif not v2.base.census_available:
            fill = _TIER_COLORS["excluded"]
            score_label = "excl."
        else:
            fill = _TIER_COLORS[_score_to_tier_key(v2.base.composite)]
            score_label = f"{v2.base.composite:.1f}"

        d = _geometry_to_svg_d(geom, to_svg)
        if not d:
            continue

        path_elements.append(
            f'<path d="{d}" fill="{fill}" stroke="#fff" stroke-width="1.2" opacity="0.92">'
            f"<title>{zcta} — Score: {score_label}</title></path>"
        )

        # Zip label at centroid
        c  = geom.centroid
        cx, cy = to_svg(c.x, c.y)
        label_elements.append(
            f'<text x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" '
            f'dominant-baseline="middle" font-size="9" fill="#1e293b" '
            f'font-family="sans-serif" pointer-events="none">{zcta}</text>'
        )

    # Legend — positioned below the map area
    legend_y   = _SVG_HEIGHT + 6
    legend_defs = [
        ("high",     "Score ≥ 7"),
        ("mid",      "Score 5–7"),
        ("low",      "Score < 5"),
        ("excluded", "No Census data"),
    ]
    legend_parts: list[str] = []
    lx = _SVG_PADDING
    for color_key, label in legend_defs:
        legend_parts.append(
            f'<rect x="{lx}" y="{legend_y}" width="12" height="12" '
            f'fill="{_TIER_COLORS[color_key]}" stroke="#94a3b8" stroke-width="0.5" rx="2"/>'
            f'<text x="{lx + 16}" y="{legend_y + 9}" font-size="9" fill="#475569" '
            f'font-family="sans-serif">{label}</text>'
        )
        lx += 100

    total_h = _SVG_HEIGHT + 26
    all_elements = "\n  ".join(path_elements + label_elements + legend_parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_SVG_WIDTH} {total_h}" '
        f'width="{_SVG_WIDTH}" height="{total_h}" '
        f'style="display:block;max-width:100%;">\n  '
        f"{all_elements}\n</svg>"
    )


# ── Assemble v2 score objects ─────────────────────────────────────────────────

def _build_v2_score(
    s: ZipScore,
    centroids: dict[str, tuple[float, float]],
    transit_data: dict[str, TransitData],
    neighbor_contexts: dict[str, NeighborContext],
) -> ZipScoreV2:
    centroid = centroids.get(s.zip_code)
    return ZipScoreV2(
        base=s,
        centroid_lat=centroid[0] if centroid else None,
        centroid_lon=centroid[1] if centroid else None,
        transit=transit_data.get(s.zip_code, TransitData(None, None)),
        neighbor_context=neighbor_contexts.get(s.zip_code),
    )


# ── Renderer ─────────────────────────────────────────────────────────────────

def render_html_v2(
    ranked:   list[ZipScoreV2],
    excluded: list[ZipScoreV2],
    city_name: str,
    state: str,
    svg_map: str,
) -> str:
    """Render ZIP Drill v2 HTML via Jinja2. Returns the output file path."""
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape([]),
    )

    template_name = "zip_drill_v2.html.j2"
    if not os.path.exists(os.path.join("templates", template_name)):
        raise FileNotFoundError(
            f"Template not found: templates/{template_name}. "
            "Ensure the v2 template is part of the distribution."
        )

    city_slug = re.sub(r"[^a-z0-9]+", "-", city_name.lower()).strip("-")
    out_dir   = f"outputs/zip/{city_slug}"
    os.makedirs(out_dir, exist_ok=True)
    out_path  = f"{out_dir}/{city_slug}_zip_drill_v2.html"

    rendered = env.get_template(template_name).render(
        ranked=ranked,
        excluded=excluded,
        city_name=city_name,
        state=state,
        svg_map=svg_map,
        generated_at=datetime.date.today().isoformat(),
        zip_count=len(ranked),
    )

    with open(out_path, "w") as f:
        f.write(rendered)

    return out_path


# ── Public entry point ────────────────────────────────────────────────────────

def run_v2(city_name: str, state: str = "NM") -> str:
    """
    Full ZIP Drill v2 pipeline for a single city.
    Returns the output HTML path.
    """
    _require_geopandas()
    log.info("zip_drill_v2: starting for %s, %s", city_name, state)

    # ── Layer 1: v1 scoring (unchanged) ───────────────────────────────────────
    with open("config/scoring_weights.yaml") as f:
        cfg = yaml.safe_load(f)
    weights = cfg["zip_preset"]

    zip_infos    = discover_zips(city_name, state)
    zip_codes    = [zi.zip_code for zi in zip_infos]
    zip_by_zip   = {zi.zip_code: zi for zi in zip_infos}

    log.info("zip_drill_v2: %d zip codes — %s", len(zip_codes), zip_codes)

    census      = fetch_census_acs(zip_codes)
    proficiency = aggregate_proficiency(zip_codes, state, city_name)
    all_scores  = score_zips(zip_infos, census, proficiency, weights)

    ranked_v1   = [s for s in all_scores if     s.census_available]
    excluded_v1 = [s for s in all_scores if not s.census_available]
    for i, s in enumerate(ranked_v1, 1):
        s.rank = i

    if excluded_v1:
        log.info(
            "zip_drill_v2: %d zip(s) excluded from ranking (no Census pop): %s",
            len(excluded_v1), [s.zip_code for s in excluded_v1],
        )

    # ── Layer 2: shapefile ────────────────────────────────────────────────────
    city_gdf, region_gdf = load_zcta_shapefile(zip_codes)

    # Build centroid dict — (lat, lon) from ZCTA centroid
    # TIGER uses NAD83 geographic coords; difference vs WGS84 is negligible
    # for 0.5-mile transit radius queries
    centroids: dict[str, tuple[float, float]] = {}
    for _, row in city_gdf.iterrows():
        zcta = row[_ZCTA_COL]
        geom = row["geometry"]
        if geom is not None and not geom.is_empty:
            c = geom.centroid
            centroids[zcta] = (c.y, c.x)   # (lat, lon)

    # ── Layer 3: topological neighbors ───────────────────────────────────────
    neighbors_dict = find_topological_neighbors(city_gdf, region_gdf)

    # Collect ZCTAs that are neighbors but outside the city discovery set
    all_nbr_zips    = {z for nbrs in neighbors_dict.values() for z in nbrs}
    neighbor_only   = list(all_nbr_zips - set(zip_codes))

    # Fetch Census for neighbor-only ZCTAs (display context only, not scored)
    neighbor_census = fetch_census_acs(neighbor_only) if neighbor_only else {}
    combined_census = {**census, **neighbor_census}

    neighbor_contexts = build_neighbor_contexts(
        zip_codes, neighbors_dict, zip_by_zip, combined_census
    )

    # ── Layer 4: transit ──────────────────────────────────────────────────────
    transit_data = fetch_transit_data(centroids)

    # ── Assemble v2 score objects ─────────────────────────────────────────────
    ranked_v2 = [
        _build_v2_score(s, centroids, transit_data, neighbor_contexts)
        for s in ranked_v1
    ]
    excluded_v2 = [
        _build_v2_score(s, centroids, transit_data, neighbor_contexts)
        for s in excluded_v1
    ]

    # ── SVG map ───────────────────────────────────────────────────────────────
    score_map = {s.base.zip_code: s for s in ranked_v2 + excluded_v2}
    svg_map   = generate_svg_map(city_gdf, score_map)

    # ── Render ────────────────────────────────────────────────────────────────
    out_path = render_html_v2(ranked_v2, excluded_v2, city_name, state, svg_map)

    log.info("zip_drill_v2: output written to %s", out_path)
    return out_path
