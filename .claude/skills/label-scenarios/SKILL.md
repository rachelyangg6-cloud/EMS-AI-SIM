---
name: label-scenarios
description: >
  Interactively review, correct, and approve generated EMS training scenarios
  (or author new ones) so they become expertise-marked facts for later stages.
  Use when the user wants to label/vet scenarios in wiki/scenarios/. Optionally
  takes a source number to review just that source's queue.
---

# Label Scenarios

Walk the user through the queue of unvetted OSCE-style scenarios in
`wiki/scenarios/` (status `pending`) and turn each into an **expertise-marked
fact** — an EMT-verified record downstream stages (retrieval, eval, fine-tuning)
can trust. The user is the domain expert; you are the scribe.

Input: an optional source number `N` (review only that source's queue). With no
argument, review all pending scenarios.

## Setup

First ask the user for their name/initials if not already known — it's recorded as
`labeled_by` (the provenance stamp). Then load the queue (pass `source_index=N` when a
source number was given):

```python
from ems.scenarios import list_pending, save_label, author_scenario
pending = list_pending(source_index=N)   # or list_pending() for all sources
```

Report how many are pending. If zero, tell the user there's nothing to review and
offer to author new scenarios (see **Author**).

## Review loop — one scenario at a time

For each file in `pending`, read it and present it to the user in a clean,
readable form: dispatch, presentation, vitals, the numbered correct-action
sequence, scope level, **age_group** (the patient's life stage), rationale, red
flags, and citations. Then ask the user to choose:

- **Approve** — the scenario is clinically correct as written.
  ```python
  save_label(path, status="approved", labeled_by=NAME)
  ```
- **Edit** — mostly right but needs correction (wrong dose/route/scope, wrong
  action order, a missing red flag, unrealistic presentation). Ask the user what's
  wrong, make the exact edits they describe to the section bodies, and save the
  corrected markdown body plus a short note on what changed:
  ```python
  save_label(path, status="approved", labeled_by=NAME,
             corrected=True, correction_note="<what/why>", new_body=CORRECTED_BODY)
  ```
  Preserve the `## Dispatch / Presentation / Vitals / Correct actions / Rationale /
  Red flags / Related` section structure. Keep `[SRC-{n}:p{NN}]` citations.
  To correct a mistagged life stage, pass `age_group="pediatric"` (or neonate /
  adult / geriatric) to the same `save_label` call. To correct the topics it is
  filed under, pass `tags=[...]` — values must come from `scenario_tags` in
  `system/source-vocabulary.json`. The tags on a new scenario are derived from
  its conditions and its source, which is a starting point and not a verdict:
  a case in the vital-signs source about an airway patient is filed under both,
  and only the reviewer knows when that is wrong.
- **Reject** — fundamentally wrong or not useful.
  ```python
  save_label(path, status="rejected", labeled_by=NAME,
             correction_note="<why rejected>")
  ```
- **Skip** — leave it `pending` and move on.

Move to the next scenario after each decision. Do not batch — the value is the
user's per-scenario judgment.

**Safety:** never invent or "fix" a dose, route, or scope on your own — only apply
the correction the user states. When the user is unsure, leave it `pending`.

## Author (add a new scenario)

When the user wants to add a scenario the model missed, collect the fields
conversationally and build a `Scenario`, then save it as already-approved:

```python
from ems.models import Scenario
s = Scenario(
    dispatch=..., presentation=..., vitals=...,
    correct_action_sequence=(...),
    scope_level="EMT-B",  # or AEMT / Paramedic
    age_group="adult",    # neonate | pediatric | adult | geriatric
    rationale=...,
    red_flags=(...),
    citations=(...),       # optional
    conditions=(...), procedures=(...), medications=(...),  # vocabulary slugs
)
author_scenario(source_index=N, scenario=s, labeled_by=NAME)
```

Use vocabulary slugs from `system/source-vocabulary.json` for the
condition/procedure/medication fields so the scenario cross-links to the wiki.

## Wrap-up

At the end, summarize: how many approved, corrected, rejected, authored, and how
many remain pending.
