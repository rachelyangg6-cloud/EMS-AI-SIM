"""Pick the next call.

    pool = approved scenarios at the trainee's level
         → weight by today's conditions (season, AQI, heat)
         → down-weight what they have seen recently
         → weighted random pick

Weighting shifts the odds; it never restricts the pool. A trainee on a
400-AQI day should get more asthma, not only asthma — and a scenario carrying
no condition tag (94 of the 150 approved ones) must stay reachable, which is why
the base weight is 1.0 rather than 0.
"""

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ems.frontmatter import read_page
from ems.sim.patterns import Conditions, weights

#: How much a scenario is damped for having been seen recently. Applied once,
#: not per sighting: seeing a case twice is not twice as stale.
RECENT_PENALTY = 0.15


@dataclass(frozen=True)
class Choice:
    path: Path
    weight: float
    #: Why it scored what it did — surfaced by the CLI, useful when a table looks wrong.
    matched: tuple[str, ...] = ()


def scenario_weight(
    frontmatter: dict, today: dict[str, float], recent: Iterable[str] = ()
) -> tuple[float, tuple[str, ...]]:
    """Multiplier for one scenario, and which condition keys drove it."""
    weight, matched = 1.0, []
    for slug in frontmatter.get("conditions") or ():
        factor = today.get(slug)
        if factor:
            weight *= factor
            matched.append(slug)
    if frontmatter.get("scenario_id") in set(recent):
        weight *= RECENT_PENALTY
    return weight, tuple(matched)


def weigh(
    pool: Iterable[Path],
    conditions: Optional[Conditions] = None,
    recent: Iterable[str] = (),
    patterns: Optional[dict] = None,
) -> list[Choice]:
    today = weights(conditions or Conditions(), patterns)
    seen = list(recent)
    choices = []
    for path in pool:
        frontmatter, _ = read_page(path)
        weight, matched = scenario_weight(frontmatter, today, seen)
        choices.append(Choice(path=path, weight=weight, matched=matched))
    return choices


def draw(choices: list[Choice], rng: Optional[random.Random] = None) -> Optional[Path]:
    """One weighted pick from already-weighed choices.

    Split from `weigh` because weighing reads every scenario file: fine once per
    session, ruinous inside a loop. Anything drawing repeatedly weighs once and
    calls this N times.
    """
    if not choices:
        return None
    generator = rng or random.Random()
    return generator.choices(
        [c.path for c in choices], weights=[c.weight for c in choices], k=1
    )[0]


def select(
    pool: Iterable[Path],
    conditions: Optional[Conditions] = None,
    recent: Iterable[str] = (),
    patterns: Optional[dict] = None,
    rng: Optional[random.Random] = None,
) -> Optional[Path]:
    """Weigh the pool and take one pick. For a single call, such as session start."""
    return draw(weigh(pool, conditions, recent, patterns), rng)
