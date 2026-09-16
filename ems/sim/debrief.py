"""The narrative debrief — pros, cons, and exactly three improvements.

This sits on top of `ems.sim.grade`, which stays deterministic and LLM-free.
The split is the point: the score, the size-up checklist, the missed actions and
the critical errors are computed from EMT-vetted data and are already decided
before this module runs. The model writes the prose around that verdict; it
cannot change it, and a critical error it disagrees with stays a critical error.

**Citation enforcement.** Every clinical claim must carry a citation the
scenario actually has. `ems.query.verify_citations` reports any citation absent
from the scenario's own set, and a bullet carrying a fabricated one is dropped —
a plausible sentence with an invented source is worse than one fewer bullet, so
the debrief can come back with two improvements rather than three. `stripped`
records what was removed so the UI can say so out loud.
"""

import os
from functools import partial
from dataclasses import asdict, dataclass
from typing import Callable, Optional

from ems.config import SIM_GRADER_MODEL
from ems.json_utils import parse_llm_json
from ems.llm import INTERACTIVE_TIMEOUT, call_llm
from ems.markdown import get_section
from ems.query import verify_citations
from ems.sim.grade import Grade

#: Time-boxed: the trainee is on the debrief screen waiting for this.
_llm = partial(call_llm, timeout=INTERACTIVE_TIMEOUT)

#: The plan asks for exactly three actionable improvements.
WANTED_IMPROVEMENTS = 3


@dataclass(frozen=True)
class Debrief:
    """LLM narrative wrapped around a deterministic `Grade`."""
    scenario_id: str
    summary: str = ""
    pros: tuple[str, ...] = ()
    cons: tuple[str, ...] = ()
    improvements: tuple[str, ...] = ()
    #: Bullets removed because they cited a source the scenario does not have.
    stripped: tuple[str, ...] = ()
    #: Citations the model invented. Non-empty means the model tried.
    fabricated_citations: tuple[str, ...] = ()
    #: False when the corpus has no vetted answer key for this case (Project 9).
    emt_verified: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


_SYSTEM = (
    "You write the debrief after an EMT training call. You are given the "
    "scenario's vetted correct actions, its rationale, and a deterministic "
    "grade that has already been decided.\n\n"
    "The grade is not yours to revise. Do not argue with a critical error, "
    "do not re-score, and do not say a missed step was acceptable. Explain the "
    "grade to the trainee and tell them what to do differently.\n\n"
    "Every clinical claim you make must end with a citation copied exactly from "
    "the Citations list you are given. Do not invent, reformat, or guess a "
    "citation. If you cannot support a point with one of those citations, leave "
    "the point out.\n\n"
    "Be specific and behavioral: 'ventilate at 10 breaths per minute, just to "
    "chest rise' rather than 'improve your ventilation technique'.\n\n"
    'Reply with JSON only: {"summary": "one or two sentences", '
    '"pros": ["..."], "cons": ["..."], "improvements": ["...", "...", "..."]} — '
    f"exactly {WANTED_IMPROVEMENTS} improvements, each one thing the trainee "
    "can do on the next call."
)


def rubric(frontmatter: dict, body: str) -> str:
    """What the grader may see. Stable across trainees for the same scenario."""
    citations = "\n".join(f"- {c}" for c in (frontmatter.get("citations") or ()))
    return (
        f"## Correct actions\n{get_section(body, 'Correct actions') or ''}\n\n"
        f"## Rationale\n{get_section(body, 'Rationale') or ''}\n\n"
        f"## Red flags\n{get_section(body, 'Red flags') or ''}\n\n"
        f"## Citations you may use\n{citations}"
    )


def performance(grade: Grade) -> str:
    """The decided verdict, rendered for the grader to explain."""
    lines = [
        f"Result: {'PASS' if grade.passed else 'FAIL'} — "
        f"{grade.points} of {grade.points_possible} points",
        f"Scene size-up: {grade.size_up.score}/5 "
        f"(missed: {', '.join(grade.size_up.missed) or 'nothing'})",
        "",
        "Steps:",
    ]
    lines += [
        f"  {r.index}. [{r.status}] {r.action}" + (f"  ({r.note})" if r.note else "")
        for r in grade.actions
    ]
    if grade.critical_errors:
        lines.append("")
        lines.append("Critical errors (these stand — explain them, do not excuse them):")
        lines += [f"  - [{e.rule}] {e.detail}" for e in grade.critical_errors]
    if grade.red_flags_missed:
        lines.append("")
        lines.append(f"Red flags never named: {', '.join(grade.red_flags_missed)}")
    if grade.out_of_order:
        lines.append(f"\nSteps done out of sequence: {grade.out_of_order}")
    return "\n".join(lines)


def grade_llm(
    grade: Grade,
    frontmatter: dict,
    body: str,
    llm: Callable = _llm,
    model: Optional[str] = None,
    emt_verified: bool = True,
) -> Debrief:
    """Write the narrative debrief. The deterministic grade is authoritative."""
    context = rubric(frontmatter, body)
    raw = llm(
        f"{context}\n\n## How the trainee did\n{performance(grade)}",
        system=_SYSTEM,
        model=model or os.environ.get("EMS_GRADER_MODEL", SIM_GRADER_MODEL),
    )
    data = parse_llm_json(raw)

    allowed = "\n".join(frontmatter.get("citations") or ())
    pros, s1, f1 = _enforce(data.get("pros"), allowed)
    cons, s2, f2 = _enforce(data.get("cons"), allowed)
    improvements, s3, f3 = _enforce(data.get("improvements"), allowed)
    summary, s4, f4 = _enforce([str(data.get("summary", ""))], allowed)

    return Debrief(
        scenario_id=frontmatter.get("scenario_id", ""),
        summary=summary[0] if summary else "",
        pros=pros,
        cons=cons,
        improvements=improvements[:WANTED_IMPROVEMENTS],
        stripped=s1 + s2 + s3 + s4,
        fabricated_citations=tuple(sorted(set(f1 + f2 + f3 + f4))),
        emt_verified=emt_verified,
    )


def _enforce(bullets, allowed: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Split bullets into (kept, stripped, fabricated citations).

    A bullet citing a source the scenario does not have is dropped whole: the
    citation is the only thing making the claim checkable, so a bullet with a
    fake one is a claim with no provenance.
    """
    kept, stripped, fabricated = [], [], []
    for bullet in bullets or ():
        text = str(bullet).strip()
        if not text:
            continue
        _, unverified = verify_citations(text, allowed)
        if unverified:
            stripped.append(text)
            fabricated.extend(unverified)
        else:
            kept.append(text)
    return tuple(kept), tuple(stripped), tuple(fabricated)
