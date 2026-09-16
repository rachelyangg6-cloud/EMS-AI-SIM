from pathlib import Path
from typing import Optional

import yaml

from ems.config import SCOPE_LEVELS
from ems.frontmatter import read_page
from ems.json_utils import parse_llm_json
from ems.llm import call_llm
from ems.models import Scenario
from ems.paths import scenarios_dir
from ems.prompts import scenario_generation_prompt
from ems.sim.difficulty import DIFFICULTY_LEVELS
from ems.tags import tags_for, valid_tags
from ems.vocabulary import load_vocabulary


def _clean_slugs(values, allowed: list[str]) -> tuple[str, ...]:
    allowed_set = set(allowed)
    seen: list[str] = []
    for v in values or []:
        if v in allowed_set and v not in seen:
            seen.append(v)
    return tuple(seen)


def _clean_age_group(value, allowed: list[str]) -> str:
    """A scenario carries exactly one life-stage tag; default to adult."""
    return value if value in set(allowed) else "adult"


def _to_scenario(data: dict, vocabulary: dict) -> Scenario:
    scope = data.get("scope_level")
    if scope not in SCOPE_LEVELS:
        scope = "EMT-B"
    return Scenario(
        dispatch=data.get("dispatch", "").strip(),
        presentation=data.get("presentation", "").strip(),
        vitals=data.get("vitals", "").strip(),
        correct_action_sequence=tuple(data.get("correct_action_sequence") or ()),
        scope_level=scope,
        rationale=data.get("rationale", "").strip(),
        age_group=_clean_age_group(data.get("age_group"), vocabulary.get("age_groups", [])),
        red_flags=tuple(data.get("red_flags") or ()),
        citations=tuple(data.get("citations") or ()),
        conditions=_clean_slugs(data.get("conditions"), vocabulary.get("conditions", [])),
        procedures=_clean_slugs(data.get("procedures"), vocabulary.get("procedures", [])),
        medications=_clean_slugs(data.get("medications"), vocabulary.get("medications", [])),
    )


def generate_scenarios(
    source_index: int,
    resource_text: str,
    vocabulary: dict,
    n: int = 10,
    llm=call_llm,
    dest_dir: Optional[Path] = None,
) -> list[Path]:
    """Generate n scenarios from a source and write one YAML+markdown file each.

    Files are numbered after any existing src{n}-s* files so re-runs never clobber
    already-labeled scenarios.
    """
    dest = dest_dir or scenarios_dir()
    dest.mkdir(parents=True, exist_ok=True)

    data = parse_llm_json(llm(scenario_generation_prompt(resource_text, source_index, vocabulary, n)))
    scenarios = [_to_scenario(s, vocabulary) for s in data.get("scenarios", [])]

    start = _next_index(dest, source_index)
    paths = []
    for i, scenario in enumerate(scenarios):
        paths.append(_write_scenario(scenario, source_index, start + i, dest))
    return paths


def _next_index(dest: Path, source_index: int) -> int:
    existing = list(dest.glob(f"src{source_index}-s*.md"))
    nums = []
    for p in existing:
        tail = p.stem.split("-s")[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return (max(nums) + 1) if nums else 1


def _write_scenario(
    scenario: Scenario, source_index: int, index: int, dest: Path,
    kind: str = "patient-care",
) -> Path:
    scenario_id = f"src{source_index}-s{index:02d}"
    frontmatter = {
        "type": "scenario",
        "scenario_id": scenario_id,
        "source_index": source_index,
        "kind": kind,                 # patient-care | provider-safety | operational | ...
        # What it is about, in the words someone would search for. Derived here
        # so a new scenario is never written without one; correct it by editing
        # the file, not the table it came from.
        "tags": tags_for({"source_index": source_index, "conditions": list(scenario.conditions)}),
        "scope_level": scenario.scope_level,
        "age_group": _clean_age_group(scenario.age_group, load_vocabulary().get("age_groups", [])),
        "status": "pending",          # pending | approved | rejected
        "labeled_by": "",
        "corrected": False,
        "correction_note": "",
        "conditions": list(scenario.conditions),
        "procedures": list(scenario.procedures),
        "medications": list(scenario.medications),
        "citations": list(scenario.citations),
    }
    fm_text = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)

    actions = "\n".join(f"{i}. {a}" for i, a in enumerate(scenario.correct_action_sequence, 1))
    red_flags = "\n".join(f"- {r}" for r in scenario.red_flags)
    related = " ".join(
        f"[[{slug}]]"
        for slug in (*scenario.conditions, *scenario.procedures, *scenario.medications)
    )

    body = f"""
## Dispatch
{scenario.dispatch}

## Presentation
{scenario.presentation}

## Vitals
{scenario.vitals}

## Correct actions
{actions}

## Rationale
{scenario.rationale}

## Red flags
{red_flags}

## Related
{related}
"""
    path = dest / f"{scenario_id}.md"
    path.write_text(f"---\n{fm_text}---\n{body}", encoding="utf-8")
    return path


def save_scenario(
    source_index: int, scenario: Scenario, kind: str = "patient-care",
    dest_dir: Optional[Path] = None,
) -> Path:
    """Write one agent-generated scenario as a pending file — no LLM call.

    Used by the generate-scenarios skill (the agent builds the Scenario, this
    persists it for review). ``kind`` records the scenario category
    (patient-care | provider-safety | operational | medical-legal | ...) so
    downstream stages can filter. Numbered after existing src{n}-s* files.
    """
    dest = dest_dir or scenarios_dir()
    dest.mkdir(parents=True, exist_ok=True)
    return _write_scenario(scenario, source_index, _next_index(dest, source_index), dest, kind)


# ── labeling (used by the /label-scenarios skill) ────────────────────────────

def author_scenario(
    source_index: int,
    scenario: Scenario,
    labeled_by: str,
    kind: str = "patient-care",
    dest_dir: Optional[Path] = None,
) -> Path:
    """Write an EMT-authored scenario, already approved (an expertise-marked fact).

    Used by the /label-scenarios skill when the reviewer adds a scenario the model
    didn't generate.
    """
    dest = dest_dir or scenarios_dir()
    dest.mkdir(parents=True, exist_ok=True)
    path = _write_scenario(scenario, source_index, _next_index(dest, source_index), dest, kind)
    save_label(path, status="approved", labeled_by=labeled_by)
    return path


def list_pending(
    dest_dir: Optional[Path] = None, source_index: Optional[int] = None
) -> list[Path]:
    """Scenario files still awaiting review (status: pending), in id order.

    Pass ``source_index`` to restrict to one source's queue.
    """
    dest = dest_dir or scenarios_dir()
    pattern = f"src{source_index}-s*.md" if source_index is not None else "src*-s*.md"
    pending = []
    for path in sorted(dest.glob(pattern)):
        fm, _ = read_page(path)
        if fm.get("status") == "pending":
            pending.append(path)
    return pending


def list_approved(
    dest_dir: Optional[Path] = None,
    source_index: Optional[int] = None,
    kind: Optional[str] = None,
    difficulty: Optional[str] = None,
    scope_level: Optional[str] = None,
    conditions: Optional[list[str]] = None,
) -> list[Path]:
    """Scenario files that are expertise-marked facts, in id order.

    An expertise-marked fact is ``status: approved`` with a non-empty
    ``labeled_by`` — the simulator only ever practices against these, never
    against pending or rejected drafts. Every filter is optional; ``conditions``
    matches a scenario carrying any of the given vocabulary slugs.
    """
    dest = dest_dir or scenarios_dir()
    pattern = f"src{source_index}-s*.md" if source_index is not None else "*.md"
    wanted = set(conditions or ())
    approved = []
    for path in sorted(dest.glob(pattern)):
        if path.name == "_template.md":
            continue
        fm, _ = read_page(path)
        if fm.get("status") != "approved" or not fm.get("labeled_by"):
            continue
        if kind is not None and fm.get("kind") != kind:
            continue
        if difficulty is not None and fm.get("difficulty") != difficulty:
            continue
        if scope_level is not None and fm.get("scope_level") != scope_level:
            continue
        if wanted and not wanted & set(fm.get("conditions") or ()):
            continue
        approved.append(path)
    return approved


def save_label(
    path: Path,
    status: str,
    labeled_by: str,
    correction_note: str = "",
    corrected: bool = False,
    new_body: Optional[str] = None,
    age_group: Optional[str] = None,
    difficulty: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> None:
    """Record a review decision (and optional corrected body) on a scenario.

    An approved scenario with labeled_by set is an expertise-marked fact.
    Pass ``age_group`` to correct the patient's life-stage tag during review,
    ``difficulty`` to override the auto-derived practice level, or ``tags`` to
    correct the topics it is filed under — the derived ones are a starting
    point, and the reviewer is the one who knows what the case is really about.
    """
    fm, body = read_page(path)
    fm["status"] = status
    fm["labeled_by"] = labeled_by
    fm["corrected"] = corrected
    fm["correction_note"] = correction_note
    if age_group is not None:
        fm["age_group"] = _clean_age_group(age_group, load_vocabulary().get("age_groups", []))
    if difficulty is not None:
        if difficulty not in DIFFICULTY_LEVELS:
            raise ValueError(f"difficulty must be one of {DIFFICULTY_LEVELS}; got {difficulty!r}")
        fm["difficulty"] = difficulty
    if tags is not None:
        unknown = sorted(set(tags) - valid_tags())
        if unknown:
            raise ValueError(
                f"not scenario_tags in system/source-vocabulary.json: {unknown}"
            )
        fm["tags"] = sorted(set(tags))
    if new_body is not None:
        body = new_body if new_body.startswith("\n") else "\n" + new_body

    fm_text = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    path.write_text(f"---\n{fm_text}---{body}", encoding="utf-8")
