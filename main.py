"""
main.py
Charter Community Intelligence Platform — Pipeline Entry Point

USAGE:
  python main.py --state NM --community nm-albuquerque
  python main.py --state NM --all --preset growth --mode 2
  python main.py --state NM --community nm-riverdale --preset turnaround --mode 3
  python main.py --state NM --all --dry-run

FLAGS:
  --state         Two-letter state code (required)
  --community     Specific community_id to run (omit for --all)
  --all           Run all communities in the state
  --preset        growth | replication | turnaround (default: growth)
  --mode          1 | 2 | 3 (default: 2)
  --force-refresh Ignore cache; regenerate all stages
  --no-cache      Disable cache reads AND writes
  --dry-run       Validate config and inputs without making API calls
  --stages        Comma-separated list of stages to run (default: all)
                  e.g., --stages s5,s6,s7 to re-run only scoring and later

ENVIRONMENT:
  ANTHROPIC_API_KEY  — required for stages that call Claude
"""

import argparse
import json
import logging
import os
import sys
import time

from pipeline import (
    OperatorPreset, OutputMode, PipelineConfig,
    StageResult, StageStatus, STAGE_ORDER
)
from pipeline import s1_discovery, s2_state_context, s3_fact_extraction
from pipeline import s4_verification, s5_scoring, s6_synthesis, s7_render

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

STAGE_MODULES = {
    "s1_discovery":     s1_discovery,
    "s2_state_context": s2_state_context,
    "s3_fact_extraction": s3_fact_extraction,
    "s4_verification":  s4_verification,
    "s5_scoring":       s5_scoring,
    "s6_synthesis":     s6_synthesis,
    "s7_render":        s7_render,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Charter Community Intelligence Platform"
    )
    parser.add_argument("--state", required=True, help="Two-letter state code")
    parser.add_argument("--community", help="Specific community_id")
    parser.add_argument("--all", action="store_true", dest="run_all",
                        help="Run all communities in state")
    parser.add_argument("--preset", default="growth",
                        choices=["growth", "replication", "turnaround"])
    parser.add_argument("--mode", type=int, default=2, choices=[1, 2, 3])
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stages", help="Comma-separated stages to run")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> PipelineConfig:
    communities = None
    if args.community:
        communities = [args.community]

    return PipelineConfig(
        state=args.state.upper(),
        preset=OperatorPreset(args.preset),
        mode=OutputMode(args.mode),
        output_format="markdown",
        cache_enabled=not args.no_cache,
        dry_run=args.dry_run,
        force_refresh=args.force_refresh,
        communities=communities
    )


def run_community_pipeline(
    community_id: str,
    state: str,
    config: PipelineConfig,
    stages_to_run: list[str]
) -> dict[str, StageResult]:
    """Run the full pipeline for one community. Returns stage_id → StageResult."""
    results = {}
    previous = None

    for stage_id in stages_to_run:
        module = STAGE_MODULES.get(stage_id)
        if not module:
            logger.warning(f"Unknown stage '{stage_id}' — skipping")
            continue

        logger.info(f"[{community_id}] Running {stage_id}...")
        start = time.time()

        try:
            result = module.run(
                community_id=community_id,
                state=state,
                config=config,
                previous_result=previous
            )
        except Exception as e:
            result = StageResult(
                stage_id=stage_id,
                community_id=community_id,
                state=state,
                status=StageStatus.ERROR,
                errors=[f"Unhandled exception: {str(e)}"]
            )
            logger.exception(f"[{community_id}] {stage_id} raised exception")

        elapsed = round(time.time() - start, 2)
        results[stage_id] = result

        if result.warnings:
            for w in result.warnings:
                logger.warning(f"[{community_id}] [{stage_id}] {w}")

        if result.status == StageStatus.ERROR:
            logger.error(
                f"[{community_id}] {stage_id} FAILED: {result.errors}. "
                f"Halting pipeline for this community."
            )
            break
        elif result.cache_hit:
            logger.info(f"[{community_id}] {stage_id} — cache hit ({elapsed}s)")
        else:
            logger.info(
                f"[{community_id}] {stage_id} — OK "
                f"({elapsed}s, {result.tokens_used} tokens)"
            )

        previous = result

    return results


def main():
    args = parse_args()
    config = build_config(args)

    if not os.getenv("ANTHROPIC_API_KEY") and not config.dry_run:
        logger.error(
            "ANTHROPIC_API_KEY not set. "
            "Export it or run with --dry-run."
        )
        sys.exit(1)

    # Determine which stages to run
    if args.stages:
        stages_to_run = [s.strip() for s in args.stages.split(",")]
        invalid = [s for s in stages_to_run if s not in STAGE_MODULES]
        if invalid:
            logger.error(f"Unknown stages: {invalid}")
            sys.exit(1)
    else:
        stages_to_run = STAGE_ORDER

    # Run S1 to get community list if --all
    if args.run_all:
        s1_result = s1_discovery.run(
            community_id="ALL",
            state=config.state,
            config=config
        )
        if not s1_result.ok:
            logger.error(f"S1 discovery failed: {s1_result.errors}")
            sys.exit(1)
        communities = [
            c["community_id"]
            for c in s1_result.output_data.get("communities", [])
        ]
    elif config.communities:
        communities = config.communities
    else:
        logger.error("Specify --community or --all")
        sys.exit(1)

    logger.info(
        f"Running pipeline for {len(communities)} communities in {config.state} "
        f"| preset={config.preset.value} | mode={config.mode.value} "
        f"| stages={stages_to_run}"
    )

    # Run pipeline per community
    all_results = {}
    for community_id in communities:
        all_results[community_id] = run_community_pipeline(
            community_id=community_id,
            state=config.state,
            config=config,
            stages_to_run=stages_to_run
        )

    # Summary
    successes = sum(
        1 for cr in all_results.values()
        if all(r.ok for r in cr.values())
    )
    failures = len(all_results) - successes

    logger.info(
        f"\n{'='*60}\n"
        f"PIPELINE COMPLETE\n"
        f"  Communities: {len(all_results)} total | {successes} succeeded | {failures} failed\n"
        f"{'='*60}"
    )

    if failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
