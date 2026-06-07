# Wisconsin district proficiency data

`pipeline/fetchers/wi_proficiency_fetcher.py` reads **`wi_district_proficiency.csv`**
from this directory. That file is **not yet populated** — until it is, the WI
academic_need dimension is excluded from the composite (graceful degradation),
exactly like any state without proficiency data.

## Authoritative source (verified 2026-06-07)

Wisconsin Forward Exam, WI Dept. of Public Instruction (DPI) — district-level
ELA/Math proficiency, grades 3-8 and 10.

- Download (no login): <https://dpi.wi.gov/wisedash/download-files/type> ("Data Files by Topic").
- Public dashboard: <https://dpi.wi.gov/wisedash> (WISEdash Public Portal).
- Note: *WISEdash for Districts* is login-gated; use the **public** download files / portal.

## ⚠ Methodology caveat — decide before populating

Beginning **Spring 2024** the Forward Exam reports four performance levels —
**Advanced, Meeting, Approaching, Developing** (new cut scores). There is no single
"Proficient" level. To produce a `% proficient` comparable to the MS/NM/TN adapters,
define **proficient = Advanced + Meeting** and apply it consistently.

Pre-Spring-2024 files use the older Advanced/Proficient/Basic/Below-Basic levels
(proficient = Advanced + Proficient). **Do not mix vintages** without normalizing the
level definition — it would corrupt the academic_need signal.

## Expected file format

Same schema as `data/raw/ms/ms_district_proficiency.csv`:

```
LEAID,DistrictName,EntityID,ELAProficiencyPct,MathProficiencyPct,SchoolYear
5509600,MILWAUKEE,...,21.4,17.9,2023-24
```

- `LEAID` — 7-digit NCES district id (matches the WI `nces_district_map` in `config/states.yaml`).
- `ELAProficiencyPct` / `MathProficiencyPct` — district "% proficient" (Advanced + Meeting, see caveat).

**Do not invent values.** Omit a district if its number is unavailable.
