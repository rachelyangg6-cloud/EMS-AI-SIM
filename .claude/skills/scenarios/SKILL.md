---
name: scenarios
description: >
  For one source, generate 10 OSCE-style scenarios and then interactively
  review/label them — runs generate-scenarios then label-scenarios back to back.
  Use when the user wants scenarios generated AND vetted for a source in one go.
  Takes a source number.
---

# Scenarios (generate + label)

Combined flow for a single source: generate the scenarios, then vet them. This
is `generate-scenarios` followed by `label-scenarios` for the same source `N`.

Input: a source number `N` (ask if not given).

## Steps

1. **Generate** — run the `generate-scenarios` skill for source `N`. It authors
   10 scenarios grounded in the source and saves them as `pending`.
2. **Label** — run the `label-scenarios` skill for source `N`. It walks you
   through each pending scenario (approve / edit / reject / author new) and stamps
   provenance, turning them into expertise-marked facts.

Do them in that order, on the same source number. After generation, confirm the
count before moving into the review loop. At the end, give the combined summary:
generated, approved, corrected, rejected, authored, remaining pending.
