"""Field-lookup query engine (Phase 3).

Safety-first retrieval over canonical wiki pages (scenarios are excluded):
keyword + optional vector/graph hybrid, scope filtering, a confidence gate that
refuses weak matches, cited synthesis via the Claude API, and post-generation
citation verification against the retrieved context.

At a small corpus (< _HYBRID_MIN_PAGES) retrieval runs keyword-only; vector and
graph layers switch on automatically as more sources are ingested.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import yaml

from ems.config import SCOPE_LEVELS
from ems.frontmatter import read_page
from ems.llm import call_llm, get_embedding
from ems.page_updater import iter_page_paths
from ems.paths import wiki_dir
from ems.prompts import query_prompt

_MIN_RETRIEVAL_SCORE = 3.0   # keyword-score gate: below this we refuse to answer
_HYBRID_MIN_PAGES = 30       # keyword-only below this corpus size
_KW_WEIGHT, _VEC_WEIGHT, _GRAPH_WEIGHT = 0.6, 0.3, 0.1
_TOP_K = 5

# Metadata list fields worth matching keywords against (2x weight).
_META_FIELDS = (
    "treats_conditions", "medications", "conditions", "procedures",
    "red_flags", "linked_pages", "sop_id", "age_group",
)
_WORD = re.compile(r"[a-z0-9]+")
# A citation is [PREFIX:suffix] with a colon; [Paramedic only] / [OUT OF SCOPE] have none.
_CITATION = re.compile(r"\[([A-Za-z0-9][\w\-]*:[^\]]+)\]")


@dataclass
class Page:
    slug: str
    type: str
    title: str
    scope_level: str
    status: str
    body: str
    frontmatter: dict


@dataclass
class QueryResult:
    answer: str
    pages_used: tuple[str, ...] = ()
    unverified_citations: tuple[str, ...] = ()
    mode: str = "keyword"       # keyword | hybrid | refused


# ── corpus loading ───────────────────────────────────────────────────────────

def load_pages() -> list[Page]:
    """All active canonical pages. Superseded pages are excluded (currency)."""
    pages = []
    for path in iter_page_paths():
        fm, body = read_page(path)
        if fm.get("status") == "superseded":
            continue
        pages.append(Page(
            slug=path.stem,
            type=fm.get("type", ""),
            title=fm.get("title", path.stem),
            scope_level=fm.get("scope_level", ""),
            status=fm.get("status", ""),
            body=body,
            frontmatter=fm,
        ))
    return pages


def _scope_rank(level: str) -> int:
    return SCOPE_LEVELS.index(level) if level in SCOPE_LEVELS else 0


def scope_filter(pages: list[Page], scope_level: str) -> list[Page]:
    """Drop pages above the provider's certification (EMT-B < AEMT < Paramedic)."""
    limit = _scope_rank(scope_level)
    return [p for p in pages if _scope_rank(p.scope_level) <= limit]


# ── search layers ────────────────────────────────────────────────────────────

def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _weighted_overlap(q: set[str], tokens: list[str]) -> int:
    counts = Counter(tokens)
    return sum(counts[t] for t in q)


def keyword_search(question: str, pages: list[Page]) -> list[tuple[Page, float]]:
    """Score pages by query-token overlap: title 3x, metadata 2x, body 1x."""
    q = set(_tokens(question))
    if not q:
        return []
    scored = []
    for p in pages:
        meta = " ".join(
            " ".join(map(str, v)) if isinstance(v, list) else str(v)
            for k in _META_FIELDS
            for v in [p.frontmatter.get(k)] if v
        )
        score = (
            3 * _weighted_overlap(q, _tokens(p.title))
            + 2 * _weighted_overlap(q, _tokens(meta))
            + 1 * _weighted_overlap(q, _tokens(p.body))
        )
        if score > 0:
            scored.append((p, float(score)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _vector_hits(question: str, pages: list[Page], embed: Callable) -> list[tuple[Page, float]]:
    from ems import embeddings
    by_slug = {p.slug: p for p in pages}
    best: dict[str, float] = {}
    for score, slug, _heading in embeddings.vector_search(question, embed=embed):
        if slug in by_slug:
            best[slug] = max(best.get(slug, 0.0), score)
    return [(by_slug[s], sc) for s, sc in best.items()]


def _graph_hits(seed_slugs: list[str], pages: list[Page]) -> list[tuple[Page, float]]:
    from ems import graph
    g = graph.get_or_build_graph()
    by_slug = {p.slug: p for p in pages}
    counts: Counter = Counter()
    for slug in seed_slugs:
        for nb in graph.get_related(g, slug):
            if nb in by_slug and nb not in seed_slugs:
                counts[nb] += 1
    return [(by_slug[s], float(c)) for s, c in counts.items()]


def _normalize(hits: list[tuple[Page, float]]) -> dict[str, float]:
    if not hits:
        return {}
    mx = max(s for _, s in hits) or 1.0
    return {p.slug: s / mx for p, s in hits}


def rank(question: str, pages: list[Page], embed: Callable = get_embedding):
    """Return (ranked_hits, mode, gate_score).

    ``gate_score`` is the top raw keyword score — the anti-hallucination gate is
    always lexical, so a query with no keyword anchor is refused regardless of mode.
    """
    kw = keyword_search(question, pages)
    gate = kw[0][1] if kw else 0.0

    if len(pages) < _HYBRID_MIN_PAGES:
        return kw, "keyword", gate

    by_slug = {p.slug: p for p in pages}
    kw_n = _normalize(kw)
    vec_n = _normalize(_vector_hits(question, pages, embed))
    graph_n = _normalize(_graph_hits([p.slug for p, _ in kw[:_TOP_K]], pages))
    combined = {
        slug: _KW_WEIGHT * kw_n.get(slug, 0.0)
        + _VEC_WEIGHT * vec_n.get(slug, 0.0)
        + _GRAPH_WEIGHT * graph_n.get(slug, 0.0)
        for slug in set(kw_n) | set(vec_n) | set(graph_n)
    }
    ranked = sorted(
        ((by_slug[s], sc) for s, sc in combined.items()),
        key=lambda x: x[1], reverse=True,
    )
    return ranked, "hybrid", gate


# ── synthesis ────────────────────────────────────────────────────────────────

def build_context(pages: list[Page]) -> str:
    blocks = []
    for p in pages:
        header = f"# {p.title} ({p.type}, scope: {p.scope_level})"
        sop = p.frontmatter.get("sop_id")
        if sop:
            header += f"  [sop_id: {sop}]"
        blocks.append(f"{header}\n{p.body.strip()}")
    return "\n\n---\n\n".join(blocks)


def _citations(text: str) -> set[str]:
    return set(_CITATION.findall(text))


def verify_citations(answer: str, context: str) -> tuple[str, list[str]]:
    """Return (answer, unverified) — citations in the answer absent from context."""
    known = _citations(context)
    return answer, sorted(_citations(answer) - known)


def answer_query(
    question: str,
    scope_level: str = "EMT-B",
    llm: Callable = call_llm,
    embed: Callable = get_embedding,
    save: bool = False,
) -> QueryResult:
    pages = load_pages()
    if scope_level:
        pages = scope_filter(pages, scope_level)

    ranked, mode, gate = rank(question, pages, embed=embed)
    if gate < _MIN_RETRIEVAL_SCORE:
        return QueryResult("NOT IN PROVIDED PROTOCOLS", mode="refused")

    top = [p for p, _ in ranked[:_TOP_K]]
    context = build_context(top)
    raw = llm(query_prompt(question, context, scope_level))
    answer, unverified = verify_citations(raw, context)

    result = QueryResult(
        answer=answer,
        pages_used=tuple(p.slug for p in top),
        unverified_citations=tuple(unverified),
        mode=mode,
    )
    if save:
        save_lookup(question, result, scope_level)
    return result


# ── audit trail ──────────────────────────────────────────────────────────────

def lookups_dir() -> Path:
    return wiki_dir() / "lookups"


def save_lookup(question: str, result: QueryResult, scope_level: str) -> Path:
    d = lookups_dir()
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:40] or "query"
    path = d / f"{ts}-{slug}.md"
    fm = {
        "type": "lookup",
        "question": question,
        "scope_level": scope_level,
        "date": date.today().isoformat(),
        "pages_used": list(result.pages_used),
        "unverified_citations": list(result.unverified_citations),
    }
    fm_text = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    path.write_text(
        f"---\n{fm_text}---\n\n## Question\n{question}\n\n## Answer\n{result.answer}\n",
        encoding="utf-8",
    )
    return path
