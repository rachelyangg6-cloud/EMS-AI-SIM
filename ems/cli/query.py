"""protocol-query — field protocol lookup (API path; needs ANTHROPIC_API_KEY).

Metadata goes to stderr, the answer to stdout.
"""
import argparse
import sys

from ems.query import answer_query


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-query",
        description="Answer an EMS field query from the wiki, with cited synthesis.",
    )
    parser.add_argument("question", help="The field question")
    parser.add_argument("--scope", default="EMT-B", help="Provider cert (EMT-B|AEMT|Paramedic)")
    parser.add_argument("--save", action="store_true", help="Save to wiki/lookups/ audit trail")
    args = parser.parse_args()

    result = answer_query(args.question, scope_level=args.scope, save=args.save)

    print(f"[mode: {result.mode}]", file=sys.stderr)
    if result.pages_used:
        print(f"[pages: {', '.join(result.pages_used)}]", file=sys.stderr)
    if result.unverified_citations:
        print(f"[WARNING unverified citations: {', '.join(result.unverified_citations)}]", file=sys.stderr)

    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
