---
name: build-graph
description: >
  Build/refresh the knowledge graph (system/graph.yaml) from page frontmatter and
  wikilinks, and answer graph questions (related/treats/meds). Deterministic, no API.
  Use when the user asks to build the graph or explore page relationships.
---

# Build Graph

Build the knowledge graph `/query` uses for graph-proximity search. Edges come
from the typed relationship fields the ingest already populates plus
`[[wikilinks]]` — so this is **deterministic** (no Anthropic API, no reasoning).

## Run it

```bash
python -m ems.cli.graph rebuild            # rebuild system/graph.yaml
python -m ems.cli.graph stats              # node/edge counts
python -m ems.cli.graph related <slug>     # neighbors of a page
python -m ems.cli.graph treats <condition> # protocols that treat a condition
python -m ems.cli.graph meds <protocol>    # meds administered in a protocol
```

Or from Python:

```python
from ems import graph
g = graph.build_graph()
print(graph.graph_stats(g))
```

## Notes

- The graph is `{nodes: {slug: type}, edges: [[src, rel, dst], ...]}` at
  `system/graph.yaml`. Relationship edges (`treats`/`administers`/…) come from
  `RELATIONSHIP_RULES`; `[[wikilinks]]` and `linked_pages` become `related` edges.
  A page's `age_group` values become `applies_to_age` edges to `age_group` nodes
  (`pediatric`, `geriatric`, …), so you can list pages for a life stage.
- Rebuild after ingesting new sources so `/query`'s graph layer stays current.

## Wrap-up

Report node and edge counts from `graph_stats()`; if the user asked a
related/treats/meds question, show the answer.
