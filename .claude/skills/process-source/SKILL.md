---
name: process-source
description: >
  Full per-source pipeline: ingest the source into wiki pages, generate 10
  OSCE-style scenarios, then interactively review/label them. Runs
  ingest-source, generate-scenarios, and label-scenarios in order for one
  source. Use to process a source end to end. Takes a source number.
---

# Process Source (ingest + generate + label)

End-to-end flow for a single source `N`, chaining all three per-source skills.

Input: a source number `N` (ask if not given).

## Steps

1. **Ingest** — run the `ingest-source` skill for source `N`: OCR if needed,
   then read the source and write its condition/procedure wiki pages with
   `[SRC-N:pNN]` citations.
2. **Generate** — run the `generate-scenarios` skill for source `N`: author 10
   scenarios grounded in the source, saved as `pending`.
3. **Label** — run the `label-scenarios` skill for source `N`: review each
   scenario (approve / edit / reject / author new), stamping provenance into
   expertise-marked facts.

Run them strictly in that order on the same source number. Pause between steps to
confirm results (pages written, scenarios generated) before continuing. Finish
with an end-to-end summary: pages created/updated, scenarios generated, and the
label tally (approved / corrected / rejected / authored / pending).
