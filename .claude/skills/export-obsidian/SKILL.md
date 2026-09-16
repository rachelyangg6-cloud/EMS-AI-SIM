---
name: export-obsidian
description: >
  Rebuild obsidian_wiki/ — a browsable Obsidian vault generated from wiki/, with
  Obsidian-legal nested tags, wikilinked relationships, and Dataview dashboards.
  Deterministic, no API. Use when the user wants to explore the corpus in
  Obsidian, or after ingesting a source so the vault is current.
---

# Export Obsidian Vault

Write `wiki/` out as `obsidian_wiki/`, shaped so Obsidian's tag pane, graph
view, backlinks and Dataview all work on it. **Deterministic** — no Anthropic
API, no reasoning.

## Run it

```bash
python -m ems.cli.obsidian export                 # rebuild the vault
python -m ems.cli.obsidian export --reset-graph   # ... and re-apply graph settings
```

`--reset-graph` overwrites `.obsidian/graph.json` with the tuned defaults —
tags shown as nodes, forces spread out, and the color groups written as the
decimal integers Obsidian stores, which is the part that is unreasonable to
enter through a color wheel. It keeps a `.bak` and preserves any key it does
not manage. **Quit Obsidian first:** it holds those settings in memory and
writes them back, so a forced write while it is open is usually undone. The
command warns if it sees Obsidian running.

Then open `obsidian_wiki/` as a vault (Obsidian → Open folder as vault) and
start at **Start here**.

## What it changes, and why

`wiki/` stays exactly as it is — this is one-way. The copy is rewritten because
three things in the corpus are unusable in Obsidian as written:

| Source | Vault | Why |
|---|---|---|
| `tags: [airway and breathing]` | `tags: [topic/airway-and-breathing]` | Obsidian tags cannot contain spaces, so the tag pane and `tag:` search silently do nothing |
| `linked_pages: [oxygen]` | `linked_pages: ["[[oxygen]]"]` | bare slugs are strings to Obsidian — 639 edges the graph could not see |
| `kind`, `source_index`, `scope_level`, `status`, `age_group`, `labeled_by` | also nested tags (`kind/patient-care`, `source/src19`, …) | one click filters the graph by any axis |
| a body with no `[[link]]` | gains a `## Related` line | 78 scenarios were graph orphans |

Every original field survives, and the plain slugs are kept as `<field>_slugs`,
so a Dataview query can still get at them.

## Notes

- **The vault is generated and gitignored.** Edits made there are lost on the
  next export; the fix for a wrong page belongs in `wiki/`. Deleting the folder
  costs nothing.
- **Nothing reads it back.** `ems.paths` resolves to `wiki/`, so the
  application never sees `obsidian_wiki/`. That is what makes it safe to write frontmatter here in a
  shape the application would reject.
- **`.obsidian/` is never deleted.** It holds installed plugins and workspace
  layout. A graph color config is written only if one is not already there.
- Re-run after `/process-source`, or whenever the vault looks stale.
- **What another person has to do by hand.** The export writes the notes, the
  dashboards, the graph settings and the legend, and sets the vault dark. It
  cannot install plugins — that is downloaded code, and Obsidian gates it behind
  Restricted Mode. So a colleague runs the export, then: turn on community
  plugins, install **Dataview** and **Obsidian Charts**, and switch on
  Dataview's **Enable JavaScript Queries**. Without that last one the tables
  render and every chart stays blank.
- **The graph picture is not reproducible, and cannot be.** The layout is a
  force simulation with random starting positions, so the arrangement differs
  every time it is opened — including for the person who exported it. The
  colors, filters and forces are identical; the exact picture is not. That is
  why `frontend/public/features/library-graph.png` is committed rather than
  regenerated.

## Wrap-up

Report the note count per directory and where the vault was written. If the user
was looking for something specific — a coverage gap, a chart — point them at the
dashboard that answers it: `Corpus overview`, `Coverage gaps`, `Review quality`,
or `Charts`.
