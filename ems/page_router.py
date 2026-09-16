import json

from ems.config import SECTIONS_BY_PAGE_TYPE
from ems.json_utils import parse_llm_json
from ems.llm import call_llm
from ems.models import RoutingResult, SourceSummary
from ems.page_updater import infer_page_type, page_type_map
from ems.prompts import route_source_prompt

# Every section heading that is valid for at least one page type.
_ALL_VALID_SECTIONS = {
    heading for headings in SECTIONS_BY_PAGE_TYPE.values() for heading in headings
}


def _valid_section(slug: str, section: str, types: dict[str, str]) -> bool:
    """A (page, section) pair is valid if the section is a real heading for the
    page's type. For pages that don't exist yet, accept any heading that is
    valid for some page type (page_updater re-validates against the real type)."""
    page_type = types.get(slug)
    if page_type:
        return section in SECTIONS_BY_PAGE_TYPE[page_type]
    return section in _ALL_VALID_SECTIONS


def route(
    summary: SourceSummary,
    vocabulary: dict,
    existing_pages: list[str] | None = None,
    llm=call_llm,
    source_kind: str = "sop",
) -> RoutingResult:
    """Route a source summary to target pages + sections via the local LLM.

    Invalid (page, section) pairs — sections that don't exist for the page's
    type — are dropped so the updater never patches a nonexistent section.
    """
    types = page_type_map()
    pages = existing_pages if existing_pages is not None else sorted(types)

    summary_json = json.dumps(
        {
            "clinical_summary": summary.clinical_summary,
            "conditions_addressed": list(summary.conditions_addressed),
            "medications_referenced": list(summary.medications_referenced),
            "scope_level": summary.scope_level,
            "sop_id": summary.sop_id,
        },
        indent=2,
    )

    data = parse_llm_json(llm(route_source_prompt(summary_json, pages, source_kind)))

    raw_pages = data.get("target_pages") or []
    raw_sections = data.get("sections") or []

    kept_pages: list[str] = []
    kept_sections: list[str] = []
    for slug, section in zip(raw_pages, raw_sections):
        if slug not in types:
            types[slug] = infer_page_type(slug, vocabulary)
        if _valid_section(slug, section, types):
            kept_pages.append(slug)
            kept_sections.append(section)

    return RoutingResult(
        target_pages=tuple(kept_pages),
        sections=tuple(kept_sections),
        reason=data.get("reason", "").strip(),
    )
