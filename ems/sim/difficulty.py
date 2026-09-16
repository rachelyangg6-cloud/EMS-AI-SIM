"""Derive a practice difficulty (basic | intermediate | expert) for a scenario.

The simulator needs to serve a trainee cases at their chosen level, but the 150
approved scenarios predate the idea. Rather than hand-label them all, score the
signals already present in each file. Every scenario in the corpus is EMT-B, so
scope_level carries no information here — the discriminating signals are how many
actions the call takes, how many red flags there are to catch, and whether it
involves medication, an airway intervention, ALS escalation, or deterioration.

The derived value is a starting point, not a verdict: it is written to the
``difficulty`` frontmatter field and a reviewer can override it during labeling.
"""

import re
from typing import Optional

from ems.markdown import get_section

DIFFICULTY_LEVELS = ("basic", "intermediate", "expert")

# Thresholds calibrated against the 150 approved scenarios to give a usable pool
# at every level (43 basic / 58 intermediate / 49 expert). Re-check with
# `--stats` if the corpus grows substantially.
_BASIC_BELOW = 3.0
_EXPERT_AT = 5.5

_ALS_RE = re.compile(r"\bals\b|advanced life support|paramedic|intercept", re.I)
_DETERIORATION_RE = re.compile(
    r"deteriorat|worsen|declin|unresponsive|arrest|decompensat", re.I
)
_AIRWAY_RE = re.compile(r"bag-valve|\bbvm\b|suction|airway|ventilat", re.I)


def _count_numbered(section: Optional[str]) -> int:
    return len(re.findall(r"^\d+\.\s", section or "", re.MULTILINE))


def _count_bullets(section: Optional[str]) -> int:
    return len(re.findall(r"^-\s", section or "", re.MULTILINE))


def difficulty_score(frontmatter: dict, body: str) -> float:
    """Weighted complexity score. Higher means a harder call to work correctly."""
    actions = _count_numbered(get_section(body, "Correct actions"))
    red_flags = _count_bullets(get_section(body, "Red flags"))

    return (
        1.0 * max(0, actions - 3)
        + 0.5 * max(0, red_flags - 1)
        + 1.0 * min(len(frontmatter.get("medications") or []), 3)
        + 0.5 * min(len(frontmatter.get("procedures") or []), 3)
        + 1.5 * bool(_ALS_RE.search(body))
        + 1.0 * bool(_DETERIORATION_RE.search(body))
        + 1.0 * bool(_AIRWAY_RE.search(body))
    )


def derive_difficulty(frontmatter: dict, body: str) -> str:
    """Return "basic", "intermediate", or "expert" for one scenario."""
    score = difficulty_score(frontmatter, body)
    if score < _BASIC_BELOW:
        return "basic"
    if score >= _EXPERT_AT:
        return "expert"
    return "intermediate"
