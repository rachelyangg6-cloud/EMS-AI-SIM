from ems.config import SCOPE_LEVELS
from ems.json_utils import parse_llm_json
from ems.llm import call_llm
from ems.models import SourceSummary
from ems.prompts import summarize_source_prompt


def _clean_slugs(values, allowed: list[str]) -> tuple[str, ...]:
    """Keep only values that are in the approved vocabulary list, de-duplicated
    and order-preserving."""
    allowed_set = set(allowed)
    seen: list[str] = []
    for v in values or []:
        if v in allowed_set and v not in seen:
            seen.append(v)
    return tuple(seen)


def summarize(source_text: str, vocabulary: dict) -> SourceSummary:
    """Summarize a source document into a SourceSummary via the local LLM.

    Condition/medication slugs are filtered against the approved vocabulary so
    hallucinated tags never enter the graph. scope_level is validated against
    SCOPE_LEVELS, defaulting to the most restrictive (EMT-B) when invalid.
    """
    prompt = summarize_source_prompt(source_text, vocabulary)
    raw = call_llm(prompt)
    data = parse_llm_json(raw)

    scope = data.get("scope_level")
    if scope not in SCOPE_LEVELS:
        scope = "EMT-B"

    return SourceSummary(
        clinical_summary=data.get("clinical_summary", "").strip(),
        conditions_addressed=_clean_slugs(
            data.get("conditions_addressed"), vocabulary.get("conditions", [])
        ),
        red_flags_mentioned=tuple(data.get("red_flags_mentioned") or ()),
        medications_referenced=_clean_slugs(
            data.get("medications_referenced"), vocabulary.get("medications", [])
        ),
        scope_level=scope,
        sop_id=(data.get("sop_id") or None),
        effective_date=(data.get("effective_date") or None),
    )
