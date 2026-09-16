import sys
from dataclasses import dataclass, field
from pathlib import Path

from ems.frontmatter import read_page, write_frontmatter
from ems.index_log import append_log, regenerate_index
from ems.llm import call_llm
from ems.models import SourceMeta
from ems.page_router import route
from ems.page_updater import update_page
from ems.paths import raw_dir
from ems.source_summarizer import summarize
from ems.vocabulary import load_vocabulary


@dataclass
class IngestResult:
    source: str
    routed_pages: tuple[str, ...] = ()
    updated_pages: list[str] = field(default_factory=list)
    status: str = "ingested"     # "ingested" | "error"
    error: str = ""


def scan_new_sources() -> list[SourceMeta]:
    """Raw notes with ``status: new``, in filename order."""
    sources = []
    for path in sorted(raw_dir().glob("*.md")):
        fm, _ = read_page(path)
        if fm.get("status") == "new":
            sources.append(
                SourceMeta(path=path, status="new", filename=fm.get("filename", path.name))
            )
    return sources


def ingest_source(
    meta: SourceMeta,
    vocabulary: dict,
    dry_run: bool = False,
    show_steps: bool = False,
    llm=call_llm,
) -> IngestResult:
    """Run one source through summarize → route → update."""
    result = IngestResult(source=meta.path.stem)
    fm, body = read_page(meta.path)
    source_text = body.strip()
    source_kind = fm.get("source_kind", "sop")
    source_index = fm.get("source_index")

    def step(msg: str):
        if show_steps:
            print(f"  {msg}", file=sys.stderr)

    try:
        summary = summarize(source_text, vocabulary)
        step(f"summary: {summary.clinical_summary[:80]}")
        step(f"conditions={list(summary.conditions_addressed)} meds={list(summary.medications_referenced)} scope={summary.scope_level}")

        routing = route(summary, vocabulary, llm=llm, source_kind=source_kind)
        result.routed_pages = routing.target_pages
        step(f"routed → {list(routing.target_pages)} ({routing.reason})")

        if dry_run:
            return result

        # Group sections by page so each page is written once.
        sections_by_page: dict[str, list[str]] = {}
        for slug, section in zip(routing.target_pages, routing.sections):
            sections_by_page.setdefault(slug, []).append(section)

        for slug, sections in sections_by_page.items():
            updated = update_page(
                slug, sections, summary, source_text, vocabulary,
                llm=llm, source_kind=source_kind, source_index=source_index,
            )
            if updated is None:  # resource content skipped a protocol page
                step(f"skipped {slug} (protocol page, resource)")
                continue
            result.updated_pages.append(slug)
            step(f"updated {slug} ({', '.join(sections)})")

    except Exception as exc:  # noqa: BLE001 — record and continue to next source
        result.status = "error"
        result.error = str(exc)

    return result


def ingest(dry_run: bool = False, show_steps: bool = False, llm=call_llm) -> list[IngestResult]:
    """Scan raw/ for new sources and ingest each. On a real run, flips each
    source's status, logs it, and regenerates the index."""
    vocabulary = load_vocabulary()
    results: list[IngestResult] = []

    for meta in scan_new_sources():
        if show_steps:
            print(f"ingesting {meta.path.name}", file=sys.stderr)
        result = ingest_source(meta, vocabulary, dry_run, show_steps, llm=llm)
        results.append(result)

        if dry_run:
            continue

        fm, _ = read_page(meta.path)
        fm["status"] = result.status
        write_frontmatter(meta.path, fm)

        if result.status == "ingested":
            append_log(
                f"{meta.path.stem} → {', '.join(result.updated_pages) or '(no pages)'}"
            )
        else:
            append_log(f"{meta.path.stem} → ERROR: {result.error}")

    if not dry_run and any(r.status == "ingested" for r in results):
        regenerate_index()

    return results
