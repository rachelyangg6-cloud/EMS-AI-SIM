"""protocol-add-source — extract a source document into a raw note (status: new).

Metadata goes to stderr; extracted protocol text is written to the raw note file
and never dumped to stdout (keeps context/log output clean).
"""
import argparse
import sys
from pathlib import Path

from ems.source_creator import create_source


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-add-source",
        description="Add an SOP/protocol document to raw/ as a new source note.",
    )
    parser.add_argument("file", type=Path, help="Path to the source PDF or text file")
    parser.add_argument("--sop-id", default=None, help="SOP-ID if known")
    parser.add_argument("--effective-date", default=None, help="Effective date (YYYY-MM-DD)")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 1

    meta = create_source(
        args.file,
        sop_id=args.sop_id,
        effective_date=args.effective_date,
    )
    print(f"created raw source: {meta.path}  (status: {meta.status})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
