#!/usr/bin/env python3
"""
Pre-filter national NCES membership CSVs to a single state and save as parquet.

Usage:
    python3 scripts/build_nces_cache.py NM

Source file paths are imported from population_trends_fetcher — defined in one
place. Adding a new year's file requires only updating NCES_SOURCE_FILES there.
"""
from __future__ import annotations

import os
import sys
import time

# Allow imports from the project root regardless of where this script is invoked from.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
from pipeline.utils.population_trends_fetcher import NCES_SOURCE_FILES

# NCES national files may label state with any of these column names.
_STATE_COL_CANDIDATES = ("STABR", "ST", "STATEABB", "STATE_ABBR")


def build_nces_cache(state: str) -> tuple[str, int, int]:
    """
    Read NCES membership CSVs, filter to state, write parquet.

    Returns (out_path, row_count, elapsed_seconds).
    Prints to stderr and calls sys.exit(1) if source files are missing.
    """
    state_upper = state.upper()
    state_lower = state.lower()
    t0 = time.time()

    missing = [p for _, p in NCES_SOURCE_FILES if not os.path.exists(p)]
    if missing:
        print("ERROR: NCES source files not found:", file=sys.stderr)
        for p in missing:
            print(f"  {p}", file=sys.stderr)
        print(
            "\nDownload the files from https://nces.ed.gov/ccd/files.asp and place them "
            "at the paths listed above.",
            file=sys.stderr,
        )
        sys.exit(1)

    frames: list[pd.DataFrame] = []
    state_col: str | None = None

    for year, path in NCES_SOURCE_FILES:
        df = pd.read_csv(path, encoding="latin-1", dtype=str, low_memory=False)
        df["_year"] = str(year)

        # Detect state column from the first file; assume all files use the same column.
        if state_col is None:
            for candidate in _STATE_COL_CANDIDATES:
                if candidate in df.columns:
                    state_col = candidate
                    break
            if state_col is None:
                print(
                    f"ERROR: No state column found in {path}.\n"
                    f"Expected one of: {_STATE_COL_CANDIDATES}\n"
                    f"First 15 columns: {list(df.columns[:15])}",
                    file=sys.stderr,
                )
                sys.exit(1)

        filtered = df[df[state_col].str.strip() == state_upper].copy()
        frames.append(filtered)

    combined = pd.concat(frames, ignore_index=True)

    out_dir = f"data/processed/{state_lower}"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/nces_membership_{state_lower}.parquet"
    combined.to_parquet(out_path, index=False)

    elapsed = round(time.time() - t0)
    return out_path, len(combined), elapsed


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
