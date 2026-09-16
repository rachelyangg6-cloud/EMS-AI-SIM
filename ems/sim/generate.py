"""Draft new practice calls from the vetted wiki — grounded, gated, unapproved.

The corpus is 196 approved scenarios and only 95 of them can actually be played
as a call. Hand-writing more is slow; generating more is fast and worthless
unless two things hold.

**A model never authors clinical truth.** Everything written here lands in
``wiki/scenarios/generated/`` as ``status: pending`` with ``origin: generated``.
That directory is not `scenarios_dir()`, so `list_approved` cannot see it and the
simulator cannot deal it. A generated call becomes a fact only when an EMT
reviews it and `ems.sim.review` promotes it — the same `save_label` path the
source scenarios go through.

**A draft that cannot be played is not saved at all.** Every candidate goes
through `ems.sim.playable.unplayable` before it touches disk, plus the checks
that come from real sessions: full numeric vitals, and an oxygen order that names
both a device and a flow rate. A failure is retried, then reported — never
written. Generating more of the 101 unplayable cases would be worse than
generating nothing.

Grounding is the wiki itself. Pages are retrieved for the seed conditions, the
prompt may cite only those pages, and any citation the model invents is removed
before the file is written. `ems.query.verify_citations` *reports* unsupported
citations rather than removing them — it is written for the debrief, where the
answer is shown to a reviewer alongside the warning — so the removal happens
here. A fabricated citation left in place is worse than no citation, because it
reads as sourced.

**No Anthropic API.** Like `generate-scenarios` and `ingest-source`, the drafting
is done by the agent reading the retrieved pages and writing the call — see the
`generate-case` skill. This module is the deterministic half: it retrieves the
grounding, gates the result, and writes it. `draft_from_text` is the entry point
for that flow.

`draft` — which takes an LLM callable and loops — remains for a headless run
(a nightly batch, a CI smoke test) and is what the tests drive with a stub. Both
paths go through the same `inspect_draft` gate, so neither can save something the
other would reject.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Optional, Sequence

from ems.frontmatter import read_page, write_frontmatter
from ems.llm import call_llm
from ems.markdown import get_section
from ems.paths import scenarios_dir, system_dir
from ems.query import load_pages, rank, verify_citations
from ems.sim.intents import (DEVICE_FLOW_RANGE, classify, flow_rate,
                             is_prohibition, named_device)
from ems.sim.playable import unplayable
from ems.tags import tags_for

#: Quarantine. Deliberately *not* `scenarios_dir()` — nothing here is approved,
#: and `list_approved` must not be able to reach it.
def generated_dir() -> Path:
    return scenarios_dir() / "generated"


def lessons_path() -> Path:
    return system_dir() / "generation-lessons.md"


#: How many pages of wiki context the prompt carries. Enough to ground the
#: clinical content, few enough that the model is not choosing between sources.
_CONTEXT_PAGES = 6

#: Attempts before giving up. Three is enough to clear a one-off formatting slip
#: without burning tokens on a prompt that is fundamentally not working.
_MAX_ATTEMPTS = 3

_SECTIONS = (
    "Dispatch", "Presentation", "Vitals", "Correct actions",
    "Rationale", "Red flags",
)

_SYSTEM = (
    "You draft practice calls for EMT trainees, working strictly from the "
    "reference pages you are given. You never invent a dose, a step, or a "
    "clinical fact that is not in those pages. Every line of '## Correct "
    "actions' ends with a citation copied exactly from the pages — if you "
    "cannot support a step with one of them, leave the step out."
)


@dataclass(frozen=True)
class Draft:
    """One generated candidate and everything known about it."""
    body: str
    conditions: tuple[str, ...] = ()
    pages_used: tuple[str, ...] = ()
    stripped_citations: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    @property
    def playable(self) -> bool:
        return not self.problems


@dataclass
class GenerationFailed(Exception):
    """Every attempt produced something unplayable. Nothing was written."""
    attempts: int
    problems: tuple[str, ...] = ()
    last_body: str = ""

    def __str__(self) -> str:
        return (
            f"{self.attempts} attempts, none playable. Last: "
            + "; ".join(self.problems)
        )


# ── grounding ────────────────────────────────────────────────────────────────

def context_for(conditions: Sequence[str], limit: int = _CONTEXT_PAGES) -> tuple[str, tuple[str, ...]]:
    """Wiki pages for these conditions, as prompt context plus the slugs used."""
    pages = load_pages()
    question = " ".join(conditions) or "emergency patient assessment"
    # `rank` returns (hits, mode, gate_score), not the hits alone.
    hits, _mode, _gate = rank(question, pages)
    ranked = hits[:limit]
    used = tuple(page.slug for page, _ in ranked)
    context = "\n\n".join(
        f"### {page.title} ({page.slug})\n{page.body}" for page, _ in ranked
    )
    return context, used


def load_lessons(path: Optional[Path] = None) -> str:
    """Accumulated realism failures, distilled from rejected drafts.

    This is the flywheel. A rejection is not discarded — its critique becomes a
    line here, and this file is in the prompt for every later generation.
    """
    path = path or lessons_path()
    return path.read_text(encoding="utf-8") if path.exists() else ""


def exemplars(limit: int = 2) -> str:
    """Approved calls that play well, as few-shot examples of the right shape."""
    from ems.sim.playable import playable_cases

    chosen = sorted(playable_cases())[-limit:]
    return "\n\n".join(
        f"### {path.stem}\n{read_page(path)[1].strip()}" for path in chosen
    )


# ── the checks a draft has to clear ──────────────────────────────────────────

_NUMBER_RE = re.compile(r"\d")


def vitals_problems(body: str) -> list[str]:
    """Every scenario needs a full numeric set — the monitor renders from it."""
    vitals = (get_section(body, "Vitals") or "").lower()
    if not vitals.strip():
        return ["vitals section is empty"]
    missing = [
        name for name, pattern in (
            ("a respiratory rate", r"\brr\b|respirat"),
            ("a pulse", r"\bpulse\b|\bhr\b"),
            ("an SpO2", r"spo2|sao2|saturation"),
            ("a blood pressure", r"\bbp\b|blood pressure|\d{2,3}/\d{2,3}"),
        )
        if not re.search(pattern, vitals)
    ]
    if not _NUMBER_RE.search(vitals):
        missing.append("any number at all")
    return [f"vitals state no {name}" for name in missing]


def oxygen_problems(body: str) -> list[str]:
    """Rachel's standing rule: every oxygen order names a device AND a rate."""
    problems = []
    for line in re.findall(r"^\d+\.\s+(.*)$", get_section(body, "Correct actions") or "",
                           re.MULTILINE):
        intents = classify(line)
        if "oxygen" not in intents:
            continue
        device = named_device(intents)
        if device is None:
            problems.append(f"oxygen step names no device: {line[:60]!r}")
            continue
        rate = flow_rate(line)
        if rate is None:
            problems.append(f"oxygen step names no flow rate: {line[:60]!r}")
            continue
        low, high = DEVICE_FLOW_RANGE[device]
        if not low <= rate <= high:
            problems.append(
                f"{device.removeprefix('oxygen-').upper()} at {rate:g} L/min is "
                f"outside {low}-{high}"
            )
    return problems


def structure_problems(body: str) -> list[str]:
    return [f"no ## {name} section" for name in _SECTIONS if not get_section(body, name)]


def rubric_problems(body: str) -> list[str]:
    """Steps the grader will not be able to see.

    A numbered step that carries no intent is graded on bare word overlap and
    can never be surfaced as a hint, so it is a step in name only. Almost always
    it is commentary that wandered into the answer key — "Do not delay
    epinephrine to finish the history", "Be prepared to give a second dose" — or
    a real action buried behind a reason: "Ensure a safe scene, because patients
    with diabetic emergencies can be agitated" matches nothing at all.

    Both shapes were found by a reviewer playing a draft and being marked down
    for steps they had performed. Advice in the skill did not stop me writing
    them, so the gate refuses them instead.
    """
    from ems.sim.grade import parse_actions

    from ems.sim.grade import TIME_CRITICAL_INTENTS

    actions = parse_actions(body)
    problems = []
    for index, line in enumerate(actions, 1):
        # A "Do NOT …" line carries no intent by design: it is scored inverted,
        # the EMT passing it by *not* doing the thing. 39 lines in the corpus
        # are this shape, and refusing them would have been the gate rejecting
        # the one kind of step it already grades correctly.
        if classify(line) or is_prohibition(line):
            continue
        opening = line.lower()[:40]
        problems.append(
            f"step {index} carries no action the grader can see "
            f"— rewrite it as something the EMT would say: {opening!r}"
        )

    # Ordering is expressed by the numbering, so the numbering has to be right.
    # A treatment that stops being correct when it happens late must not be
    # listed after the paperwork: the grader reads the sequence literally, and
    # an answer key that puts the history first is teaching the wrong call.
    signatures = [frozenset(classify(line)) for line in actions]
    LATER = frozenset({"sample-history", "documentation", "physical-exam", "opqrst"})
    #: A treatment that is being *withheld* carries the same intent as giving
    #: it, and none of the urgency — "withhold the autoinjector" is a decision
    #: not to act, so it does not have to precede the history.
    WITHHELD = re.compile(
        r"\b(withhold|do not (give|administer)|does not (need|require)|"
        r"defer|hold off|avoid giving)\b",
        re.IGNORECASE,
    )
    for index, sig in enumerate(signatures, 1):
        urgent = sig & TIME_CRITICAL_INTENTS
        if not urgent or WITHHELD.search(actions[index - 1]):
            continue
        # Only the *first* step of its kind. A second epinephrine dose two
        # minutes after the first is meant to come after documenting the first,
        # and flagging it made a correctly ordered call look wrong.
        if any(other_sig & urgent for other_sig in signatures[: index - 1]):
            continue
        earlier = [
            other + 1 for other, other_sig in enumerate(signatures[: index - 1])
            # Only a step that does *nothing but* gather information. Assessing
            # before treating is correct — "confirm epinephrine is indicated"
            # reads as history but is the indication check, and flagging it made
            # the rule fire on every properly ordered call.
            if other_sig and other_sig <= LATER
        ]
        if earlier:
            problems.append(
                f"step {index} treats an immediate threat but is numbered after "
                f"step {earlier[0]}, which gathers information — put the "
                f"time-critical step first, because the numbering is the order"
            )
    return problems


def inspect_draft(body: str, frontmatter: dict) -> tuple[str, ...]:
    """Everything wrong with this candidate. Empty means it can be saved."""
    problems = structure_problems(body)
    if problems:
        # The playability and content checks read sections that are not there
        # yet; reporting "no ## Vitals" twice helps nobody.
        return tuple(problems)
    return tuple(
        [*unplayable(frontmatter, body), *vitals_problems(body),
         *oxygen_problems(body), *rubric_problems(body)]
    )


def strip_unsupported_citations(body: str, context: str) -> tuple[str, list[str]]:
    """Remove citations the retrieved pages do not contain, and report them.

    `verify_citations` only reports — it is built for the debrief, where the text
    is shown to a reviewer next to the warning. Here nobody sees the warning
    before the file is written, and a fabricated citation reads as provenance, so
    it comes out.
    """
    _, unsupported = verify_citations(body, context)
    for citation in unsupported:
        # `_citations` yields the id without its brackets, so the brackets have
        # to be matched here — removing the id alone leaves a bare "[]" behind,
        # which looks like a citation that failed to render rather than one that
        # was never real.
        body = re.sub(rf"\s*\[{re.escape(citation)}\]", "", body)
    # A stripped trailing citation can leave a double space or a floating stop.
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = re.sub(r"[ \t]+([.,;])", r"\1", body)
    return body.strip(), unsupported


# ── drafting ─────────────────────────────────────────────────────────────────

def draft_from_text(
    body: str,
    conditions: Sequence[str],
    pages_used: Sequence[str] = (),
    context: str = "",
) -> Draft:
    """Gate a call the agent wrote, without calling any API.

    The path the `generate-case` skill uses. The agent has read the retrieved
    pages and written the six sections; this checks them exactly as the headless
    path is checked, and reports what is wrong rather than raising — the agent
    can fix a dispatch and try again in the same turn, which no retry loop does
    as well.

    `context` is optional and only used to strip unsupported citations. Pass the
    text from `context_for` to get that check; leave it out to skip it.
    """
    stripped: list[str] = []
    if context:
        body, stripped = strip_unsupported_citations(body, context)
    frontmatter = {"kind": "patient-care", "origin": "generated"}
    return Draft(
        body=body.strip(),
        conditions=tuple(conditions),
        pages_used=tuple(pages_used),
        stripped_citations=tuple(stripped),
        problems=inspect_draft(body, frontmatter),
    )


def build_prompt(conditions: Sequence[str], context: str, lessons: str, shots: str,
                 retry_note: str = "") -> str:
    parts = [
        "Draft ONE practice call for an EMT trainee.",
        "",
        "## Reference pages — the only source you may use",
        context,
        "",
        "## The shape it must take",
        shots,
        "",
        "## Rules",
        "- `## Dispatch` names the patient (age or life stage) AND the complaint. "
        "It is read aloud as a radio tone-out: \"62-year-old man, chest pain and "
        "short of breath, conscious and alert.\"",
        "- `## Presentation` is what you see on ARRIVAL, in the third person. "
        "Never \"You are...\" — that is a teaching frame and cannot be narrated.",
        "- `## Vitals` states RR, pulse, SpO2 and BP as numbers, consistent with "
        "the condition. An SpO2 of 97% alongside severe distress teaches the "
        "wrong reflex.",
        "- Every `## Correct actions` line ends with a citation copied exactly "
        "from the reference pages.",
        "- Every oxygen step names the device AND the flow rate: nasal cannula "
        "2-6 L/min, nonrebreather 12-15 L/min, BVM 15 L/min with a reservoir.",
        "- US English spelling throughout.",
        "",
        f"## Conditions to build the call around\n{', '.join(conditions)}",
    ]
    if lessons.strip():
        parts += ["", "## Realism failures found in earlier drafts — do not repeat these",
                  lessons.strip()]
    if retry_note:
        parts += ["", "## Your previous attempt was rejected", retry_note]
    parts += [
        "",
        "Output the scenario body only: the six `## ` sections in the order "
        "shown, no frontmatter, no preamble.",
    ]
    return "\n".join(parts)


def draft(
    conditions: Sequence[str],
    llm: Callable[..., str] = call_llm,
    max_attempts: int = _MAX_ATTEMPTS,
    context: Optional[str] = None,
    pages_used: Sequence[str] = (),
    lessons: Optional[str] = None,
) -> Draft:
    """Draft one playable call, or raise `GenerationFailed` having written nothing.

    Retries feed the previous attempt's problems back into the prompt, because
    the failures are specific and legible ("dispatch names no person") and a
    blind retry wastes the information.
    """
    if context is None:
        context, pages_used = context_for(conditions)
    if lessons is None:
        lessons = load_lessons()
    shots = exemplars()

    problems: tuple[str, ...] = ()
    body = ""
    retry_note = ""
    for attempt in range(1, max_attempts + 1):
        prompt = build_prompt(conditions, context, lessons, shots, retry_note)
        body = llm(prompt, system=_SYSTEM).strip()
        body, stripped = strip_unsupported_citations(body, context)

        frontmatter = {"kind": "patient-care", "origin": "generated"}
        problems = inspect_draft(body, frontmatter)
        if not problems:
            return Draft(
                body=body,
                conditions=tuple(conditions),
                pages_used=tuple(pages_used),
                stripped_citations=tuple(stripped),
                problems=(),
            )
        retry_note = "\n".join(f"- {p}" for p in problems)

    raise GenerationFailed(attempts=max_attempts, problems=problems, last_body=body)


# ── writing it out ───────────────────────────────────────────────────────────

def next_id(dest: Optional[Path] = None, today: Optional[date] = None) -> str:
    dest = dest or generated_dir()
    stamp = (today or date.today()).strftime("%Y%m%d")
    existing = sorted(dest.glob(f"gen-{stamp}-*.md")) if dest.exists() else []
    return f"gen-{stamp}-{len(existing) + 1:02d}"


#: `[SRC-30:p872]`, as the rubric steps carry it.
_CITATION = re.compile(r"\[SRC-\d+:p\d+\]")


def citations_in(body: str) -> list[str]:
    """Every distinct resource citation in the body, in the order it appears."""
    seen: dict[str, None] = {}
    for citation in _CITATION.findall(body):
        seen.setdefault(citation, None)
    return list(seen)


def _with_related(body: str, conditions) -> str:
    """Append the `## Related` section a scenario is required to carry.

    `_write_scenario` has always written one and this path never did, so a
    promoted draft was missing a required section. The wikilinks are what tie a
    case back to the pages it was drafted from.
    """
    body = body.strip()
    if "## Related" in body:
        return body + "\n"
    links = " ".join(f"[[{slug}]]" for slug in conditions)
    return f"{body}\n\n## Related\n{links}\n"


def save_draft(
    draft_: Draft,
    dest: Optional[Path] = None,
    today: Optional[date] = None,
    difficulty: str = "intermediate",
) -> Path:
    """Write a playable draft to quarantine. Refuses anything else."""
    if not draft_.playable:
        raise ValueError(f"refusing to save an unplayable draft: {'; '.join(draft_.problems)}")

    dest = dest or generated_dir()
    dest.mkdir(parents=True, exist_ok=True)
    scenario_id = next_id(dest, today)
    path = dest / f"{scenario_id}.md"
    path.write_text(_with_related(draft_.body, draft_.conditions), encoding="utf-8")
    write_frontmatter(path, {
        "type": "scenario",
        "scenario_id": scenario_id,
        "kind": "patient-care",
        # A draft belongs to no source — it is grounded in wiki pages, which is
        # why `source_index` is absent here and why this field exists. Derived from
        # the conditions it was drafted from; the reviewer can correct it.
        "tags": tags_for({"conditions": list(draft_.conditions)}),
        # The whole point: pending, unattributed, and marked as machine-drafted.
        "status": "pending",
        "labeled_by": "",
        "origin": "generated",
        "generated_from": list(draft_.conditions),
        "pages_used": list(draft_.pages_used),
        "difficulty": difficulty,
        "scope_level": "EMT-B",
        "corrected": False,
        "correction_note": "",
        "conditions": list(draft_.conditions),
        "procedures": [],
        "medications": [],
        # Lifted out of the body rather than left empty. The steps carry their
        # citations inline and always did; leaving the field blank meant a
        # promoted draft looked uncited to every tool that reads frontmatter,
        # including the schema check that says an approved scenario must have
        # at least one.
        "citations": citations_in(draft_.body),
    })
    return path


def list_generated(dest: Optional[Path] = None, status: str = "pending") -> list[Path]:
    """Drafts of `status`, unseen ones first.

    A reviewer who sets a draft aside should not be handed it again before
    everything else has had a turn, so anything carrying `deferred_at` sorts
    behind everything that does not. Within each group the order is by id,
    which is the date — oldest draft first.
    """
    dest = dest or generated_dir()
    if not dest.exists():
        return []
    matching = [
        path for path in dest.glob("gen-*.md")
        if read_page(path)[0].get("status") == status
    ]
    return sorted(
        matching,
        key=lambda path: (
            str(read_page(path)[0].get("deferred_at") or ""),
            path.name,
        ),
    )
