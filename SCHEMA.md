# EMS Protocol Wiki — Schema

This document is the enforceable contract for all wiki pages. The compliance test suite
(`tests/test_schema_compliance.py`) validates every page in `wiki/` against these rules.
No page enters the system without satisfying this schema.

---

## Page Types

| Type | Slug prefix | Directory |
|------|-------------|-----------|
| `protocol` | e.g. `crush-syndrome-protocol` | `wiki/protocols/` |
| `condition` | e.g. `crush-syndrome` | `wiki/conditions/` |
| `medication` | e.g. `sodium-bicarbonate` | `wiki/medications/` |
| `procedure` | e.g. `opqrst` | `wiki/procedures/` |

Page type is determined by which subdirectory a file lives in.

---

## Scope Level Enum

Valid values for the `scope_level` field:

```
EMT-B       Basic EMT
AEMT        Advanced EMT
Paramedic   Paramedic
```

---

## Frontmatter Fields by Page Type

### `protocol`

```yaml
---
type: protocol
title: ""                       # required — human-readable name
sop_id: ""                      # required — official SOP/SOG identifier (e.g. "SOP-2024-CR-01")
scope_level: ""                 # required — EMT-B | AEMT | Paramedic
effective_date: ""              # required — ISO date (YYYY-MM-DD)
supersedes: ""                  # optional — sop_id this version replaces
treats_conditions: []           # auto — populated from source summary during ingest
medications: []                 # auto — populated from source summary during ingest
linked_pages: []                # auto — synced from [[wikilinks]] in body
status: ""                      # required — active | superseded | draft
---
```

### `condition`

```yaml
---
type: condition
title: ""                       # required
scope_level: ""                 # required — highest scope that manages this condition
protocols: []                   # auto — from source summary during ingest
red_flags: []                   # auto — from source summary during ingest
linked_pages: []                # auto
status: ""                      # required — active | draft
---
```

### `medication`

```yaml
---
type: medication
title: ""                       # required
scope_level: ""                 # required — minimum certification to administer
effective_date: ""              # required — date this drug reference was last reviewed
used_in_protocols: []           # auto — populated during ingest
contraindicated_conditions: []  # auto — populated during ingest
linked_pages: []                # auto
status: ""                      # required — active | draft
---
```

### `procedure`

```yaml
---
type: procedure
title: ""                       # required
scope_level: ""                 # required — minimum certification level
conditions: []                  # auto — populated during ingest
linked_pages: []                # auto
status: ""                      # required — active | draft
---
```

---

## Required Sections by Page Type

Sections are identified by exact `##` heading text. The ingest pipeline patches content
into these sections. No other top-level `##` headings are allowed.

### `protocol`
```
## When it applies
## Steps
## Medications & doses
## Scope boundaries
## Red flags
## Transport decision
```

### `condition`
```
## Recognition
## Differentials
## Assessment
## Field management
## When to escalate (ALS)
```

### `medication`
```
## Indications
## Adult dose
## Pediatric dose
## Route
## Contraindications
## Scope boundary
```

### `procedure`
```
## When to use
## Steps
## Common errors
## Documentation
```

---

## Relationship Rules

These relationships are auto-populated by `populate_relationships()` during ingest.
They also define the edges in the knowledge graph (`system/graph.yaml`).

```yaml
relationships:
  - source_type: protocol
    field: treats_conditions
    target_type: condition
    edges: [treats, treated_by]

  - source_type: protocol
    field: medications
    target_type: medication
    edges: [administers, administered_in]

  - source_type: condition
    field: procedures
    target_type: procedure
    edges: [assessed_by, assesses]

  - source_type: medication
    field: contraindicated_conditions
    target_type: condition
    edges: [contraindicated_in, contraindicates]
```

---

## Slug Conventions

- Lowercase, hyphen-separated, no special characters
- Condition slugs: the clinical name (`crush-syndrome`, `anaphylaxis`, `acute-mi`)
- Protocol slugs: condition + `-protocol` (`crush-syndrome-protocol`)
- Medication slugs: generic drug name (`epinephrine`, `sodium-bicarbonate`)
- Procedure slugs: acronym or short name (`opqrst`, `start-triage`, `spinal-motion-restriction`)
- Wikilinks in body use slug: `[[crush-syndrome]]`, `[[epinephrine]]`

---

## Auto-Populated vs. Required vs. Optional

| Tag | Meaning |
|-----|---------|
| `required` | Must be present and non-empty when status is `active`. Compliance test fails without it. |
| `auto` | Populated by the ingest pipeline. May be empty on draft pages. Not hand-edited. |
| `optional` | May be absent. |

**Templates and `draft` pages are exempt from `required` field checks.**
Only `status: active` pages are validated for completeness.

---

## Scenario Pages (training artifacts)

Scenarios live in `wiki/scenarios/` and are **not** canonical wiki pages — they are
OSCE-style training/eval artifacts generated from resources and vetted by an
EMT via the `/label-scenarios` skill. They are excluded from page iteration, routing,
and the index.

```yaml
scenario:
  frontmatter:
    scenario_id: required        # src{n}-s{NN}
    source_index: required       # index of the user resource it came from
    kind: required               # patient-care | provider-safety | medical-legal |
                                 # operational | documentation-qi | communication |
                                 # public-health | mci-triage
    scope_level: required        # EMT-B | AEMT | Paramedic
    status: required             # pending | approved | rejected
    age_group: optional          # neonate | pediatric | adult | geriatric
    difficulty: optional         # basic | intermediate | expert — practice level.
                                 # Auto-derived by ems.sim.difficulty; a reviewer
                                 # may override it via save_label(difficulty=...).
    labeled_by: auto             # EMT who reviewed (set on approve/reject)
    corrected: auto              # true if the reviewer edited the content
    correction_note: auto        # what/why was corrected
    conditions: auto             # vocabulary slugs (cross-linked)
    procedures: auto
    medications: auto
    citations: auto              # [SRC-{n}:p{NN}]
  sections: [Dispatch, Presentation, Vitals, Correct actions, Rationale, Red flags, Related]
```

**Expertise-marked fact:** a scenario with `status: approved` and a non-empty
`labeled_by`. Downstream stages (retrieval, eval, fine-tuning) filter on this to use
only EMT-verified data.
