"""protocol-scenarios — generate OSCE-style training scenarios from ingested sources.

Reads the OCR'd resource raw notes and writes per-scenario files to
wiki/scenarios/ (status: pending) for review via the /label-scenarios skill.
"""
import argparse
import sys

from ems.frontmatter import read_page
from ems.paths import raw_dir
from ems.scenarios import generate_scenarios
from ems.vocabulary import load_vocabulary


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-scenarios",
        description="Generate OSCE-style scenarios from ingested resources.",
    )
    parser.add_argument("--sources", default="1-4", help="Range or list, e.g. '1-4' or '1,3'")
    parser.add_argument("--count", type=int, default=10, help="Scenarios per source (default 10)")
    args = parser.parse_args()

    vocab = load_vocabulary()
    rc = 0
    for n in _parse_sources(args.sources):
        note = raw_dir() / f"source-{n}.md"
        if not note.exists():
            print(f"skip: {note} not found (run protocol-add-resource first)", file=sys.stderr)
            rc = 1
            continue
        _fm, body = read_page(note)
        print(f"generating {args.count} scenarios for source {n} ...", file=sys.stderr)
        paths = generate_scenarios(n, body.strip(), vocab, n=args.count)
        print(f"  wrote {len(paths)} scenarios", file=sys.stderr)
    return rc


def _parse_sources(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        elif part:
            out.append(int(part))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
