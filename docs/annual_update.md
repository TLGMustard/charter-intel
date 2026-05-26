# CLIP Annual Data Update Guide

**Who this is for:** whoever maintains this pipeline after initial build.
**Estimated time:** 30 minutes per annual cycle.
**Last verified against codebase:** 2026-05-26

---

## Overview

CLIP draws from two external data sources that must be refreshed annually:

1. **NCES CCD** (National Center for Education Statistics, Common Core of Data)
   Released: October–December each year
   Download page: https://nces.ed.gov/ccd/files.asp

2. **NM PED** (New Mexico Public Education Department)
   Released: each summer
   Download page: NM PED Google Sheet (same source as original files)

Both sources require downloading new files, replacing old ones on disk,
updating filename constants in two utility files, and recomputing one
hardcoded constant. Then run the spot-check validator before re-running
any city briefs.

---

## Part 1 — NCES CCD Files

### 1a. Which files to download

Download the **district-level (LEA)** variants only. Do not use school-level
files for the pipeline — the pipeline aggregates from the school-level lunch
file itself, but all other data comes from LEA-level files.

| File type | Filename pattern | Used by pipeline at runtime |
|---|---|---|
| LEA Directory | `nces_lea_directory_YYYY.csv` | No — reference only (see note below) |
| LEA Membership | `nces_lea_membership_YYYY.csv` | No — reference only (see note below) |
| LEA Finance | `nces_lea_finance_YYYY.csv` | **Yes** — `nces_fetcher.py` reads this |
| School Lunch | `nces_sch_lunch_YYYY.csv` | **Yes** — `nces_fetcher.py` reads this |

**Note on Directory and Membership files:** These are not read by any pipeline
code at runtime. They were used during initial setup to build the
`nces_district_map` in `config/states.yaml` (the community_id → LEAID mapping).
Download and keep them for reference. If new NM communities are added to the
pipeline, you will need the Directory file to look up their LEAID.

### 1b. Where to put them

```
data/raw/nm/
```

Replace the old files. Filename must match exactly what you set in
`nces_fetcher.py` (see step 1c).

### 1c. Update filename constants in nces_fetcher.py

Open `pipeline/utils/nces_fetcher.py`. At the top of the file, update
these two constants (lines 33–34):

```python
FINANCE_CSV = "data/raw/nm/nces_lea_finance_2024.csv"   # ← update year
LUNCH_CSV   = "data/raw/nm/nces_sch_lunch_2024.csv"     # ← update year
```

Change `2024` to the new file year (e.g., `2025` for the SY2025-26 release).
No other filename changes are needed in this file.

### 1d. Recompute NM state average per-pupil revenue

The NM state average PPR is hardcoded at line 43 of `nces_fetcher.py`:

```python
NM_STATE_AVG_PPR = 24_356.0
```

This value was computed from 143 valid NM LEA rows in the FY2023 finance file
(`TOTALREV / MEMBERSCH`, excluding rows where either field is -2 or ≤ 0).
It **must be recomputed** each year from the new finance file — it is used to
calculate `per_pupil_revenue_vs_state_avg_pct` for every community.

To recompute it, open the new finance CSV in any spreadsheet tool or run a
quick Python snippet:

```python
import csv

total, count = 0.0, 0
with open("data/raw/nm/nces_lea_finance_YYYY.csv", newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        if row.get("STNAME", "").strip().upper() != "NEW MEXICO":
            continue
        try:
            rev  = int(row["TOTALREV"])
            mem  = int(row["MEMBERSCH"])
        except (ValueError, KeyError):
            continue
        if rev <= 0 or mem <= 0 or rev == -2 or mem == -2:
            continue
        total += rev / mem
        count += 1

print(f"NM state avg PPR: ${total/count:,.0f}  ({count} valid rows)")
```

Update `NM_STATE_AVG_PPR` on line 43 with the result.

### 1e. Sentinel value reminder

NCES uses **-2** to mean "missing or not applicable" for numeric fields.
`nces_fetcher.py` already filters these out before any arithmetic. If you
add new columns in the future, always check for this sentinel before dividing.

### 1f. Columns the pipeline reads — verify these still exist

If the pipeline suddenly returns `None` for finance data after an update,
the most likely cause is that NCES renamed a column. Check that the new
finance file still contains these columns:

**Finance file (`nces_lea_finance_YYYY.csv`):**
`LEAID`, `MEMBERSCH`, `TOTALREV`, `TFEDREV`, `TSTREV`, `TLOCREV`, `TOTALEXP`

**Lunch file (`nces_sch_lunch_YYYY.csv`):**
`LEAID`, `DATA_GROUP`, `LUNCH_PROGRAM`, `TOTAL_INDICATOR`, `DMS_FLAG`, `STUDENT_COUNT`

These column names have been stable across recent NCES releases, but NCES
does occasionally rename columns between major release cycles.

---

## Part 2 — NM PED Files

### 2a. Which files to replace

| File | Filename on disk | Notes |
|---|---|---|
| Charter roster | `charter_roster.csv` | No year suffix — replace in place |
| ELA proficiency | `proficiency_ela_YYYY_YY.csv` | Year suffix in filename |
| Math proficiency | `proficiency_math_YYYY_YY.csv` | Year suffix in filename |

### 2b. Where to put them

```
data/raw/nm/
```

### 2c. Update filename constants in ped_fetcher.py

Open `pipeline/utils/ped_fetcher.py`. Update these two constants
(lines 19–20):

```python
ELA_CSV  = "data/raw/nm/proficiency_ela_2024_25.csv"   # ← update year
MATH_CSV = "data/raw/nm/proficiency_math_2024_25.csv"  # ← update year
```

Change both to match the new file's name exactly (e.g., `proficiency_ela_2025_26.csv`).

**Charter roster:** `charter_roster.csv` has no year suffix in the code
(`pipeline/s1_discovery.py` always reads `data/raw/{state}/charter_roster.csv`).
Just replace the file on disk — no code change needed.

### 2d. Columns the pipeline reads — verify these still exist

**Proficiency files (`proficiency_ela_YYYY_YY.csv`, `proficiency_math_YYYY_YY.csv`):**

The pipeline searches for the first line containing `TableName` as the header
row (handles PED's habit of prepending a metadata line). It then filters on:

`TableName`, `Demographic` (must equal `"All"`),
`LocationCode` (must equal `"0"`), `DistrictName`, `AttenuatedProficiencyRate`

If PED renames any of these columns, `ped_fetcher.py` will return `None`
silently and proficiency dimensions will default to 5.

---

## Part 3 — Verification Steps After Any File Update

Run these checks before re-running city briefs. Do not skip them —
silent column-rename failures have no error message.

### 3a. Spot-check known districts

Run the following and confirm the values fall in the expected ranges:

```python
import sys
sys.path.insert(0, ".")
from pipeline.utils.nces_fetcher import get_district_data as nces
from pipeline.utils.ped_fetcher  import get_district_data as ped

for cid in ["nm-albuquerque", "nm-santa-fe", "nm-espanola"]:
    n = nces(cid, "NM")
    p = ped(cid, "NM")
    print(f"\n{cid}")
    print(f"  FRL:  {n.get('frl_pct') if n else None}")
    print(f"  PPR:  {n.get('per_pupil_expenditure') if n else None}")
    print(f"  ELA:  {p.get('ela_proficiency_pct') if p else None}")
    print(f"  MATH: {p.get('math_proficiency_pct') if p else None}")
```

Expected ranges (from the FY2023 / SY2024-25 baseline):

| Community | FRL | PPR | ELA | MATH |
|---|---|---|---|---|
| Albuquerque | ~86% | ~$18k | ~43% | ~25% |
| Santa Fe | ~77% | ~$20k | ~41% | ~22% |
| Española | ~86% | ~$18k | — | — |

Values should be in the same ballpark year over year. A sudden jump to
`None` means a column was renamed. A sudden jump to an implausible value
(e.g., 0% or 200%) means the filter logic matched the wrong rows.

### 3b. Confirm dimensions are not defaulting to 5

```bash
python3 main.py "Albuquerque" --depth fast
```

In the output, verify:
- `funding_environment` score is **not** 5.0 (it should be lower — NM PPR is
  below the state average)
- `operational_complexity` score is **not** 5.0 (it should be higher — high FRL)

If either returns 5.0, `nces_fetcher` is returning `None`. Check column names
in the new file against the list in Part 1f above.

---

## Part 4 — Cache Management After Any File Update

Always bust the community and synthesis caches before re-running after a data
update. Stale cache will serve old facts even after you replace the source files.

```bash
for CITY in nm-albuquerque nm-santa-fe nm-las-cruces \
            nm-espanola nm-truth-or-consequences; do
  rm -rf data/cache/community/nm/$CITY/
  rm -f  data/cache/synthesis/nm/$CITY/s6_brief_growth_mode2.json
done
```

Then re-run each city:

```bash
python3 main.py "Albuquerque"           --depth standard
python3 main.py "Santa Fe"              --depth standard
python3 main.py "Las Cruces"            --depth standard
python3 main.py "Española"              --depth standard
python3 main.py "Truth or Consequences" --depth standard
```

---

## Part 5 — If New NM Communities Are Added to the Pipeline

If you add a new community (city), you must add entries to both maps in
`config/states.yaml`:

1. **`nm_district_map`** — community_id → PED district name
   Find the district name in the PED charter roster or proficiency files.

2. **`nces_district_map`** — community_id → LEAID (7-digit string)
   Look up the LEAID using the `nces_lea_directory_YYYY.csv` file:
   filter by `STATENAME == "New Mexico"` and match on `LEA_NAME` (district name).
   The LEAID is a 7-digit zero-padded string (e.g., `"3500120"`).

If a community has no NCES mapping (e.g., Navajo Nation addresses with PO Box),
set its value to `null` in `nces_district_map`. The fetcher handles `null`
gracefully and returns `None` without raising.

---

## Quick Reference — All Files and Constants to Update Each Year

| What | File | Line | Action |
|---|---|---|---|
| Finance CSV filename | `pipeline/utils/nces_fetcher.py` | 33 | Update year in `FINANCE_CSV` |
| Lunch CSV filename | `pipeline/utils/nces_fetcher.py` | 34 | Update year in `LUNCH_CSV` |
| NM state avg PPR | `pipeline/utils/nces_fetcher.py` | 43 | Recompute from new finance file |
| ELA proficiency filename | `pipeline/utils/ped_fetcher.py` | 19 | Update year in `ELA_CSV` |
| Math proficiency filename | `pipeline/utils/ped_fetcher.py` | 20 | Update year in `MATH_CSV` |
| Charter roster | `data/raw/nm/charter_roster.csv` | — | Replace file; no code change |

---

## Silent Failure Warning

If NCES or PED renames a column between releases, the fetchers return `None`
silently. There is no error message. The affected scoring dimensions will
default to 5 with no indication that real data was expected.

**The spot-check in Part 3 is the only safety net for catching this.**
Do not skip it.
