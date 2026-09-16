"""protocol-generate — draft new practice calls from the vetted wiki.

    protocol-generate --conditions asthma hypoxia
    protocol-generate --conditions sepsis --count 3
    protocol-generate --list

Drafts land in `wiki/scenarios/generated/` as `status: pending`. Nothing there is
approved, nothing there can be dealt by the simulator, and nothing is written at
all unless it passes every playability check. Review them with
`protocol-review`.

Two ways to draft, and neither is the default path for this project:

    protocol-generate --context asthma hypoxia    # print the grounding to read
    protocol-generate --from-file draft.md --conditions asthma
                                                  # gate and save what you wrote

That is the `generate-case` skill's flow — the agent reads the retrieved pages
and writes the call, exactly as `generate-scenarios` and `ingest-source` work.
No API key.

    protocol-generate --conditions asthma --api    # headless, calls Claude

`--api` is for a batch run with no agent in the loop and needs credentials
(`ANTHROPIC_API_KEY`, or a line in the gitignored `.env`). Both paths go through
the same gate.
"""
import argparse
import sys

from ems.frontmatter import read_page
from pathlib import Path

from ems.sim.generate import (
    GenerationFailed, context_for, draft, draft_from_text, generated_dir,
    list_generated, save_draft,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-generate",
        description="Draft practice calls grounded in the vetted wiki.",
    )
    parser.add_argument("--conditions", nargs="+", metavar="SLUG",
                        help="Condition slugs to build the call around")
    parser.add_argument("--context", nargs="+", metavar="SLUG",
                        help="Print the retrieved wiki grounding for these slugs and exit")
    parser.add_argument("--from-file", metavar="PATH",
                        help="Gate and save a call you wrote yourself (no API)")
    parser.add_argument("--api", action="store_true",
                        help="Draft by calling Claude instead (needs credentials)")
    parser.add_argument("--count", type=int, default=1, help="How many to draft")
    parser.add_argument("--difficulty", default="intermediate",
                        choices=("basic", "intermediate", "expert"))
    parser.add_argument("--list", action="store_true",
                        help="List drafts awaiting review and exit")
    args = parser.parse_args()

    if args.list:
        waiting = list_generated()
        if not waiting:
            print(f"No drafts awaiting review in {generated_dir()}")
            return 0
        print(f"{len(waiting)} draft(s) awaiting review:\n")
        for path in waiting:
            frontmatter, body = read_page(path)
            origin = ", ".join(frontmatter.get("generated_from") or ()) or "—"
            print(f"  {path.stem}  [{origin}]")
        return 0

    if args.context:
        context, used = context_for(args.context)
        print(f"# Grounding for: {', '.join(args.context)}")
        print(f"# Pages: {', '.join(used)}\n")
        print(context)
        return 0

    if not args.conditions:
        parser.error("--conditions is required (or use --list/--context)")

    if args.from_file:
        source = Path(args.from_file)
        if not source.exists():
            print(f"No such file: {source}", file=sys.stderr)
            return 2
        context, used = context_for(args.conditions)
        candidate = draft_from_text(
            source.read_text(encoding="utf-8"),
            conditions=args.conditions, pages_used=used, context=context,
        )
        if not candidate.playable:
            # Reported, not raised. Whoever wrote it can fix the dispatch and
            # run this again — which is faster than any retry loop.
            print("Not playable, so not saved:", file=sys.stderr)
            for problem in candidate.problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        path = save_draft(candidate, difficulty=args.difficulty)
        print(f"  wrote {path}")
        if candidate.stripped_citations:
            print(f"    stripped {len(candidate.stripped_citations)} unsupported citation(s): "
                  f"{', '.join(candidate.stripped_citations)}")
        print("\n1 draft pending review. `protocol-review` to work through it.")
        return 0

    if not args.api:
        parser.error(
            "drafting needs either --from-file (you write it) or --api (Claude writes it). "
            "Start with --context to read the grounding."
        )

    written = 0
    for _ in range(args.count):
        try:
            candidate = draft(args.conditions)
        except GenerationFailed as failure:
            # Loud, with the reasons. A silent unplayable file is how the corpus
            # got to 101 calls that cannot be played.
            print(f"Generation failed after {failure.attempts} attempts:", file=sys.stderr)
            for problem in failure.problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        except Exception as error:                       # noqa: BLE001
            print(f"Generation failed: {error}", file=sys.stderr)
            if "api_key" in str(error).lower() or "authentication" in str(error).lower():
                print("  Set ANTHROPIC_API_KEY, or run `ant auth login`.", file=sys.stderr)
            return 1

        path = save_draft(candidate, difficulty=args.difficulty)
        written += 1
        print(f"  wrote {path.relative_to(path.parent.parent.parent)}")
        if candidate.stripped_citations:
            print(f"    stripped {len(candidate.stripped_citations)} unsupported citation(s): "
                  f"{', '.join(candidate.stripped_citations)}")

    print(f"\n{written} draft(s) pending review. `protocol-review` to work through them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
