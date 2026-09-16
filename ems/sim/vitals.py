"""Fill the monitor when the scenario is silent.

Only 26 of 150 approved scenarios state a respiratory rate and 12 a blood
pressure, so the monitor was four empty tiles on most calls. This fills the gaps
from `system/vital-profiles.yaml`, keyed on the scenario's condition slugs and
age group.

**What the scenario says always wins.** A stated number is authored content and
is never touched, never marked, and never overridden. Only the blanks are
filled, and every filled value is flagged `generated` from here to the screen,
where it renders with a SIM tag. The rule the rest of the simulator keeps — that
a number nobody vetted must not be presented as fact — holds by labelling rather
than by silence.

**Deterministic per scenario.** The draw is seeded by `scenario_id`, so a case
has the same pulse every time anyone runs it. A trainee comparing notes with
another trainee is comparing the same patient.
"""

import random
import re
from dataclasses import replace
from typing import Optional

import yaml

from ems.markdown import get_section
from ems.paths import system_dir
from ems.sim.scene import Vitals

AGE_GROUPS = ("infant", "child", "adolescent", "adult")


def profiles_path():
    return system_dir() / "vital-profiles.yaml"


def load_profiles(path=None) -> dict:
    data = yaml.safe_load((path or profiles_path()).read_text(encoding="utf-8")) or {}
    return {
        "baseline": data.get("baseline") or {},
        "conditions": data.get("conditions") or {},
        "findings": data.get("findings") or {},
    }


def profile_for(
    conditions,
    age_group: str = "adult",
    profiles: Optional[dict] = None,
    effort: str = "",
) -> dict:
    """Ranges for this patient, most-vetted source last.

    Age baseline, then the condition slug, then any finding the scenario's own
    text states. `effort` wins because it is the author's word about this
    patient: an apneic patient has a respiratory rate of zero whatever their
    condition slug would otherwise imply.
    """
    profiles = profiles or load_profiles()
    base = dict(
        profiles["baseline"].get(age_group)
        or profiles["baseline"].get("adult")
        or {}
    )
    for slug in conditions or ():
        override = profiles["conditions"].get(slug)
        if override:
            base.update(override)
            break
    if effort:
        base.update(profiles["findings"].get(effort) or {})
    return base


def generate(
    stated: Vitals,
    conditions=(),
    age_group: str = "adult",
    seed: str = "",
    profiles: Optional[dict] = None,
    effort: str = "",
) -> tuple[Vitals, frozenset[str]]:
    """Return the vitals to show, plus which of them the simulator made up.

    `stated` comes from the scenario's own ``## Vitals`` section and is returned
    untouched; only its `None` fields are filled.
    """
    # `None` means nobody said how old this patient is. Blood pressure is the
    # vital that varies most across a life — the adult band put 118/68 on
    # src8-s01's five-month-old — so when the band is unknown the blood pressure
    # is left blank rather than guessed. An empty tile prompts the trainee to go
    # and take one; a wrong normal teaches them the wrong number.
    band_known = age_group is not None
    ranges = profile_for(conditions, age_group or "adult", profiles, effort)
    rng = random.Random(f"{seed}|{age_group}|{','.join(sorted(conditions or ()))}")
    filled, generated = {}, set()

    def draw(key: str) -> Optional[int]:
        span = ranges.get(key)
        if not span:
            return None
        low, high = int(span[0]), int(span[1])
        return rng.randint(min(low, high), max(low, high))

    for key in ("rr", "hr", "spo2"):
        if getattr(stated, key) is None:
            value = draw(key)
            if value is not None:
                filled[key] = value
                generated.add(key)

    if stated.bp is None and band_known:
        systolic, diastolic = draw("sbp"), draw("dbp")
        if systolic is not None and diastolic is not None:
            # A diastolic at or above the systolic is not a low blood pressure,
            # it is a broken one. Keep a plausible pulse pressure.
            diastolic = min(diastolic, systolic - 15)
            if diastolic > 0:
                filled["bp"] = f"{systolic}/{diastolic}"
                generated.add("bp")

    return replace(stated, **filled), frozenset(generated)


#: Reading a life stage out of the scenario's own words.
#:
#: Half the playable corpus (50 of 95) predates the `age_group` frontmatter
#: field, and `generate` defaulted the lot to "adult" — so src8-s01, whose
#: dispatch opens "Infant, several days of vomiting", was handed a blood
#: pressure of 118/68. In a training tool a wrong normal is worse than a blank
#: tile, because the trainee has no way to know which one they were shown.
_AGE_PATTERNS = (
    ("neonate",   r"\bneonate\b|\bnewborn\b|\bjust\s+born\b|\b(?:[0-3]?\d)[- ]day[- ]old\b"),
    ("pediatric", r"\binfant\b|\btoddler\b|\bbaby\b|\bchild\b|\bboy\b|\bgirl\b"
                  r"|\bteen(?:ager)?\b|\badolescent\b|\bpediatric\b|\bschool[- ]age\b"
                  r"|\b(?:[1-9]|1[0-1])[- ]month[- ]old\b"
                  r"|\b(?:[1-9]|1[0-7])[- ]year[- ]old\b"),
    ("geriatric", r"\belderly\b|\bgeriatric\b|\bolder\s+adult\b"
                  r"|\b(?:6[5-9]|[7-9]\d|1[01]\d)[- ]year[- ]old\b"),
    ("adult",     r"\badult\b|\bman\b|\bwoman\b|\bmale\b|\bfemale\b"
                  r"|\b(?:1[89]|[2-5]\d|6[0-4])[- ]year[- ]old\b"),
)
_AGE_COMPILED = tuple((band, re.compile(p, re.IGNORECASE)) for band, p in _AGE_PATTERNS)


def infer_age_group(frontmatter: dict, body: str) -> Optional[str]:
    """The patient's life stage: frontmatter first, then the scenario's words.

    Returns None when neither says — and None means *do not invent an
    age-dependent number*, rather than quietly meaning "adult".

    Order matters. Geriatric and neonate are checked before adult and pediatric
    because "68-year-old man" and "3-day-old" both also match the looser bands.
    """
    stated = frontmatter.get("age_group")
    if isinstance(stated, str) and stated:
        return stated
    if isinstance(stated, (list, tuple)) and stated:
        return stated[0]

    # Only the dispatch and the presentation, never the whole file. Rationale
    # and Correct actions routinely name a *different* life stage for contrast —
    # src13-s01 is an adult scenario whose rationale explains the brachial pulse
    # in a child, and reading the whole body made its patient pediatric.
    said = " ".join(
        (get_section(body, section) or "") for section in ("Dispatch", "Presentation")
    )
    for band in ("neonate", "geriatric", "pediatric", "adult"):
        if dict(_AGE_COMPILED)[band].search(said):
            return band
    return None
