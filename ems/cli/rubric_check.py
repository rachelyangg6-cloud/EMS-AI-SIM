"""Report ``## Correct actions`` lines the grader cannot see.

A rubric line is only gradeable if `classify` finds an intent in it. 34% of the
corpus's lines classify to nothing, which means they fall back to bag-of-words
overlap: they can be "hit" by a sentence that happens to share vocabulary, and
they can never be hinted, because a hint is chosen by intent.

Most of them are not steps at all. They are things an EMT would never say aloud
— "Do not delay epinephrine to finish the history", "Be prepared to give a
second dose", "Warn the receiving hospital that the reaction may be biphasic".
Those belong in the rationale or the red flags, or they need rewriting as the
action they are really asking for.

    python -m ems.cli.rubric_check                # every approved scenario
    python -m ems.cli.rubric_check --source 25
    python -m ems.cli.rubric_check --generated    # drafts awaiting review
"""

import argparse
import re
from pathlib import Path

from ems.frontmatter import read_page
from ems.scenarios import list_approved
from ems.sim.grade import parse_actions
from ems.sim.intents import classify

#: Openings that mark a line as commentary rather than an action. Reported
#: separately because they are the ones an author should simply delete.
_NOT_AN_ACTION = (
    "do not delay", "be prepared", "be aware", "remember that", "understand that",
    "know that", "keep in mind", "note that", "bear in mind", "expect that",
)


def gaps(paths: list[Path], top: int = 30) -> list[tuple[int, str, str]]:
    """The vocabulary the corpus wants and the intent table does not have.

    Every rubric line the grader cannot see is a step somebody wrote and meant.
    Grouping them by their leading verb turns 300-odd individual failures into a
    short list of missing *categories* — which is a thing that can be fixed, as
    opposed to a number that can only be complained about.

    This is how `recognize-condition` was found: 79 lines began "Recognize…" and
    no category covered any of them, though naming your working impression out
    loud is an ordinary part of every radio report.

        python -m ems.cli.rubric_check --gaps

    Read the clusters, add the categories they name to `ems/sim/intents.py`,
    give each one a hint, and run it again. It went 33% -> 22% in four passes.
    """
    from collections import Counter
    from ems.sim.intents import classify

    buckets: dict[str, list[str]] = {}
    counts: Counter = Counter()
    for path in paths:
        _, body = read_page(path)
        for line in parse_actions(body):
            if classify(line):
                continue
            plain = re.sub(r"\[.*?\]", "", line).strip()
            key = " ".join(re.findall(r"[A-Za-z']+", plain.lower())[:2])
            counts[key] += 1
            buckets.setdefault(key, []).append(plain)
    return [
        (count, key, buckets[key][0][:88]) for key, count in counts.most_common(top)
    ]


def interchangeable(path: Path) -> list[tuple[int, int]]:
    """(specific, general) pairs where one step's meaning sits inside another's.

    "Obtain a SAMPLE history" and "Ask specifically about previous allergic
    reactions" carry the same intent, so a trainee who says only the general
    thing is credited with the specific question they never asked. Grading now
    demands matching words before it calls that a hit, but the pair is still a
    smell worth showing the author: either the second step should name something
    concrete the first does not, or the two should be one step.
    """
    from ems.sim.intents import classify

    _, body = read_page(path)
    signatures = [frozenset(classify(line)) for line in parse_actions(body)]
    pairs = []
    for i, mine in enumerate(signatures):
        if not mine:
            continue
        for j, other in enumerate(signatures):
            if i != j and other and mine <= other:
                pairs.append((i + 1, j + 1))
                break
    return pairs


def ungradeable(path: Path) -> list[tuple[int, str, str]]:
    """(index, line, why) for each rubric line the grader cannot see."""
    _, body = read_page(path)
    found = []
    for i, line in enumerate(parse_actions(body), 1):
        if classify(line):
            continue
        lowered = line.lower()
        why = next(
            (f"commentary, not an action ({opening!r})"
             for opening in _NOT_AN_ACTION if lowered.startswith(opening)),
            "no intent — graded on word overlap only",
        )
        found.append((i, line, why))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-rubric-check",
        description="Report rubric lines the grader cannot see.",
    )
    parser.add_argument("--source", type=int)
    parser.add_argument("--generated", action="store_true",
                        help="Check drafts in quarantine instead of the corpus")
    parser.add_argument("--commentary", action="store_true",
                        help="Only the lines that are plainly not actions")
    parser.add_argument("--interchangeable", action="store_true",
                        help="Steps a sibling step would satisfy on its own")
    parser.add_argument("--gaps", action="store_true",
                        help="Missing intent categories, clustered, commonest first")
    args = parser.parse_args()

    if args.generated:
        from ems.sim.generate import list_generated
        paths = list_generated()
    else:
        paths = sorted(list_approved())
    if args.source:
        paths = [p for p in paths if p.name.startswith(f"src{args.source}-")]

    if args.gaps:
        rows = gaps(paths)
        for count, key, example in rows:
            print(f"{count:4}  {key:22} e.g. {example}")
        print(f"\n{sum(c for c, _, _ in rows)} lines in the {len(rows)} biggest clusters")
        return 0

    if args.interchangeable:
        pairs_found = 0
        for path in paths:
            pairs = interchangeable(path)
            if not pairs:
                continue
            print(f"\n{path.stem}")
            for specific, general in pairs:
                pairs_found += 1
                print(f"  step {specific} is satisfied by step {general} alone")
        print(f"\n{pairs_found} interchangeable steps across {len(paths)} scenarios")
        return 0

    total_lines = flagged = 0
    for path in paths:
        _, body = read_page(path)
        total_lines += len(parse_actions(body))
        rows = ungradeable(path)
        if args.commentary:
            rows = [r for r in rows if r[2].startswith("commentary")]
        if not rows:
            continue
        print(f"\n{path.stem}")
        for index, line, why in rows:
            flagged += 1
            print(f"  {index:2}. {why}")
            print(f"      {line[:96]}")

    share = f" ({flagged / total_lines:.0%})" if total_lines else ""
    print(f"\n{flagged} of {total_lines} rubric lines{share} across {len(paths)} scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
