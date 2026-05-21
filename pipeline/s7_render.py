"""
pipeline/s7_render.py
Stage 7: Output Rendering

Renders the structured brief JSON into human-readable markdown (or PDF).
NO LLM CALLS. Pure Jinja2 template rendering from structured data.

INPUT:  data/cache/synthesis/{state}/{community_id}/s6_brief_{preset}_mode{mode}.json
OUTPUT: outputs/by_community/{community_id}/{community_id}_{preset}_mode{mode}_{date}.md
"""
from __future__ import annotations
import json
import os
import time
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pipeline import PipelineConfig, StageResult, StageStatus, today_str

STAGE_ID = "s7_render"

MODE_TEMPLATES = {
    1: "snapshot.md.j2",
    2: "strategic_brief.md.j2",
    3: "deep_dive.md.j2",
}


def run(
    community_id: str,
    state: str,
    config: PipelineConfig,
    previous_result: Optional[StageResult] = None,
    **kwargs
) -> StageResult:
    start = time.time()

    # Load brief from S6
    if previous_result and previous_result.output_data:
        brief = previous_result.output_data
    else:
        brief_path = (
            f"data/cache/synthesis/{state.lower()}/{community_id}/"
            f"s6_brief_{config.preset.value}_mode{config.mode.value}.json"
        )
        if not os.path.exists(brief_path):
            return StageResult(
                stage_id=STAGE_ID, community_id=community_id, state=state,
                status=StageStatus.ERROR,
                errors=[f"Brief not found at {brief_path}. Run S6 first."]
            )
        with open(brief_path) as f:
            brief = json.load(f)

    # Load template
    template_name = MODE_TEMPLATES.get(config.mode.value, "strategic_brief.md.j2")
    template_path = os.path.join("templates", template_name)

    if not os.path.exists(template_path):
        # Fallback: render directly from brief JSON without template
        rendered = _render_fallback(brief)
        warnings = [
            f"Template {template_path} not found. Used fallback renderer. "
            f"Create templates/{template_name} for formatted output."
        ]
    else:
        env = Environment(
            loader=FileSystemLoader("templates"),
            autoescape=select_autoescape([])
        )
        template = env.get_template(template_name)
        rendered = template.render(brief=brief)
        warnings = []

    # Write output
    out_dir = f"outputs/by_community/{community_id}"
    os.makedirs(out_dir, exist_ok=True)
    filename = f"{community_id}_{config.preset.value}_mode{config.mode.value}_{today_str()}.md"
    out_path = os.path.join(out_dir, filename)

    with open(out_path, "w") as f:
        f.write(rendered)

    return StageResult(
        stage_id=STAGE_ID, community_id=community_id, state=state,
        status=StageStatus.SUCCESS, output_path=out_path,
        warnings=warnings, duration_seconds=round(time.time() - start, 2)
    )


def _render_fallback(brief: dict) -> str:
    """
    Minimal fallback renderer when no Jinja template exists.
    Produces readable markdown from brief JSON.
    """
    lines = [
        f"# {brief.get('community_name', brief.get('community_id'))} — "
        f"{brief.get('mode_label', 'Strategic Brief')}",
        f"**Classification:** {brief.get('classification', '—')}  "
        f"**Score:** {brief.get('composite_score', '—')}/10  "
        f"**Confidence:** {brief.get('confidence_overall', '—')}",
        f"*Data through {brief.get('data_through', '—')} · "
        f"Generated {brief.get('generated_at', '—')[:10]}*",
        "",
        "## Executive Snapshot",
        brief.get("executive_snapshot", "_Not available_"),
        "",
    ]

    # Scorecard
    scorecard = brief.get("scorecard_summary", {})
    if scorecard:
        lines += [
            "## Scorecard",
            f"**Composite:** {scorecard.get('composite_score', '—')}/10  "
            f"**Tier:** {scorecard.get('tier_display_label', '—')}",
            "",
            "| Dimension | Score | Weight | Confidence | Driver |",
            "|---|---|---|---|---|",
        ]
        for row in scorecard.get("dimension_table", []):
            lines.append(
                f"| {row.get('display_name', row.get('dimension'))} "
                f"| {row.get('score', '—')} "
                f"| {int(row.get('weight', 0) * 100)}% "
                f"| {row.get('confidence', '—')} "
                f"| {row.get('driver', '—')} |"
            )
        # Override flags
        for flag in scorecard.get("override_flags", []):
            lines.append(
                f"\n- {flag.get('visual', '⚠️')} **{flag.get('flag')}** — "
                f"{flag.get('triggered_by')}"
            )
        lines.append("")

    # Recommendations
    recs = brief.get("recommendations", [])
    if recs:
        lines += ["## Recommendations", ""]
        for i, rec in enumerate(recs, 1):
            lines += [
                f"**{i}. {rec.get('action', '—')}**",
                rec.get("rationale", ""),
                f"*Evidence:* {rec.get('evidence_summary', '—')}  "
                f"*Risk:* {rec.get('primary_risk', '—')}  "
                f"*Confidence:* {rec.get('confidence', '—')}",
                "",
            ]

    # Needs Verification
    nv = brief.get("needs_verification", [])
    if nv:
        lines += ["## Needs Verification", ""]
        for item in nv:
            lines.append(
                f"- **{item.get('claim', '—')}** — {item.get('reason', '—')} "
                f"*(Impact: {item.get('impact_if_wrong', '—')})*"
            )
        lines.append("")

    # Sources
    sources = brief.get("sources", [])
    if sources:
        lines += ["## Sources", ""]
        for s in sources:
            url_part = f" · {s['url']}" if s.get("url") else ""
            lines.append(
                f"[{s['ref_num']}] {s.get('title', '—')} · "
                f"{s.get('source_class', '—')}{url_part}"
            )
        lines.append("")

    # Disclosure
    disclosure = brief.get("disclosure", "")
    if disclosure:
        lines += ["---", f"*{disclosure}*"]

    # Audit warning
    if brief.get("audit_passed") is False:
        flags = brief.get("audit_flags", [])
        lines += [
            "",
            f"> ⚠️ **Audit flag:** {len(flags)} claim(s) were stripped or "
            f"moved to Needs Verification by the hallucination audit. "
            f"Review before external use."
        ]

    return "\n".join(lines)
