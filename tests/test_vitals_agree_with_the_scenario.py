"""A scenario's numbers must agree with its own words.

A numeric vitals line filled in for a scenario that only described its vitals
in prose, without reading that prose, once gave a patient whose whole clinical
point is "systolic of 88" a blood pressure of 113/74, and a child described as
bradycardic a pulse of 119.

That is not a cosmetic inconsistency. The monitor is what the trainee sees and
the ``## Correct actions`` list is what the grader marks against, so when the two
disagree the trainee is graded on a patient they were never shown. It was found
by an EMT who assisted with nitroglycerin at a correctly-read 113/74 and was
charged two critical errors for treating a hypotensive patient.

Both checks compare a scenario against itself. Neither encodes a clinical
opinion of its own: the thresholds are only wide enough to catch a number that
contradicts the word sitting next to it.
"""
import re

import pytest

from ems.frontmatter import read_page
from ems.markdown import get_section
from ems.scenarios import list_approved

#: (word in the prose, which number must agree, what would contradict it, label)
DESCRIPTORS = (
    ("bradycard", "hr", lambda n: n >= 60, "pulse"),
    ("tachycard", "hr", lambda n: n <= 100, "pulse"),
    ("hypotens", "sbp", lambda n: n >= 100, "systolic"),
    ("hypox|cyanotic|cyanosis", "spo2", lambda n: n >= 94, "SpO2"),
    ("tachypn", "rr", lambda n: n <= 20, "RR"),
    ("bradypn", "rr", lambda n: n >= 12, "RR"),
)

_FIELDS = {
    "sbp": r"\bBP\s*(\d{2,3})\s*/",
    "spo2": r"\bSpO2\s*(\d{1,3})",
    "hr": r"\bpulse\s*(\d{1,3})",
    "rr": r"\bRR\s*(\d{1,3})",
}

#: "systolic of 88", "SBP 88" — a systolic named in words rather than measured.
_NAMED_SBP = re.compile(r"(?:sbp|systolic)(?:\s+(?:of|is|at))?\s*(\d{2,3})", re.I)


def _numbers(vitals: str) -> dict:
    out = {}
    for field, pattern in _FIELDS.items():
        match = re.search(pattern, vitals, re.I)
        out[field] = int(match.group(1)) if match else None
    return out


def _prose(vitals: str) -> str:
    """Whatever follows the generated numeric sentence."""
    return re.sub(r"^[^.]*\.", "", vitals, count=1) if "." in vitals else vitals


APPROVED = sorted(list_approved())
IDS = [p.stem for p in APPROVED]


@pytest.mark.parametrize("path", APPROVED, ids=IDS)
def test_the_numbers_agree_with_the_words_beside_them(path):
    """"Bradycardia for age" cannot sit next to a pulse of 119."""
    _, body = read_page(path)
    vitals = get_section(body, "Vitals") or ""
    numbers = _numbers(vitals)
    prose = _prose(vitals)

    for word, field, contradicts, label in DESCRIPTORS:
        value = numbers[field]
        if value is not None and re.search(word, prose, re.I) and contradicts(value):
            pytest.fail(
                f"{path.stem}: vitals read {label} {value}, but the same line "
                f"describes the patient as '{word.split('|')[0]}…'. The trainee "
                f"is shown the number and graded on the word."
            )


@pytest.mark.parametrize("path", APPROVED, ids=IDS)
def test_a_systolic_named_in_prose_is_the_one_on_the_monitor(path):
    """src18-s02 said "systolic of 88" and put 113/74 on the monitor."""
    _, body = read_page(path)
    vitals = get_section(body, "Vitals") or ""
    measured = _numbers(vitals)["sbp"]
    if measured is None:
        return

    for match in _NAMED_SBP.finditer(vitals + " " + (get_section(body, "Presentation") or "")):
        named = int(match.group(1))
        assert named == measured, (
            f"{path.stem}: the scenario names a systolic of {named} but the "
            f"monitor reads {measured}. Whichever is right, the grader and the "
            f"trainee are looking at different patients."
        )
