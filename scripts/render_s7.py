#!/usr/bin/env python3
"""
scripts/render_s7.py
Standalone re-render of strategic_brief.html.j2 from a cached S6 brief JSON.

Usage (run from repo root):
  python3 scripts/render_s7.py [community_id] [preset]

  community_id — e.g. nm-albuquerque (default: nm-albuquerque)
  preset       — e.g. growth, maturity_adjusted (default: growth)

The template uses brief.X attribute access throughout. Pass the full S6 JSON
as brief=data; do NOT unpack with **data or pass individual flat variables.
"""
import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "templates"

# ---- CONFIG ----
community_id = sys.argv[1] if len(sys.argv) > 1 else "nm-albuquerque"
preset       = sys.argv[2] if len(sys.argv) > 2 else "growth"

state = community_id.split("-")[0]  # e.g. "nm"

S6_JSON_PATH = (
    REPO_ROOT / "data" / "cache" / "synthesis" / state / community_id
    / f"s6_brief_{preset}_mode2.json"
)

OUTPUT_DIR   = REPO_ROOT / "outputs" / "by_community" / community_id
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
HTML_OUTPUT  = OUTPUT_DIR / f"{community_id}_{preset}_mode2.html"

# ---- LOAD S6 BRIEF ----
if not S6_JSON_PATH.exists():
    print(f"[ERROR] S6 brief not found: {S6_JSON_PATH}")
    print(f"  Run the pipeline first: python3 main.py '{community_id}' --preset {preset}")
    sys.exit(1)

with open(S6_JSON_PATH) as f:
    brief = json.load(f)

# ---- POST-PROCESSING: FIX 1, 3 ----
def post_process_brief(brief):
    """Apply render-layer fixes for confidence communication."""

    if "scorecard_summary" not in brief or "dimension_table" not in brief["scorecard_summary"]:
        return brief

    dim_table = brief["scorecard_summary"]["dimension_table"]

    # FIX 1: Academic Need language — replace demand language with educational need language
    for row in dim_table:
        if row.get("dimension") == "academic_need":
            driver = row.get("driver", "")
            if "demand for alternative" in driver.lower():
                row["driver"] = driver.replace(
                    "demand for alternative school models",
                    "documented educational need; parent demand requires separate verification"
                )

    # FIX 3: Authorizer Friendliness — detect state-level signals only when local data absent
    local_auths = brief.get("local_authorizers", [])
    has_local_auth_data = len(local_auths) > 0

    for row in dim_table:
        if row.get("dimension") == "authorizer_friendliness":
            score = row.get("score", 0)
            if not has_local_auth_data and score > 6.0:
                # Append sub-label to display_name
                display_name = row.get("display_name", "Authorizer Friendliness")
                if "(state-level signals only" not in display_name:
                    row["display_name"] = f"{display_name} (state-level signals only — local data absent)"

    # FIX 3b: Add needs_verification entry for Authorizer Friendliness
    for row in dim_table:
        if row.get("dimension") == "authorizer_friendliness":
            score = row.get("score", 0)
            if not has_local_auth_data and score > 6.0:
                if "needs_verification" not in brief:
                    brief["needs_verification"] = []

                # Check if entry already exists
                nv_exists = any(
                    "Authorizer Friendliness score derived from state-level" in item.get("claim", "")
                    for item in brief["needs_verification"]
                )

                if not nv_exists:
                    # Insert at top of list
                    brief["needs_verification"].insert(0, {
                        "claim": "Authorizer Friendliness score derived from state-level signals only; local approval, renewal, and closure rates unverified.",
                        "reason": None,
                        "impact_if_wrong": "HIGH",
                    })

    # FIX 2: Check for demand-signal absence condition for Executive Snapshot note
    # If Competitive Opportunity is defaulted (score == 5.0) AND Charter Saturation < 4.0
    co_score = None
    co_default = False
    cs_score = None

    for row in dim_table:
        if row.get("dimension") == "competitive_opportunity":
            co_score = row.get("score")
            co_default = row.get("used_default", False)
        elif row.get("dimension") == "charter_saturation":
            cs_score = row.get("score")

    if co_score == 5.0 and co_default and cs_score is not None and cs_score < 4.0:
        if brief.get("executive_snapshot"):
            snap = brief["executive_snapshot"]
            if "demand signal is absent" not in snap:
                brief["executive_snapshot"] = snap + " Note: demand signal is absent; this score reflects educational need, not verified market demand."

    return brief

brief = post_process_brief(brief)

# ---- RENDER ----
# The template uses brief.X throughout (e.g. brief.community_name, brief.state).
# Pass the full S6 dict as brief= so all expressions resolve correctly.
env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=False)

debug = {
    "run_id":     "manual-render",
    "timestamp":  "",
    "depth":      "standard",
    "token_rows": [],
    "warn_lines": [],
}

rendered = env.get_template("strategic_brief.html.j2").render(brief=brief, debug=debug)
HTML_OUTPUT.write_text(rendered, encoding="utf-8")
print(f"[OK] HTML written to {HTML_OUTPUT}")
