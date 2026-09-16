"""protocol-difficulty — derive and backfill the practice difficulty on scenarios."""
import argparse
import collections
import sys

from ems.frontmatter import read_page, write_frontmatter
from ems.paths import scenarios_dir
from ems.sim.difficulty import derive_difficulty, difficulty_score


def _scenario_paths():
    return [p for p in sorted(scenarios_dir().glob("*.md")) if p.name != "_template.md"]


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-difficulty",
        description="Derive basic/intermediate/expert difficulty for approved scenarios.",
    )
    parser.add_argument("--backfill", action="store_true", help="Write difficulty to frontmatter")
    parser.add_argument("--dry-run", action="store_true", help="Show what --backfill would write")
    parser.add_argument("--stats", action="store_true", help="Show the difficulty spread and exit")
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite a difficulty that is already set (default: leave it alone)",
    )
    args = parser.parse_args()

    spread = collections.Counter()
    written = 0
    for path in _scenario_paths():
        fm, body = read_page(path)
        if fm.get("status") != "approved":
            continue
        level = derive_difficulty(fm, body)
        spread[level] += 1

        if args.stats:
            continue
        if fm.get("difficulty") and not args.force:
            continue
        if args.dry_run:
            print(f"{path.name}: {level}  (score {difficulty_score(fm, body):.1f})")
            continue
        if args.backfill:
            fm["difficulty"] = level
            write_frontmatter(path, fm)
            written += 1

    total = sum(spread.values())
    summary = "  ".join(f"{lvl}={spread[lvl]}" for lvl in ("basic", "intermediate", "expert"))
    print(f"{total} approved scenarios: {summary}", file=sys.stderr)
    if args.backfill and not args.dry_run:
        print(f"  wrote difficulty to {written} files", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
