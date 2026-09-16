"""Section-level vector index for semantic retrieval (Phase 5).

Embeddings are local (`sentence-transformers`, no API). The index is only
maintained once it has been explicitly built with :func:`build_embedding_index`;
:func:`embed_sections` (called from the page updater during ingest) is a no-op
until then, so ingest stays fast and fully offline until vector search is wanted.
"""
import json
import math
from pathlib import Path
from typing import Callable

from ems.config import DEFAULT_EMBEDDING_MODEL
from ems.frontmatter import read_page
from ems.llm import get_embedding
from ems.markdown import extract_h2_headings, get_section
from ems.page_updater import iter_page_paths
from ems.paths import embeddings_path


def index_exists() -> bool:
    return embeddings_path().exists()


def _iter_sections(path: Path):
    """Yield (heading, text) for each non-empty ## section of a page."""
    _fm, body = read_page(path)
    for heading in extract_h2_headings(body):
        text = (get_section(body, heading) or "").strip()
        if text:
            yield heading, text


def _entry(slug: str, ptype: str, title: str, heading: str, text: str,
           embed: Callable, age: str = "") -> dict:
    prefix = f"[{age}] " if age else ""
    return {
        "slug": slug,
        "type": ptype,
        "heading": heading,
        "vector": embed(f"{prefix}{title} — {heading}\n{text}"),
    }


def _age_str(fm: dict) -> str:
    """Page-level age_group list rendered for embedding text (empty if unset)."""
    return " ".join(fm.get("age_group") or [])


def build_embedding_index(force: bool = False, embed: Callable = get_embedding) -> dict:
    """Embed every section of every canonical page. Returns the index dict."""
    if index_exists() and not force:
        return load_index()
    sections = []
    for page in iter_page_paths():
        fm, _ = read_page(page)
        title = fm.get("title", page.stem)
        age = _age_str(fm)
        for heading, text in _iter_sections(page):
            sections.append(_entry(page.stem, fm.get("type", ""), title, heading, text, embed, age))
    index = {"model": DEFAULT_EMBEDDING_MODEL, "sections": sections}
    _write_index(index)
    return index


def embed_sections(page_path: Path, embed: Callable = get_embedding) -> None:
    """Incrementally re-embed one page's sections (called by the page updater).

    No-op unless an index already exists — the index is opt-in via
    build_embedding_index, so ingest never forces a model load.
    """
    if not index_exists():
        return
    index = load_index()
    slug = page_path.stem
    index["sections"] = [s for s in index["sections"] if s["slug"] != slug]
    fm, _ = read_page(page_path)
    title = fm.get("title", slug)
    age = _age_str(fm)
    for heading, text in _iter_sections(page_path):
        index["sections"].append(_entry(slug, fm.get("type", ""), title, heading, text, embed, age))
    _write_index(index)


def vector_search(question: str, embed: Callable = get_embedding, top_k: int = 10) -> list[tuple]:
    """Return [(cosine_score, slug, heading), ...] best-first. Empty if no index."""
    if not index_exists():
        return []
    index = load_index()
    qv = embed(question)
    scored = [(_cosine(qv, s["vector"]), s["slug"], s["heading"]) for s in index["sections"]]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]


def index_stats() -> dict:
    if not index_exists():
        return {"model": None, "sections": 0, "pages": 0}
    index = load_index()
    return {
        "model": index.get("model"),
        "sections": len(index["sections"]),
        "pages": len({s["slug"] for s in index["sections"]}),
    }


def load_index() -> dict:
    return json.loads(embeddings_path().read_text(encoding="utf-8"))


def _write_index(index: dict) -> None:
    path = embeddings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index), encoding="utf-8")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
