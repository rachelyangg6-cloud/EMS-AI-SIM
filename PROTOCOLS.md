# EMS Protocol Wiki — Content Conventions

Naming rules, section templates, and editorial standards for wiki pages.
See `SCHEMA.md` for the machine-enforceable schema.

---

## Naming Conventions

### Files
- Filename = slug + `.md`
- Examples: `wiki/protocols/crush-syndrome-protocol.md`, `wiki/medications/epinephrine.md`
- Templates: `_template.md` in each subdirectory — never ingested, never queried

### SOP IDs
- Format: `SOP-YYYY-ABBR-NN` (e.g. `SOP-2024-CR-01` for the first crush syndrome protocol of 2024)
- Used in citations: `[SOP-2024-CR-01:Steps]`
- The `sop_id` frontmatter field must match exactly how the source document names itself

### Wikilinks
- Format: `[[slug]]` in body text
- Resolved to the file at `wiki/<type>/<slug>.md`
- The ingest pipeline extracts all `[[...]]` patterns and syncs them into `linked_pages`

---

## Section Templates

### Protocol page

```markdown
---
type: protocol
title: ""
sop_id: ""
scope_level: ""
effective_date: ""
supersedes: ""
treats_conditions: []
medications: []
linked_pages: []
status: draft
---

## When it applies

<!-- Clinical scenario and patient presentation that triggers this protocol -->

## Steps

<!-- Numbered, sequential steps in order of execution -->

## Medications & doses

<!-- Drug name, dose, route, repeat intervals. Cite weight-based calculations explicitly. -->

## Scope boundaries

<!-- What EMT-B can do vs AEMT vs Paramedic. What requires medical direction. -->

## Red flags

<!-- Signs that indicate rapid deterioration or require immediate intervention change -->

## Transport decision

<!-- Load-and-go vs stay-and-play criteria. Destination decision (trauma center, stroke center, etc.) -->
```

---

### Condition page

```markdown
---
type: condition
title: ""
scope_level: ""
protocols: []
red_flags: []
linked_pages: []
status: draft
---

## Recognition

<!-- Signs and symptoms. What the patient looks like, complains of, shows on assessment -->

## Differentials

<!-- Conditions that present similarly and how to distinguish them in the field -->

## Assessment

<!-- Focused assessment steps: OPQRST, SAMPLE, vitals, physical exam priorities -->

## Field management

<!-- General management principles before protocol-specific steps -->

## When to escalate (ALS)

<!-- Specific indicators that should trigger ALS intercept or upgrade -->
```

---

### Medication page

```markdown
---
type: medication
title: ""
scope_level: ""
effective_date: ""
used_in_protocols: []
contraindicated_conditions: []
linked_pages: []
status: draft
---

## Indications

<!-- Clinical scenarios where this medication is indicated -->

## Adult dose

<!-- Dose, route, onset, duration. Include max dose and repeat intervals -->

## Pediatric dose

<!-- Weight-based dosing. Include age/weight cutoffs. Write "Not indicated" if not used peds -->

## Route

<!-- IV, IM, IN, PO, SL, IO, nebulized — list all approved routes -->

## Contraindications

<!-- Absolute and relative contraindications -->

## Scope boundary

<!-- Minimum certification to administer. Standing order vs medical direction required -->
```

---

### Procedure page

```markdown
---
type: procedure
title: ""
scope_level: ""
conditions: []
linked_pages: []
status: draft
---

## When to use

<!-- Clinical indication. Which conditions or patient presentations trigger this procedure -->

## Steps

<!-- Numbered steps in order -->

## Common errors

<!-- Frequently made mistakes and how to avoid them -->

## Documentation

<!-- What to document on the PCR/ePCR after performing this procedure -->
```

---

## Editorial Standards

### Language
- Active voice, second person: "Administer 0.3 mg epinephrine IM" not "Epinephrine may be administered"
- Spell out abbreviations on first use per page: "SpO₂ (oxygen saturation)"
- Use metric units: mg, mL, kg — not grains, ounces, lbs (except where source document uses lbs for weight-based dosing)

### Doses
- Always include unit: `0.3 mg` not `0.3`
- Always include route: `0.3 mg IM` not `0.3 mg`
- Weight-based: `0.01 mg/kg IM (max 0.3 mg)`
- Never round silently — write the calculation out

### Scope notes
- Every intervention in a section must be tagged if it crosses scope: `[Paramedic only]`, `[AEMT only]`
- BLS interventions need no tag
- Scope boundary section summarizes all scope-split items on that page

### Citations
- Reference the source document using SOP ID: `Per [SOP-2024-CR-01:Steps]`
- Never paraphrase a dose — quote or cite the source exactly

### Status lifecycle
```
draft → active → superseded
```
- `draft`: page exists but ingest is incomplete or review pending
- `active`: approved, lint-passing, in retrieval index
- `superseded`: replaced by a newer version; demoted in retrieval but retained for audit
