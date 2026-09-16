---
name: generate-scenarios
description: >
  Generate 10 detailed EMS training scenarios (with correct EMT actions) from a
  processed resource, saved as pending for review. Scenarios may be
  patient-care OR provider-safety/wellness OR other EMS categories, depending on
  what the source is about. Use after a source is ingested, or when asked to
  generate scenarios for a source. Takes a source number.
---

# Generate Scenarios

Create 10 rich, realistic training scenarios from one resource.
**You are the LLM here** — no Anthropic API is called. You read the source and
author the scenarios yourself, then persist each as a `pending` file for the EMT
to review via `label-scenarios`.

Input: a source number `N` (ask if not given).

## Scenario categories (pick per source, not one-size-fits-all)

A scenario tests a decision an EMT must get right — which is **not only
patient-care**. Choose the category that matches the source's content, and set
it as the `kind` when you save. Mix categories within a source when the material
spans several. Supported `kind` values:

- **`patient-care`** — clinical: a patient with a presentation the EMT assesses
  and treats. `presentation` = what you find on the patient; `vitals` = the vital
  signs; `correct_action_sequence` = the correct clinical response; cross-link
  `conditions`/`procedures`/`medications` slugs.
- **`provider-safety`** — the EMT's own safety/wellness decision (scene safety,
  PPE/Standard Precautions, exposure response, hazmat distance, violence
  retreat, stress/exposure). `presentation` = the scene/hazard/exposure;
  `vitals` = `"N/A — provider-safety scenario"`; clinical slugs usually empty.
- **Other EMS categories** (see the `ingest-source` skill for the full list and
  definitions): `medical-legal`, `operational`, `documentation-qi`,
  `communication`, `public-health`, `mci-triage`. Frame `presentation` as the
  situation, `correct_action_sequence` as the correct EMT actions, and keep
  clinical fields empty/`N/A` when they don't apply.

Ground **every** scenario in the source text and cite pages with
`[SRC-N:p<NN>]` regardless of category. `scope_level` is still required
(non-clinical scenarios generally apply at `EMT-B`).

## 1. Read the source and vocabulary

```python
from ems.frontmatter import read_page
from ems.paths import raw_dir
from ems.vocabulary import load_vocabulary

fm, resource_text = read_page(raw_dir() / "source-N.md")
vocab = load_vocabulary()
```

If `raw/source-N.md` doesn't exist, tell the user to run
`ingest-source N` (or the OCR step) first.

## 2. Author 10 scenarios (you do the reasoning)

Ground every scenario in the source text — realistic dispatch, presentation,
and the *correct* EMT response. Cover different topics across the 10. For each,
build a `Scenario`:

```python
from ems.models import Scenario
s = Scenario(
    dispatch="<the 911 call as it comes in>",
    presentation="<what you find on scene>",
    vitals="<initial vital signs — see the rule below>",
    correct_action_sequence=(
        "<ordered correct EMT action>",
        "...",
    ),
    scope_level="EMT-B",          # highest cert the correct actions require
    age_group="adult",            # neonate | pediatric | adult | geriatric (the patient's life stage)
    rationale="<why this is the correct response>",
    red_flags=("<warning sign>", ...),
    citations=("[SRC-N:p<NN>]", ...),   # from the [p.NN] markers
    conditions=("<slug>", ...),    # approved vocabulary slugs (cross-links)
    procedures=("<slug>", ...),
    medications=("<slug>", ...),
)
```

### `dispatch` must say who you are going to and why

**For `kind: patient-care`, the dispatch names a person and a complaint.**
That means a life stage or age, and what is wrong:

> `"62-year-old man, chest pain and short of breath, conscious and alert."`
> `"Four-year-old, difficulty breathing, mother on scene."`

Not `"Patient en route to the hospital; care already begun."` and not
`"Head-on motor-vehicle collision."` — a trainee who is told neither who the
patient is nor what is wrong has nothing to assess and no thread to follow. Four
in five of the existing scenarios open this way and it is the single most common
reason a call feels pointless to run.

A scenario built around a *procedure* rather than a patient — reassessment,
handover, lifting — still has a patient. Give them one: an age, a complaint, and
a reason the ambulance was called.

### `vitals` must carry real numbers on a patient-care scenario

**For `kind: patient-care`, give a full numeric set: RR, pulse, SpO2 and BP.**
Write them plainly so they parse — `RR 36, pulse 118, SpO2 82%, BP 96/60` — and
add the descriptive findings after: `; cyanotic, one-word dyspnea`.

This field is not a restatement of the complaint. `"Cardiac-type chest pain; no
aspirin allergy"` is a presentation, not a set of vitals, and leaves the
simulator's monitor blank. The numbers drive the animation (chest-rise rate *is*
the respiratory rate) and are what a trainee reacts to, so a scenario without
them cannot be practiced properly.

Pick numbers the condition would actually produce, and make them internally
consistent — an SpO2 of 97% alongside "severe respiratory distress" teaches the
wrong reflex. Where the patient genuinely has no number, say which and why
(`RR 0 — apneic`), rather than omitting it.

The other `kind` values have no patient, so `vitals="N/A — <kind> scenario"`
remains right for them.

Rules:
- **Every dose/step must be supported by the source** — invent nothing.
- Cite pages with `[SRC-N:p<NN>]`.
- `scope_level` must match what `correct_action_sequence` actually requires.
- Use only approved vocabulary slugs for conditions/procedures/medications so the
  scenario cross-links to the wiki pages.
- **`age_group`** is the patient's life stage (one of `neonate | pediatric |
  adult | geriatric`, from the `age_groups` vocabulary); default `"adult"`.
  **When the source covers pediatric care, dedicate 1–2 of the 10 scenarios to
  `age_group="pediatric"`** (or `"neonate"`); tag `"geriatric"` where the material
  is age-specific. If the source genuinely has no pediatric angle, generate 10
  and note that no peds scenario was warranted — never invent age-specific content
  the source does not support (same rule as clinical facts).

### Every step must be something the EMT says or does

A line in `correct_action_sequence` is graded by matching it against what the
trainee actually said. A line nobody would ever say out loud cannot be matched,
cannot be hinted, and quietly grades on word overlap instead — 34% of the
existing corpus is in that state.

**Do not write commentary as a step.** These are not steps:

> "Do not delay epinephrine to finish the history — it is the priority"
> "Be prepared to give a second dose if she does not improve"
> "Remember that head injuries can make a patient appear intoxicated"

The first is an *ordering rule*, the second is a *contingency*, the third is a
*fact*. Facts belong in `rationale`; warning signs belong in `red_flags`.

**Express ordering by position, not by prose.** If epinephrine must come before
the history, number it before the history. The grader reads the numbering as the
order the call should run in, and marks a time-critical treatment down when it
is done after steps the rubric puts later. Writing "do not delay X" instead
leaves the requirement ungraded and the sequence unenforced.

**Express a contingency as the action that reveals it.** "Be prepared to give a
second dose" becomes "Reassess 2 minutes after the dose and give a second if she
has not improved" — something the trainee can actually say.

Check your work:

```bash
python -m ems.cli.rubric_check --generated     # or --source N
```

Every line it reports is one the grader cannot see.

## 3. Save each as pending (no LLM call)

```python
from ems.scenarios import save_scenario
path = save_scenario(N, s, kind="provider-safety")   # or "patient-care", "operational", ...
# writes wiki/scenarios/chN-sMM.md, status: pending, kind: <category>
```

`save_scenario` numbers files after any existing `chN-s*` so re-runs never
clobber already-labeled scenarios, and cross-links the slugs as `[[wikilinks]]`.
Always pass the `kind` that matches the scenario's category (default is
`patient-care` if omitted).

## Wrap-up

Report how many scenarios you wrote and where. Tell the user to run
`label-scenarios N` to review and vet them into expertise-marked facts.
