import re
from pathlib import Path
from typing import Optional

import yaml

from ems.config import (
    AUTO_LIST_FIELDS,
    SECTIONS_BY_PAGE_TYPE,
    TYPE_TO_DIR,
)
from ems.frontmatter import read_page
from ems.llm import call_llm
from ems.markdown import extract_wikilinks, replace_section
from ems.models import SourceSummary
from ems.paths import wiki_dir, wiki_subdir
from ems.prompts import patch_section_prompt

# Which SourceSummary field feeds which frontmatter list, per page type.
POPULATE_MAP = {
    "protocol": {
        "treats_conditions": "conditions_addressed",
        "medications": "medications_referenced",
    },
    "condition": {
        "red_flags": "red_flags_mentioned",
    },
}


# ── page discovery ───────────────────────────────────────────────────────────

def iter_page_paths() -> list[Path]:
    """All canonical wiki pages (the four page-type subdirs, excludes templates).

    Deliberately excludes wiki/scenarios/ — scenarios are training artifacts,
    not canonical pages, and have a different frontmatter shape.
    """
    pages = []
    for subdir in TYPE_TO_DIR.values():
        pages.extend(
            p for p in (wiki_dir() / subdir).glob("*.md") if p.name != "_template.md"
        )
    return pages


def find_page(slug: str) -> Optional[Path]:
    """Return the path to a page by slug, searching every page-type subdir."""
    for page_type in TYPE_TO_DIR:
        candidate = wiki_subdir(page_type) / f"{slug}.md"
        if candidate.exists():
            return candidate
    return None


def page_type_map() -> dict[str, str]:
    """Map every existing page slug to its page type."""
    return {path.stem: _dir_type(path) for path in iter_page_paths()}


def _dir_type(path: Path) -> str:
    from ems.config import DIR_TO_TYPE
    return DIR_TO_TYPE[path.parent.name]


def infer_page_type(slug: str, vocabulary: dict) -> str:
    """Best-effort page type for a slug that doesn't exist yet."""
    if slug.endswith("-protocol") or slug.endswith("-sop"):
        return "protocol"
    if slug in vocabulary.get("conditions", []):
        return "condition"
    if slug in vocabulary.get("medications", []):
        return "medication"
    if slug in vocabulary.get("procedures", []):
        return "procedure"
    return "protocol"


# ── page IO ──────────────────────────────────────────────────────────────────

def _write_page(path: Path, frontmatter: dict, body: str) -> None:
    fm_text = yaml.dump(
        frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False
    )
    if not body.startswith("\n"):
        body = "\n" + body
    path.write_text(f"---\n{fm_text}---{body}", encoding="utf-8")


def _title_from_slug(slug: str) -> str:
    return slug.replace("-", " ").title()


def create_page_from_template(slug: str, page_type: str) -> Path:
    """Create a new page from its type template with the title filled in."""
    subdir = wiki_subdir(page_type)
    subdir.mkdir(parents=True, exist_ok=True)
    template = subdir / "_template.md"
    fm, body = read_page(template)
    fm["title"] = _title_from_slug(slug)
    path = subdir / f"{slug}.md"
    _write_page(path, fm, body)
    return path


# ── content helpers ──────────────────────────────────────────────────────────

def strip_h2(text: str) -> str:
    """Remove any ## heading lines the LLM leaked into section-body output."""
    return "\n".join(
        line for line in text.splitlines() if not re.match(r"^##\s", line)
    ).strip()


def _merge(existing, incoming) -> list:
    """Union two lists preserving order (existing first)."""
    out = list(existing or [])
    for item in incoming or ():
        if item not in out:
            out.append(item)
    return out


def populate_relationships(
    frontmatter: dict, page_type: str, summary: SourceSummary
) -> None:
    """Merge the summary's conditions/medications/red-flags into the page's
    auto-populated frontmatter lists, per POPULATE_MAP. Mutates in place."""
    mapping = POPULATE_MAP.get(page_type, {})
    for field, summary_attr in mapping.items():
        frontmatter[field] = _merge(
            frontmatter.get(field), getattr(summary, summary_attr)
        )


def sync_linked_pages(frontmatter: dict, body: str) -> None:
    """Refresh linked_pages from [[wikilinks]] in the body. Mutates in place."""
    if "linked_pages" not in AUTO_LIST_FIELDS.get(frontmatter.get("type", ""), []):
        return
    frontmatter["linked_pages"] = _merge(
        frontmatter.get("linked_pages"), extract_wikilinks(body)
    )


def stamp_version(frontmatter: dict, page_type: str, summary: SourceSummary) -> None:
    """Stamp sop_id / effective_date from the summary when the page carries
    those fields and they're not already set. Mutates in place."""
    if "sop_id" in frontmatter and summary.sop_id and not frontmatter.get("sop_id"):
        frontmatter["sop_id"] = summary.sop_id
    if "effective_date" in frontmatter and summary.effective_date:
        frontmatter["effective_date"] = summary.effective_date


def supersede_prior_versions(current_path: Path, sop_id: str) -> list[str]:
    """Mark any other active protocol page sharing this sop_id as superseded.

    Returns the slugs that were superseded (empty if none). The current page's
    ``supersedes`` field is set to the sop_id it replaces.
    """
    if not sop_id:
        return []
    superseded: list[str] = []
    for path in iter_page_paths():
        if path == current_path:
            continue
        fm, _ = read_page(path)
        if fm.get("sop_id") == sop_id and fm.get("status") == "active":
            fm["status"] = "superseded"
            _, body = read_page(path)
            _write_page(path, fm, body)
            superseded.append(path.stem)

    if superseded:
        fm, body = read_page(current_path)
        fm["supersedes"] = sop_id
        _write_page(current_path, fm, body)
    return superseded


def _reembed(page_path: Path) -> None:
    """Re-embed a page's sections if the embeddings module exists (Phase 5).
    No-op — and never a hard dependency — until that module lands."""
    try:
        from ems import embeddings
    except ImportError:
        return
    embed = getattr(embeddings, "embed_sections", None)
    if embed is not None:
        embed(page_path)


# ── orchestration ────────────────────────────────────────────────────────────

def apply_agent_update(
    slug: str,
    section_content: dict[str, str],
    summary: SourceSummary,
    vocabulary: dict,
    source_kind: str = "sop",
    source_index: int = None,
    age_group: list[str] = None,
) -> Optional[Path]:
    """Persist already-written section content to a page — no LLM call.

    ``section_content`` maps ``## heading`` → finished section text (written by
    the caller: the ingest-source skill, or update_page after its LLM pass).
    Handles create-from-template, section replace, relationship/scope/version
    population, link sync, and re-embed.

    Returns None (skips) when resource content targets a protocol page —
    resource is reference material for condition/procedure pages only.
    """
    path = find_page(slug)
    if path is None:
        page_type = infer_page_type(slug, vocabulary)
        if source_kind == "resource" and page_type == "protocol":
            return None
        path = create_page_from_template(slug, page_type)
    else:
        page_type = _dir_type(path)
        if source_kind == "resource" and page_type == "protocol":
            return None

    fm, body = read_page(path)

    valid_sections = SECTIONS_BY_PAGE_TYPE[page_type]
    for heading, content in section_content.items():
        if heading not in valid_sections:
            continue
        body = replace_section(body, heading, strip_h2(content))

    # scope_level from summary — every ingested page must carry a valid scope.
    if not fm.get("scope_level"):
        fm["scope_level"] = summary.scope_level

    # age_group: only the values in the vocabulary, in canonical order.
    if age_group is not None:
        allowed = vocabulary.get("age_groups", [])
        fm["age_group"] = [a for a in allowed if a in set(age_group)]

    populate_relationships(fm, page_type, summary)
    stamp_version(fm, page_type, summary)
    sync_linked_pages(fm, body)
    if fm.get("status") == "draft":
        fm["status"] = "active"

    _write_page(path, fm, body)

    if page_type == "protocol":
        supersede_prior_versions(path, fm.get("sop_id") or "")

    _reembed(path)
    return path


def update_page(
    slug: str,
    sections: list[str],
    summary: SourceSummary,
    source_text: str,
    vocabulary: dict,
    llm=call_llm,
    source_kind: str = "sop",
    source_index: int = None,
) -> Optional[Path]:
    """Patch a page via the LLM (API path): draft each section with ``llm`` then
    persist through :func:`apply_agent_update`. Skills use apply_agent_update
    directly with agent-written content instead."""
    path = find_page(slug)
    page_type = infer_page_type(slug, vocabulary) if path is None else _dir_type(path)
    if source_kind == "resource" and page_type == "protocol":
        return None

    fm, body = read_page(path) if path else ({}, "")
    valid_sections = SECTIONS_BY_PAGE_TYPE[page_type]
    sop_id = (fm.get("sop_id") or summary.sop_id or "")

    section_content: dict[str, str] = {}
    for heading in sections:
        if heading not in valid_sections:
            continue
        prompt = patch_section_prompt(
            page_title=fm.get("title", slug),
            section_heading=heading,
            current_content=body_section_or_empty(body, heading),
            source_summary=summary.clinical_summary,
            source_text=source_text,
            sop_id=sop_id,
            source_kind=source_kind,
            source_index=source_index,
        )
        section_content[heading] = llm(prompt)

    return apply_agent_update(
        slug, section_content, summary, vocabulary, source_kind, source_index
    )


def body_section_or_empty(body: str, heading: str) -> str:
    from ems.markdown import get_section
    return get_section(body, heading) or ""
