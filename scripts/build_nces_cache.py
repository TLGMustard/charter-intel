#!/usr/bin/env python3
"""
Pre-filter national NCES membership parquet to a single state and save as parquet.

Usage:
    python3 scripts/build_nces_cache.py NM

Reads data/raw/national/nces_lea_membership.parquet (built by build_national_parquet.py),
filters to the requested state, and writes data/processed/{state}/nces_membership_{state}.parquet.
"""
from __future__ import annotations

import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd

NATIONAL_MEMBERSHIP_PQ = "data/raw/national/nces_lea_membership.parquet"


def build_nces_cache(state: str) -> tuple[str, int, int]:
    """
    Filter national membership parquet to state, write per-state parquet.

    Returns (out_path, row_count, elapsed_seconds).
    Prints to stderr and calls sys.exit(1) if the national parquet is missing.
    """
    state_upper = state.upper()
    state_lower = state.lower()
    t0 = time.time()

    if not os.path.exists(NATIONAL_MEMBERSHIP_PQ):
        print(
            f"ERROR: National membership parquet not found: {NATIONAL_MEMBERSHIP_PQ}",
            file=sys.stderr,
        )
        print("Run: python scripts/build_national_parquet.py", file=sys.stderr)
        sys.exit(1)

    df = pd.read_parquet(NATIONAL_MEMBERSHIP_PQ)
    filtered = df[df["STABBR"].str.strip() == state_upper].copy()

    out_dir = f"data/processed/{state_lower}"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/nces_membership_{state_lower}.parquet"
    filtered.to_parquet(out_path, index=False)

    elapsed = round(time.time() - t0)
    return out_path, len(filtered), elapsed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/build_nces_cache.py <STATE>")
        print("Example: python3 scripts/build_nces_cache.py NM")
        sys.exit(1)

    out_path, row_count, elapsed = build_nces_cache(sys.argv[1])

    print(f"State: {sys.argv[1].upper()}")
    print(f"Rows written: {row_count:,}")
    print(f"Output: {out_path}")
    print(f"Time: {elapsed}s")
