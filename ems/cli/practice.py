"""protocol-practice — play one approved scenario end to end in the terminal.

Text only, deterministic, no API key. Say "end of call" to finish and get the
graded debrief; an empty line does the same.
"""
import argparse
import os
import random
import sys
import textwrap
from datetime import date

from ems.paths import scenarios_dir
from ems.sim import persona, review
from ems.sim.generate import generated_dir, list_generated
from ems.sim.playable import playable_cases
from ems.sim import select
from ems.sim.grade import Grade
from ems.sim.hints import hint_for_session
from ems.sim.patterns import Conditions, fetch_live, season_for
from ems.sim.session import Session

_SPEAKER_LABEL = {
    "dispatcher": "DISPATCH",
    "narrator": "SCENE",
    "patient": "PATIENT",
    "sim": "SIM",
}

_SIZE_UP_LABEL = {
    "scene-safety": "scene safety",
    "bsi": "BSI / PPE",
    "patient-count": "number of patients",
    "moi-noi": "mechanism of injury / nature of illness",
    "additional-resources": "additional resources",
}


def _wrap(text: str, indent: str = "    ") -> str:
    return textwrap.fill(text, width=88, initial_indent=indent, subsequent_indent=indent)


def _conditions(args) -> Conditions:
    """Whatever the flags claim about today; otherwise today itself."""
    if not any((args.season, args.aqi, args.heat_index, args.flu)):
        return fetch_live()   # no-ops to the date unless EMS_LIVE_ENV=1
    return Conditions(
        season=args.season or season_for(date.today()),
        aqi=args.aqi,
        heat_index=args.heat_index,
        flu_season_peak=args.flu,
    )


def _persona_for(args):
    """The persona callable, or None for the deterministic sim.

    Checked up front rather than on the first reply: discovering a missing key
    four turns into a call costs the whole call.
    """
    if not args.personas:
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("--personas needs ANTHROPIC_API_KEY (a line in .env works).",
              file=sys.stderr)
        raise SystemExit(2)
    return persona.safe_speak


def _pick(args) -> "Session":
    if args.scenario:
        # Quarantine is searched too, so a draft can be played before it is
        # reviewed — which is the order the review loop needs. It stays out of
        # the random pool; naming it is the reviewer choosing to play it.
        for directory in (scenarios_dir(), generated_dir()):
            path = directory / f"{args.scenario}.md"
            if path.exists():
                return Session.from_path(path, persona=_persona_for(args))
        print(f"No scenario {args.scenario!r} in {scenarios_dir()} or {generated_dir()}",
              file=sys.stderr)
        raise SystemExit(2)

    if args.generated:
        pool = list_generated()
        if not pool:
            print(f"No drafts awaiting review in {generated_dir()}", file=sys.stderr)
            raise SystemExit(2)
        return Session.from_path(random.Random(args.seed).choice(pool),
                                 persona=_persona_for(args))

    pool = playable_cases(difficulty=args.level)
    if args.include_generated:
        # Opt-in, never the default: an unreviewed draft should not arrive
        # unannounced in the middle of ordinary practice.
        pool = sorted(set(pool) | set(list_generated()))
    if not pool:
        print(f"No playable scenarios at difficulty {args.level!r}", file=sys.stderr)
        raise SystemExit(2)
    # Same weighting the web app uses, so a smoke day is a smoke day in both.
    # No recency penalty here: the terminal has no user to have a history.
    path = select.select(pool, _conditions(args), rng=random.Random(args.seed))
    return Session.from_path(path or random.Random(args.seed).choice(pool),
                             persona=_persona_for(args))


def _print_debrief(grade: Grade) -> None:
    print("\n" + "=" * 88)
    print(f"DEBRIEF — {grade.scenario_id}    "
          f"{grade.points}/{grade.points_possible} points    "
          f"{'PASS' if grade.passed else 'FAIL'}")
    print("=" * 88)

    print(f"\nScene size-up: {grade.size_up.score}/5")
    for item in grade.size_up.covered:
        print(f"  [x] {_SIZE_UP_LABEL[item]}")
    for item in grade.size_up.missed:
        print(f"  [ ] {_SIZE_UP_LABEL[item]}  — not stated")

    print("\nCorrect actions:")
    mark = {"hit": "[x]", "partial": "[~]", "missed": "[ ]"}
    for result in grade.actions:
        print(f"  {mark[result.status]} {result.index}. {result.action}")
        if result.note:
            print(_wrap(f"↳ {result.note}", indent="      "))
    if grade.out_of_order:
        print(f"\n  {grade.out_of_order} step(s) were done out of sequence.")
    if grade.turns_to_first_intervention:
        print(f"  First intervention came on turn {grade.turns_to_first_intervention}.")

    if grade.critical_errors:
        print("\nCRITICAL:")
        for error in grade.critical_errors:
            print(_wrap(f"! [{error.rule}] {error.detail}", indent="  "))

    # Listed, not checked off. See the note in `ems/sim/grade.py`: catching one
    # meant saying it aloud, which is not what an EMT does with a finding.
    print("\nWhat this call turned on (not scored):")
    for flag in (*grade.red_flags_caught, *grade.red_flags_missed):
        print(f"  - {flag}")

    if grade.citations:
        print("\nSources: " + "  ".join(grade.citations))
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-practice",
        description="Play one approved scenario from tone-out to graded debrief.",
    )
    parser.add_argument(
        "--level", default="intermediate", choices=("basic", "intermediate", "expert"),
        help="Difficulty of the case to draw (default: intermediate)",
    )
    parser.add_argument("--scenario",
                        help="Play a specific scenario, e.g. src19-s02 or gen-20260818-01")
    parser.add_argument("--generated", action="store_true",
                        help="Play an unreviewed generated draft from quarantine")
    parser.add_argument("--include-generated", action="store_true",
                        help="Draw from vetted cases AND unreviewed drafts together")
    parser.add_argument("--hints", action=argparse.BooleanOptionalAction, default=None,
                        help="Show the next-step nudge each turn "
                             "(default: on at --level basic)")
    parser.add_argument("--personas", action="store_true",
                        help="Voice the dispatcher, the scene and the patient with "
                             "Claude (needs ANTHROPIC_API_KEY)")
    parser.add_argument("--review", action="store_true",
                        help="After the debrief, approve or reject a generated draft")
    parser.add_argument("--seed", type=int, help="Seed the random draw for a repeatable call")
    parser.add_argument("--season", choices=("winter", "spring", "summer", "fall"),
                        help="Practice a different season than today")
    parser.add_argument("--aqi", type=int, help="Force an air-quality index, e.g. 400")
    parser.add_argument("--heat-index", type=int, dest="heat_index")
    parser.add_argument("--flu", action="store_true", help="Force flu-season peak")
    args = parser.parse_args()

    session = _pick(args)
    # Proactive at Basic, on request otherwise — the policy hints.py describes.
    # Not tied to apprentice/certified: this CLI never opens the database and has
    # no user, and inventing an identity flag for the terminal would be real
    # complexity for nothing.
    show_hints = args.hints if args.hints is not None else args.level == "basic"

    print(f"\n{session.scenario_id}  ({session.difficulty or 'unrated'})")
    print("Say 'end of call' when you are finished. Empty line does the same.\n")

    while not session.done:
        if session.awaiting_input:
            # Under the prompt and above the cursor, which is where somebody who
            # is stuck is already looking. A category-level nudge, never the
            # rubric's own words — the same call the web app makes.
            if show_hints:
                nudge = hint_for_session(session)
                if nudge:
                    print(_wrap(f"hint: {nudge}", "  "))
            try:
                spoken = input("  EMT > ").strip()
            except EOFError:
                spoken = "end of call"
            event = session.step(spoken or "end of call")
        else:
            event = session.step()

        if event.awaiting_input:
            print(f"\n  {event.text}")
        elif event.text:
            print(f"\n{_SPEAKER_LABEL.get(event.speaker, event.speaker.upper())}")
            print(_wrap(event.text))

    _print_debrief(session.grade())
    if args.review:
        _review(session)
    return 0


def _review(session) -> None:
    """Approve or reject the draft that was just played, from the terminal.

    Only offers itself for a generated draft — a vetted case has nothing to
    promote. Reuses `ems.sim.review` verbatim, so the terminal and the browser
    reach the corpus through exactly one code path.
    """
    if session.scenario_path.parent != generated_dir():
        print("\nNothing to review — that was a vetted case.")
        return

    choice = input("\n[a]pprove  [r]eject  [s]kip > ").strip().lower()
    if not choice or choice.startswith("s"):
        return

    reviewer = input("Your name or initials: ").strip()
    if not reviewer:
        print("A review needs a name — it is the provenance stamp.")
        return

    rating = input("Realism 1-5 (enter to skip): ").strip()
    realism = int(rating) if rating.isdigit() and 1 <= int(rating) <= 5 else None

    if choice.startswith("a"):
        promoted = review.approve(session.scenario_path, labeled_by=reviewer,
                                  realism_rating=realism,
                                  realism_note=input("Note (optional): ").strip())
        print(f"  → promoted to {promoted.parent.name}/{promoted.name}")
        return

    critique = input("What is wrong with it? ").strip()
    if not critique:
        print("  skipped — a rejection with no critique teaches nothing")
        return
    review.reject(session.scenario_path, labeled_by=reviewer,
                  critique=critique, realism_rating=realism)
    print("  → kept in quarantine; critique added to the generation lessons")


if __name__ == "__main__":
    raise SystemExit(main())
