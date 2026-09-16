"""Aggregate counts over the wiki, for the Features page.

**Why this is its own module.** It is a pure function over files on disk, so it
can be tested against a fixture corpus without standing up FastAPI. `server.py`
only exposes it.

**What it may import is a hard constraint, not a preference.** The server runs
from a `.[web]` install — without sentence-transformers, and without
`system/embeddings.json` or `system/graph.yaml`. Importing `ems.query`,
`ems.embeddings` or `ems.graph` from here would drag PyTorch into a server that
has no use for it. A test asserts that none of the three is reachable from
this module.

It also stays clear of `ems.scenarios`, which pulls in `ems.llm` and the
Anthropic client to serve one dict lookup — and which lists only *approved*
scenarios, where this needs a single pass over every file to bucket approved,
rejected and pending together. The expertise-marked definition is duplicated
here instead, and a test pins it against `list_approved()` so the two cannot
drift apart silently.

**Difficulty is deliberately not reported.** 171 of the approved scenarios carry
no `difficulty` field at all, so any histogram would describe a level ladder
that does not exist. A test encodes the omission so it is not helpfully added
back before the underlying gap is fixed.
"""

import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Optional

from ems.config import (
    ANTHROPIC_MODEL,
    DIR_TO_TYPE,
    SIM_GRADER_MODEL,
    SIM_PERSONA_MODEL,
)
from ems.frontmatter import read_page
from ems.paths import scenarios_dir, system_dir, wiki_dir
from ems.tags import valid_tags

#: `[SRC-22:p660]`. Narrower than the citation pattern in `ems/query.py`
#: on purpose: that one recognizes any `[PREFIX:suffix]` so the engine can
#: verify whatever a page cites, while this counts resource page references
#: specifically, which is the number the page reports.
_SOURCE_CITATION = re.compile(r"\[([A-Z][A-Z0-9-]*):(p\d+)\]")

#: A lesson in generation-lessons.md is a top-level bullet.
_LESSON = re.compile(r"^- ", re.M)


def _pages(directory: Path):
    """Wiki markdown files, skipping the per-type `_template.md`."""
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.md")):
        if path.name != "_template.md":
            yield path


def _ranked(counter: Counter) -> dict:
    """Counter → plain dict, ordered high to low so the client need not sort."""
    return dict(counter.most_common())


def scenario_stats(directory: Optional[Path] = None) -> dict:
    """One pass over every scenario file, bucketing what the page reports."""
    directory = directory or scenarios_dir()
    # Drafts wait in a quarantine subdirectory until an EMT promotes them. They
    # are part of the corpus story, so they are counted — but never as approved.
    paths = list(_pages(directory)) + list(_pages(directory / "generated"))

    status, kinds, ages, tags = Counter(), Counter(), Counter(), Counter()
    marked = corrected = reviewed = 0

    for path in paths:
        fm, _ = read_page(path)
        status[str(fm.get("status", "unknown"))] += 1

        # Anyone's name on it means a person read it and made a decision —
        # including the rejections, which are the evidence that review is
        # capable of saying no.
        if fm.get("labeled_by"):
            reviewed += 1

        # The definition of record: approved *and* signed. `list_approved()`
        # requires both, and a status-only count would quietly include a
        # scenario nobody put their name to.
        approved = fm.get("status") == "approved" and bool(fm.get("labeled_by"))
        if not approved:
            continue

        marked += 1
        if fm.get("corrected") is True:
            corrected += 1
        kinds[str(fm.get("kind", "unspecified"))] += 1
        ages[str(fm.get("age_group", "unspecified"))] += 1
        tags.update(str(t) for t in (fm.get("tags") or ()))

    return {
        "total": len(paths),
        "reviewed": reviewed,
        "expertise_marked": marked,
        "corrected": corrected,
        "by_status": _ranked(status),
        "by_kind": _ranked(kinds),
        "by_age_group": _ranked(ages),
    }


def topic_stats(directory: Optional[Path] = None) -> dict:
    """Topic tags across the vetted corpus — the first reserved chart's data."""
    directory = directory or scenarios_dir()
    tags: Counter = Counter()
    for path in _pages(directory):
        fm, _ = read_page(path)
        if fm.get("status") == "approved" and fm.get("labeled_by"):
            tags.update(str(t) for t in (fm.get("tags") or ()))
    return {
        "vocabulary": len(valid_tags()),
        "used": len(tags),
        "assignments": sum(tags.values()),
        "by_topic": _ranked(tags),
    }


def page_stats(root: Optional[Path] = None) -> dict:
    """Canonical pages — conditions, procedures, medications, protocols.

    A type with no pages reports 0 rather than being omitted: `wiki/protocols/`
    holds only its template today, and a reader should be able to see that the
    slot exists and is empty rather than wonder whether it was counted.
    """
    root = root or wiki_dir()
    by_type: dict[str, int] = {}
    ages: Counter = Counter()
    total = 0

    for directory, page_type in sorted(DIR_TO_TYPE.items()):
        paths = list(_pages(root / directory))
        by_type[page_type] = len(paths)
        total += len(paths)

        for path in paths:
            fm, _ = read_page(path)
            for age in fm.get("age_group") or ():
                ages[str(age)] += 1

    return {
        "total": total,
        "by_type": by_type,
        "by_age_group": _ranked(ages),
    }


def citation_stats(wiki_root: Optional[Path] = None) -> dict:
    """Every resource reference in the corpus, from both places they live.

    Canonical pages carry citations inline in the body; scenarios carry them in
    a `citations:` frontmatter list. The two are different sets over the same
    resource, so neither alone is the "grounded in N sources" number — `distinct`
    is their union, and the per-area counts are reported beside it rather than
    instead of it.
    """
    wiki_root = wiki_root or wiki_dir()
    scenarios = wiki_root / "scenarios"

    page_refs: set[str] = set()
    case_refs: set[str] = set()
    occurrences = pages_cited = pages_total = 0

    for directory in sorted(DIR_TO_TYPE):
        for path in _pages(wiki_root / directory):
            pages_total += 1
            _, body = read_page(path)
            found = _SOURCE_CITATION.findall(body)
            occurrences += len(found)
            if found:
                pages_cited += 1
            page_refs |= {f"[{prefix}:{page}]" for prefix, page in found}

    cases_cited = cases_total = 0
    for path in _pages(scenarios):
        fm, _ = read_page(path)
        if fm.get("status") != "approved" or not fm.get("labeled_by"):
            continue
        cases_total += 1
        refs = {str(c) for c in (fm.get("citations") or ())}
        if refs:
            cases_cited += 1
        case_refs |= refs

    combined = page_refs | case_refs
    # The prefix is `SRC-22`, so distinct prefixes are distinct sources.
    sources = {m.group(1) for r in combined if (m := re.match(r"\[([A-Z][A-Z0-9-]*):", r))}

    return {
        "distinct": len(combined),
        "occurrences": occurrences,
        "sources_cited": len(sources),
        "pages_cited": pages_cited,
        "pages_total": pages_total,
        "pages_distinct": len(page_refs),
        "scenarios_cited": cases_cited,
        "scenarios_total": cases_total,
        "scenarios_distinct": len(case_refs),
    }


def source_stats(directory: Optional[Path] = None) -> dict:
    """Vetted scenarios per indexed source — how much of each resource is covered."""
    directory = directory or scenarios_dir()
    sources: Counter = Counter()
    for path in _pages(directory):
        fm, _ = read_page(path)
        if fm.get("status") != "approved" or not fm.get("labeled_by"):
            continue
        source_index = fm.get("source_index")
        if isinstance(source_index, int):
            sources[source_index] += 1
    return {
        "covered": len(sources),
        "by_source": {str(k): sources[k] for k in sorted(sources)},
    }


def lesson_count(root: Optional[Path] = None) -> int:
    """Rejections distilled into rules every later draft is generated against."""
    path = (root or system_dir()) / "generation-lessons.md"
    if not path.is_file():
        return 0
    return len(_LESSON.findall(path.read_text(encoding="utf-8")))


def _models() -> dict:
    """Which model does which job, read the way the callers read it.

    Served rather than written into the page so the copy cannot claim a model
    the server has stopped using — `EMS_PERSONA_MODEL` and `EMS_GRADER_MODEL`
    can override either simulator model at runtime.
    """
    return {
        "authoring": os.environ.get("ANTHROPIC_MODEL", ANTHROPIC_MODEL),
        "personas": os.environ.get("EMS_PERSONA_MODEL", SIM_PERSONA_MODEL),
        "grading": os.environ.get("EMS_GRADER_MODEL", SIM_GRADER_MODEL),
    }


def corpus_stats(
    wiki_root: Optional[Path] = None,
    system_root: Optional[Path] = None,
) -> dict:
    """Counts over the wiki. Pure and uncached — takes its roots explicitly.

    The caching lives in `cached_stats()` rather than here: a cache on a
    path-taking function would serve one test's `tmp_path` to the next.
    """
    wiki_root = wiki_root or wiki_dir()
    scenarios = wiki_root / "scenarios"

    pages = page_stats(wiki_root)
    cases = scenario_stats(scenarios)
    return {
        "pages": pages,
        "scenarios": cases,
        "topics": topic_stats(scenarios),
        "citations": citation_stats(wiki_root),
        "sources": source_stats(scenarios),
        "lessons": lesson_count(system_root),
        "models": _models(),
        "files": pages["total"] + cases["total"],
    }


@lru_cache(maxsize=1)
def cached_stats() -> dict:
    """`corpus_stats()` over the real corpus, computed once per process.

    A process-lifetime cache is correct here rather than merely fast: `wiki/` does
    not change under a running server in normal use. The consequence is that
    editing `wiki/` needs a server restart to show up — call
    `cached_stats.cache_clear()` if that matters.
    """
    return corpus_stats()
