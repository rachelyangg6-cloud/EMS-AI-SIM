---
name: build-embeddings
description: >
  Build/refresh the local vector index over the wiki's canonical pages so query
  can do semantic search. Deterministic (local sentence-transformers, no API).
  Use when the user asks to (re)build embeddings or the embedding index.
---

# Build Embeddings

Build the section-level vector index used by `/query`. Embeddings are **local**
(`sentence-transformers`, no Anthropic API) — this skill just drives the
deterministic builder and reports what happened. There is no reasoning to do.

## Run it

```bash
python -m ems.cli.embed          # incremental/first build
python -m ems.cli.embed --force  # full rebuild (use after a model swap)
python -m ems.cli.embed --stats  # show current index stats
```

Or from Python:

```python
from ems import embeddings
index = embeddings.build_embedding_index(force=False)
print(embeddings.index_stats())
```

## Notes

- The index lands at `system/embeddings.json`, one entry per `##` section of each
  canonical page (scenarios are excluded).
- Until the index exists, `/query` runs keyword-only and ingest never loads the
  model — the vector layer is opt-in. Once built, the page updater keeps it fresh
  incrementally on each ingest.

## Wrap-up

Report the model, section count, and page count from `index_stats()`.
