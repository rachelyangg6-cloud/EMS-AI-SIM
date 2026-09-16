---
name: query
description: >
  Answer an EMS field question from the wiki with cited, scope-aware synthesis and
  no Anthropic API — you (the agent) are the LLM. Retrieval and citation-checking
  are deterministic helpers. Use when the user asks a protocol/field question.
  Takes a question and optional --scope.
---

# Query

Answer a field question from the wiki. **You are the LLM here** — no Anthropic API
is called. The deterministic `ems` helpers do retrieval, scope filtering, and
citation verification; **you** write the cited answer from the retrieved pages.
This is the no-API twin of `ems.query.answer_query`.

Input: a question, and an optional provider scope (`EMT-B` default, `AEMT`,
`Paramedic`). Ask for the scope if it matters and wasn't given.

## 1. Retrieve context (deterministic)

```python
from ems.query import load_pages, scope_filter, rank, build_context, _MIN_RETRIEVAL_SCORE

scope = "EMT-B"  # or what the user gave
pages = scope_filter(load_pages(), scope)     # drops above-scope pages
ranked, mode, gate = rank(question, pages)    # keyword-only at small corpus
```

**Anti-hallucination gate:** if `gate < _MIN_RETRIEVAL_SCORE` (no real keyword
match), do **not** answer — reply exactly:

```
NOT IN PROVIDED PROTOCOLS
```

Otherwise build the context from the top pages:

```python
top = [p for p, _ in ranked[:5]]
context = build_context(top)
```

## 2. Answer from the context only (you do this)

Write a concise field answer using **only** `context`. Follow the same rules the
API prompt enforces:

1. **Cite every clinical claim** with a citation copied verbatim from the
   context — `[SOP-ID:Section]` or `[SRC-n:pNN]`. Never write a citation
   that isn't present in the context.
2. If the context doesn't contain the answer, reply exactly `NOT IN PROVIDED
   PROTOCOLS` — do not guess.
3. Flag any step above the provider's scope with `[OUT OF SCOPE for <scope>]`.
4. **Never invent** doses, drug names, or steps.
5. Be brief — field conditions don't allow long answers.

## 3. Verify your own citations (deterministic)

```python
from ems.query import verify_citations
answer, unverified = verify_citations(your_answer, context)
```

If `unverified` is non-empty, you cited something not in the context — **fix the
answer** (remove/correct those citations) and re-check before showing it.

## 4. Optionally save to the audit trail

If the user wants it saved:

```python
from ems.query import save_lookup, QueryResult
save_lookup(question, QueryResult(answer=answer, pages_used=tuple(p.slug for p in top),
            unverified_citations=tuple(unverified), mode=mode), scope)
```

## Wrap-up

Show the answer, the pages used, the retrieval mode, and the scope. If retrieval
was thin (few/no pages), say so plainly — the corpus grows as more sources are
ingested with `/ingest-source`.
