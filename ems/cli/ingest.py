"""protocol-ingest — scan raw/ for new sources and ingest them.

Progress and step detail go to stderr; extracted protocol text is never dumped.
"""
import argparse
import sys

from ems.ingest import ingest


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-ingest",
        description="Summarize, route, and patch wiki pages from new raw sources.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Summarize and route only; write no pages and don't flip source status.",
    )
    parser.add_argument(
        "--show-steps",
        action="store_true",
        help="Print per-source summarize/route/update steps to stderr.",
    )
    args = parser.parse_args()

    results = ingest(dry_run=args.dry_run, show_steps=args.show_steps)

    if not results:
        print("no new sources to ingest", file=sys.stderr)
        return 0

    for r in results:
        if r.status == "error":
            print(f"ERROR {r.source}: {r.error}", file=sys.stderr)
        elif args.dry_run:
            print(f"{r.source}: would route → {', '.join(r.routed_pages) or '(none)'}", file=sys.stderr)
        else:
            print(f"{r.source}: updated {', '.join(r.updated_pages) or '(no pages)'}", file=sys.stderr)

    errors = sum(1 for r in results if r.status == "error")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
