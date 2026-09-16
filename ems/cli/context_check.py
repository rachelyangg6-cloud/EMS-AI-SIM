"""protocol-context-check — find scenarios that give the trainee nothing to work with.

    protocol-context-check                 # everything that is thin
    protocol-context-check --source 16
    protocol-context-check --worst         # only the ones naming no person at all

A call is unrunnable when the dispatch does not say who the patient is or what is
wrong. The trainee arrives, asks the obvious questions, gets nothing back, and
has no thread to follow — the sim reads as broken when the scenario is simply
empty.

This only reports. Rewriting a dispatch is a clinical and editorial decision, so
the output is a worklist for `/label-scenarios`, not a patch.
"""
import argparse
import re
import sys

from ems.frontmatter import read_page
from ems.markdown import get_section
from ems.scenarios import list_approved

#: Someone is named — a life stage, an age, or at minimum a person.
_PERSON_RE = re.compile(
    r"\b(?:[\w-]{1,20}[-\s](?:year|month|week|day)[-\s]?old|\d{1,3}\s?(?:yo|y/o)\b"
    r"|infant|newborn|neonate|toddler|child|teen(?:ager)?|adolescent"
    r"|man|woman|male|female|adult|elderly|older adult|patient|boy|girl)\b",
    re.IGNORECASE,
)

#: A life stage or age specifically — "patient" alone does not tell you who.
_AGE_RE = re.compile(
    r"\b(?:[\w-]{1,20}[-\s](?:year|month|week|day)[-\s]?old|\d{1,3}\s?(?:yo|y/o)\b"
    r"|infant|newborn|neonate|toddler|child|teen(?:ager)?|adolescent"
    r"|elderly|older adult|geriatric)\b",
    re.IGNORECASE,
)

#: A sign, symptom or injury — the "what is wrong" half of a tone-out.
#: Derived from the words that actually appear in dispatches the checker already
#: passes, rather than from an invented clinical list.
#:
#: This is word matching, not comprehension: "no chest pain" contains "pain" and
#: will read as a complaint. That is the right failure direction for a lint —
#: passing a good dispatch matters more than catching every bad one.
_COMPLAINT_RE = re.compile(
    r"\b(?:pain|painful|hurts?|ache|aching"
    r"|breath|breathing|dyspnea|wheez\w*|chok\w*"
    r"|unresponsive|unconscious|responsive\w*|confus\w*|altered|collaps\w*"
    r"|faint\w*|syncop\w*|seizur\w*"
    r"|bleed\w*|blood|hemorrhag\w*|wound|burn\w*|injur\w*|trauma|fractur\w*"
    r"|deform\w*"
    r"|vomit\w*|nausea|diarrhea|dizz\w*|weak\w*|numb\w*|swell\w*|rash|hives"
    r"|allerg\w*"
    r"|overdose|poison\w*|ingest\w*|withdraw\w*"
    r"|cough\w*|fever|chills|sweat\w*|pale|cyanotic|clammy"
    r"|arrest|apneic|distress|attack|irrational\w*|agitat\w*"
    r"|sick|ill|labor|contraction\w*|pregnan\w*|deliver\w*)\b",
    re.IGNORECASE,
)

#: Words that describe a mechanism or a task rather than a patient's problem.
#: A dispatch made only of these tells you what happened, not who is hurt.
#:
#: Naming a mechanism is not itself a fault — most trauma tone-outs do, and
#: should. The fault is naming one *instead of* a complaint, so this pattern is
#: only half the test; see `problems`, which also requires that no complaint be
#: present. Matching on the mechanism alone flagged "Woman with chest pain after
#: a minor car crash" and even "unconscious adult; bystanders report no fall or
#: trauma", where the mechanism appears only to be ruled out.
_MECHANISM_ONLY_RE = re.compile(
    r"^(?:[^.]*\b(?:collision|crash|fall|fire|rescue|extrication|transfer|"
    r"handover|en route|already begun|two patients|multiple patients)\b[^.]*)\.?$",
    re.IGNORECASE,
)


def problems(frontmatter: dict, body: str) -> list[str]:
    dispatch = (get_section(body, "Dispatch") or "").strip()
    found = []
    if not dispatch:
        return ["no dispatch at all"]
    if not _PERSON_RE.search(dispatch):
        found.append("names no person")
    elif not _AGE_RE.search(dispatch):
        found.append("no age or life stage")
    if _MECHANISM_ONLY_RE.match(dispatch) and not _COMPLAINT_RE.search(dispatch):
        found.append("mechanism only, no complaint")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-context-check",
        description="Report patient-care scenarios whose dispatch gives the trainee nothing.",
    )
    parser.add_argument("--source", type=int)
    parser.add_argument("--worst", action="store_true",
                        help="Only those naming no person at all")
    args = parser.parse_args()

    rows, total = [], 0
    for path in list_approved():
        frontmatter, body = read_page(path)
        if frontmatter.get("kind") != "patient-care":
            continue
        if args.source and frontmatter.get("source_index") != args.source:
            continue
        total += 1
        found = problems(frontmatter, body)
        if args.worst:
            found = [f for f in found if f in ("names no person", "no dispatch at all")]
        if found:
            rows.append((path.stem, found, (get_section(body, "Dispatch") or "").strip()))

    for scenario_id, found, dispatch in rows:
        print(f"{scenario_id}  [{', '.join(found)}]\n    {dispatch}")

    if not rows:
        print("Every patient-care dispatch names a patient and a complaint.", file=sys.stderr)
        return 0
    print(f"\n{len(rows)} of {total} patient-care scenarios need a better dispatch.",
          file=sys.stderr)
    print("Rewriting one is a content decision — fix them in /label-scenarios.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
