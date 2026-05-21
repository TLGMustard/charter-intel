# Internal Intelligence Layer

## Purpose

This directory holds non-public, confidential, or partner-contributed intelligence that supplements the public-source analysis.

**The public-source pipeline and the internal layer are STRICTLY SEPARATED.**
No data from `/internal/` is ever included in publicly shareable outputs without explicit operator action.

---

## Design Principles

1. **Public pipeline never reads from `/internal/`.**
   The S1–S7 pipeline reads only from `data/` and `config/`. It produces outputs in `outputs/` that are safe to share externally.

2. **Internal layer produces separate enriched outputs.**
   When internal data exists for a community, a separate `internal_brief_enrichment_{community_id}.md` is generated and stored here — never in `outputs/`.

3. **Merging is a manual, human-controlled step.**
   If an analyst wants to combine public and internal intelligence into a final deliverable, that is a deliberate human action, not an automated one.

4. **All internal data requires source tagging.**
   Even inside this directory, every intel note must be tagged with:
   - Source (person, organization, date)
   - Sensitivity level (INTERNAL | PARTNER_CONFIDENTIAL | DO_NOT_DISTRIBUTE)
   - Whether it can be referenced in public outputs (typically NO)

---

## What Belongs Here

✅ Notes from operator interviews
✅ Partner-contributed market intelligence
✅ TMT internal observations from site visits
✅ Unverified signals worth tracking but not suitable for public analysis
✅ Board/leadership intelligence about specific schools
✅ Real estate leads and facility contacts

❌ Student or family data (never here — never anywhere in this system)
❌ Personnel matters about individuals
❌ Anything the contributor expected to be confidential but isn't marked as such

---

## File Naming Convention

```
intel_notes/{community_id}_{YYYY-MM-DD}_{author_initials}.md
```

Example: `intel_notes/nm-albuquerque_2026-03-15_bj.md`

---

## Intel Note Template

```markdown
# Intel Note: [Community Name]
**Date:** YYYY-MM-DD
**Author:** [Initials or name]
**Sensitivity:** INTERNAL | PARTNER_CONFIDENTIAL | DO_NOT_DISTRIBUTE
**Public-safe:** NO | YES — [specify what portion]

## Source
[Who provided this? In what context?]

## Intelligence
[What was shared or observed?]

## Implications for Analysis
[How does this change or add to the public analysis?]

## Follow-up Needed
[What should be verified or acted on?]
```

---

## Reminder

Per standing AI usage guidelines, do NOT paste internal notes directly into a Claude conversation or prompt without first anonymizing or redacting any identifiable student, family, or personnel information. The system is designed so this directory is processed separately and never fed into the automated pipeline.
