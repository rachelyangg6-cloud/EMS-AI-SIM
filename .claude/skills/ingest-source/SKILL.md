---
name: ingest-source
description: >
  Ingest one EMT resource into the wiki: extract the source (OCR, PDF or TXT, if needed),
  then read it and write condition/procedure reference pages with citations.
  Use when the user asks to ingest/process a source (e.g. "ingest source 3").
  Takes a source number.
---

# Ingest Source

Turn one resource into condition/procedure wiki pages. **You are the LLM
here** — no Anthropic API is called. You read the OCR'd source, decide what it
covers, draft the section content yourself, and persist it through the
deterministic `ems` helpers.

Input: a source number `N` (ask if not given).

## 1. Ensure the source is extracted

If `raw/source-N.md` does not exist, extract it (local, no API). The resources
directory holds source `N` as a `source_N/` folder of page PNGs (OCR'd with
Apple Vision), a `source_N.pdf` text PDF, or a `source_N.txt` file (pages split
on form feeds). A scanned PDF with no text layer is refused; export its pages as
PNGs into `source_N/` instead. Default resource location is `/Volumes/WorkShared/Projects/EMSContents/textbook`
(confirm/adjust with the user if the mount isn't present):

```bash
python -m ems.cli.resource /Volumes/WorkShared/Projects/EMSContents/textbook --sources N
```

## 2. Read the source and vocabulary

```python
from ems.frontmatter import read_page
from ems.paths import raw_dir
from ems.vocabulary import load_vocabulary

fm, resource_text = read_page(raw_dir() / "source-N.md")
vocab = load_vocabulary()   # approved condition/procedure/medication slugs
```

Read `resource_text` fully. It has `[p.NN]` page markers — you'll cite pages as
`[SRC-N:pNN]`.

## 3. Decide what the source covers (you do the reasoning)

- Which **condition** and **procedure** slugs from the vocabulary does this
  source actually address? Use only approved slugs (invent none). Many sources
  (e.g. "Intro to EMS", "Well-Being of the EMT") are **not patient-care** and map
  to few or no condition/procedure pages — that's expected. Do not force matches
  or invent slugs. See **When a source isn't patient-care** below.
- Build a `SourceSummary` capturing the source:

```python
from ems.models import SourceSummary
summary = SourceSummary(
    clinical_summary="<2-3 sentences on what the source covers>",
    conditions_addressed=("<condition-slug>", ...),
    red_flags_mentioned=("<plain-text red flag>", ...),
    medications_referenced=("<medication-slug>", ...),
    scope_level="EMT-B",   # highest cert the source's content pertains to
)
```

## 4. Write each target page (condition/procedure only — never protocol)

For each page, draft the relevant sections **from the source text**. Section
headings must match the page type's schema:
- condition: `Recognition`, `Differentials`, `Assessment`, `Field management`, `When to escalate (ALS)`
- procedure: `When to use`, `Steps`, `Common errors`, `Documentation`

Rules for the content you write:
- **Cite every clinical claim** with `[SRC-N:p<NN>]` using the `[p.NN]` markers.
- **Do not invent** doses, steps, or facts not in the source text.
- Cross-link related pages with `[[slug]]` (they sync into `linked_pages`).
- Tag scope-restricted steps `[Paramedic only]` / `[AEMT only]`.

Then persist (no LLM call — this just writes files):

```python
from ems.page_updater import apply_agent_update
apply_agent_update(
    slug="<condition-or-procedure-slug>",
    section_content={
        "Recognition": "<your drafted text with [SRC-N:pNN] citations>",
        "Assessment": "...",
        # only the sections you actually wrote
    },
    summary=summary,
    vocabulary=vocab,
    source_kind="resource",
    source_index=N,
    age_group=["adult"],   # which life stages this page's content covers
)
```

`apply_agent_update` creates the page from its template if missing, fills scope
level, populates relationships/red-flags, syncs `[[wikilinks]]`, and marks it
active.

**`age_group`** (multi-value) records which life stages the page's content
actually covers, from the `age_groups` vocabulary (`neonate | pediatric | adult
| geriatric`). Set it from the source — e.g. a medication page with both adult
and pediatric dosing → `["pediatric", "adult"]`; a page with no age-specific
content → `["adult"]`. It's stored as a retrieval keyword (age-specific queries
surface age-specific pages), so tag honestly and don't invent coverage the
source doesn't provide. Omit the argument to leave the field untouched. It returns `None` and skips if a slug resolves to a protocol page
(resource is reference material, not protocols).

## When a source isn't patient-care

Not every source maps to condition/procedure pages, but **every source has EMS
value worth capturing.** When a source is non-clinical (or only partly
clinical), its value is captured as **scenarios** (via `generate-scenarios`),
not reference pages. Don't report "0 pages" as a dead end — say what the source
*is* and which scenario categories apply. Scenario categories span all of EMS
service, not just patient care:

- **patient-care** — clinical assessment and treatment of a patient.
- **provider-safety** — the EMT's own safety/wellness: scene safety, Standard
  Precautions/PPE, exposure response, hazmat distance, violence retreat,
  stress/critical-incident recognition, immunizations. (e.g. "Well-Being" source)
- **medical-legal** — consent, refusal of care, DNR/advance directives, patient
  confidentiality/HIPAA, abandonment, negligence/duty to act, mandatory reporting
  (abuse/neglect), crime-scene preservation. (e.g. "Medical/Legal & Ethical" source)
- **operational** — ambulance operations and safe driving, radio/dispatch
  communication, staging, mutual aid, hospital-destination selection, equipment
  checks. (e.g. "EMS Operations", "Highway Safety" sources)
- **documentation-qi** — accurate/complete PCR writing, transfer-of-care handoff
  report, quality-improvement review, error reporting.
- **communication** — therapeutic/interpersonal communication, professionalism,
  cultural competence, interprofessional teamwork, family interaction, death
  notification.
- **public-health** — injury prevention, vaccination clinics, disease
  surveillance, Mobile Integrated Health / community paramedicine.
- **mci-triage** — multiple-casualty incidents, START triage, incident command
  (ICS) roles, scene size-up / resource determination.

If the source is non-clinical, still finalize it (below), then tell the user
which scenario categories fit and offer to run `generate-scenarios N`. If it's
partly clinical, write the condition/procedure pages that genuinely apply **and**
note the scenario categories for the rest.

## 5. Finalize

Mark the source ingested and refresh the index/log:

```python
from ems.frontmatter import read_page, write_frontmatter
from ems.index_log import append_log, regenerate_index
from ems.paths import raw_dir

note = raw_dir() / "source-N.md"
fm, _ = read_page(note)
fm["status"] = "ingested"
write_frontmatter(note, fm)
append_log(f"source-N → <comma-separated pages you wrote>")
regenerate_index()
```

## Wrap-up

Report which pages you created/updated and the conditions/procedures covered. If
the source was non-clinical (or only partly clinical), say so plainly rather
than manufacturing pages — and name the scenario categories that fit (see **When
a source isn't patient-care**), offering to run `generate-scenarios N` to
capture that value.
