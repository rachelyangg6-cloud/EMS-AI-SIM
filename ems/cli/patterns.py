"""protocol-patterns — inspect and check the call-pattern weights.

    protocol-patterns --check              # is every weight key real and reachable?
    protocol-patterns --today              # what today's conditions do to the pool
    protocol-patterns --aqi 400 --draws 500  # measure the shift, don't assume it
"""
import argparse
import collections
import sys
from datetime import date

from ems.frontmatter import read_page
from ems.sim.playable import playable_cases
from ems.sim import select as selector
from ems.sim.patterns import Conditions, load_patterns, season_for, validate, weights


def _conditions(args) -> Conditions:
    return Conditions(
        season=args.season or season_for(date.today()),
        aqi=args.aqi,
        heat_index=args.heat_index,
        flu_season_peak=args.flu,
    )


def _check() -> int:
    result = validate()
    if result.unknown:
        print("Weight keys that are not condition slugs (rules cannot match):",
              file=sys.stderr)
        for slug in result.unknown:
            print(f"  ✗ {slug}", file=sys.stderr)
    if result.unreachable:
        print("Weight keys no approved scenario carries (rules cannot fire):",
              file=sys.stderr)
        for slug in result.unreachable:
            print(f"  ! {slug}", file=sys.stderr)
    if result.ok and not result.unreachable:
        print("call-patterns.yaml: every weight key is real and reachable.",
              file=sys.stderr)
    return 1 if result.unknown else 0


def _draw(conditions: Conditions, draws: int, level: str | None, seed: int | None) -> int:
    pool = playable_cases(difficulty=level) if level else playable_cases()
    if not pool:
        print("No approved scenarios in that pool.", file=sys.stderr)
        return 2

    import random

    rng = random.Random(seed)
    choices = selector.weigh(pool, conditions)   # read the corpus once
    picked = collections.Counter()
    for _ in range(draws):
        chosen = selector.draw(choices, rng)
        if chosen:
            picked[chosen.stem] += 1

    today = weights(conditions)
    print(f"{draws} draws from {len(pool)} scenarios "
          f"(season={conditions.season or '-'} aqi={conditions.aqi} "
          f"heat={conditions.heat_index} flu={conditions.flu_season_peak})")
    print(f"active multipliers: {today or 'none'}\n")

    tags = {}
    for path in pool:
        frontmatter, _ = read_page(path)
        tags[path.stem] = tuple(frontmatter.get("conditions") or ()) or ("(untagged)",)

    by_condition = collections.Counter()
    for scenario_id, count in picked.items():
        for slug in tags[scenario_id]:
            by_condition[slug] += count

    print("draws by condition:")
    for slug, count in by_condition.most_common(12):
        share = 100 * count / max(1, sum(by_condition.values()))
        flag = "  ←" if slug in today else ""
        print(f"  {count:5d}  {share:5.1f}%  {slug}{flag}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-patterns",
        description="Check and simulate environment-aware scenario selection.",
    )
    parser.add_argument("--check", action="store_true",
                        help="Validate every weight key; exit 1 on an unknown slug")
    parser.add_argument("--today", action="store_true", help="Draw using today's season")
    parser.add_argument("--season", choices=("winter", "spring", "summer", "fall"))
    parser.add_argument("--aqi", type=int, help="Force an air-quality index")
    parser.add_argument("--heat-index", type=int, dest="heat_index")
    parser.add_argument("--flu", action="store_true", help="Force flu-season peak")
    parser.add_argument("--draws", type=int, default=200)
    parser.add_argument("--level", choices=("basic", "intermediate", "expert"))
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()

    if args.check:
        return _check()
    if not any((args.today, args.season, args.aqi, args.heat_index, args.flu)):
        print(load_patterns())
        return 0
    return _draw(_conditions(args), args.draws, args.level, args.seed)


if __name__ == "__main__":
    raise SystemExit(main())
