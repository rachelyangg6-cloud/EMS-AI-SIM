"""protocol-review — review generated calls and promote the good ones.

    protocol-review                       # walk the pending queue
    protocol-review --show gen-20260818-01
    protocol-review --lessons             # what rejections have taught the generator

Approving moves the file into `wiki/scenarios/` as an expertise-marked fact,
eligible for the next Vetted Case draw. Rejecting keeps it in quarantine and
writes the critique into `system/generation-lessons.md`, which goes into every
later generation prompt.

The judgement is entirely the reviewer's. This only records it.
"""
import argparse
import sys

from ems.frontmatter import read_page
from ems.markdown import get_section
from ems.sim.generate import generated_dir, lessons_path
from ems.sim.review import approve, load_lessons_text, pending, reject


def _show(path) -> None:
    frontmatter, body = read_page(path)
    print(f"\n{'─' * 72}\n{path.stem}   [{', '.join(frontmatter.get('generated_from') or ()) or '—'}]")
    print(f"grounded in: {', '.join(frontmatter.get('pages_used') or ()) or '—'}\n")
    for section in ("Dispatch", "Presentation", "Vitals", "Correct actions",
                    "Rationale", "Red flags"):
        text = (get_section(body, section) or "").strip()
        if text:
            print(f"## {section}\n{text}\n")


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-review",
        description="Review generated practice calls; promote or reject them.",
    )
    parser.add_argument("--show", metavar="ID", help="Print one draft and exit")
    parser.add_argument("--lessons", action="store_true",
                        help="Print the accumulated generation lessons and exit")
    parser.add_argument("--by", default="", help="Your name or initials (labeled_by)")
    args = parser.parse_args()

    if args.lessons:
        text = load_lessons_text()
        print(text if text.strip() else f"No lessons yet ({lessons_path()} does not exist).")
        return 0

    if args.show:
        path = generated_dir() / f"{args.show}.md"
        if not path.exists():
            print(f"No draft {args.show!r} in {generated_dir()}", file=sys.stderr)
            return 2
        _show(path)
        return 0

    queue = pending()
    if not queue:
        print(f"Nothing awaiting review in {generated_dir()}")
        return 0

    reviewer = args.by or _ask("Your name or initials: ")
    if not reviewer:
        print("A review needs a name — it is the provenance stamp.", file=sys.stderr)
        return 2

    approved = rejected = skipped = 0
    print(f"\n{len(queue)} draft(s) to review.")
    for path in queue:
        _show(path)
        choice = _ask("[a]pprove  [r]eject  [s]kip  [q]uit > ").lower()
        if choice.startswith("q"):
            break
        if choice.startswith("s") or not choice:
            skipped += 1
            continue

        rating = _ask("Realism 1-5 (enter to skip): ")
        realism = int(rating) if rating.isdigit() and 1 <= int(rating) <= 5 else None

        if choice.startswith("a"):
            note = _ask("Note (optional): ")
            promoted = approve(path, labeled_by=reviewer,
                               realism_rating=realism, realism_note=note)
            approved += 1
            print(f"  → promoted to {promoted.parent.name}/{promoted.name}")
        elif choice.startswith("r"):
            critique = _ask("What is wrong with it? ")
            if not critique:
                print("  skipped — a rejection with no critique teaches nothing")
                skipped += 1
                continue
            reject(path, labeled_by=reviewer, critique=critique, realism_rating=realism)
            rejected += 1
            print("  → kept in quarantine; critique added to the generation lessons")

    print(f"\n{approved} approved · {rejected} rejected · {skipped} skipped")
    if approved:
        print("Approved calls are in the vetted corpus and can be dealt from the next run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
