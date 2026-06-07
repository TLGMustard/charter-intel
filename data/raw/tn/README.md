# Tennessee district proficiency data

`pipeline/fetchers/tn_proficiency_fetcher.py` reads **`tn_district_proficiency.csv`**
from this directory. That file is **not yet populated** — until it is, the TN
academic_need dimension is excluded from the composite (graceful degradation),
exactly like any state without proficiency data.

## Authoritative source (verified 2026-06-07)

Tennessee Comprehensive Assessment Program (TCAP), TN Dept. of Education —
district-level ELA/Math "% proficient" (on track + mastered).

- Download (no login): <https://www.tn.gov/education/districts/federal-programs-and-oversight/data/data-downloads.html>
  → **State Assessments** section → **Assessment Files** tab (district-level file).
- Report card portal: <https://tdepublicschools.ondemand.sas.com/>
- Latest released cycle at review: **SY 2023-24**.

## Expected file format

Same schema as `data/raw/ms/ms_district_proficiency.csv`:

```
LEAID,DistrictName,EntityID,ELAProficiencyPct,MathProficiencyPct,SchoolYear
4700148,MEMPHIS-SHELBY COUNTY SCHOOLS,...,28.5,22.1,2023-24
```

- `LEAID` — 7-digit NCES district id (matches the TN `nces_district_map` in `config/states.yaml`).
- `ELAProficiencyPct` / `MathProficiencyPct` — district "% proficient".

**Do not invent values.** Omit a district if its number is unavailable.
