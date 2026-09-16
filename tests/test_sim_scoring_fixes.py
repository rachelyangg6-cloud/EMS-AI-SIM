"""Scoring bugs found by playing src1-s01 and src1-s01.

Both sessions scored 0/100 while doing broadly reasonable things.
"""
import pytest

from ems.paths import scenarios_dir
from ems.sim.grade import credit_the_size_up, grade_size_up, ActionResult
from ems.sim.intents import classify
from ems.sim.session import Session
from ems.sim.vitals import generate
from ems.sim.scene import Vitals


# ── asking for a saturation is not ordering a gas ────────────────────────────

@pytest.mark.parametrize("said", [
    "what is the respiratory rate pulse oxygen and blood pressure",
    "check his pulse ox",
    "put him on a pulse oximeter",
    "what is his oxygen saturation",
    "check the o2 sat",
    "what's her oxygen level",
])
def test_asking_for_a_saturation_is_not_ordering_oxygen(said):
    """This fired `oxygen-device-missing` twice in a real session and took the
    score to 0 — the critical-error rule for a dangerous omission, triggered by
    someone asking to check a pulse ox."""
    assert not {i for i in classify(said) if i.startswith("oxygen")}


@pytest.mark.parametrize("said,expected", [
    ("give him oxygen by nasal cannula at 4 L/min", "oxygen-nc"),
    ("nonrebreather at 15 liters per minute", "oxygen-nrb"),
    ("bag him with a BVM at 15 L/min", "oxygen-bvm"),
])
def test_actually_ordering_oxygen_still_registers(said, expected):
    intents = classify(said)
    assert "oxygen" in intents and expected in intents


def test_a_real_pulse_ox_session_earns_no_critical_error():
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    said = [
        "BSI scene is safe one patient",
        "what's the respiratory rate pulse oxygen and blood pressure",
        "help him with his nitroglycerin",
        "end of call",
    ]
    index = 0
    while not session.done:
        if session.awaiting_input:
            session.step(said[index] if index < len(said) else "end of call")
            index += 1
        else:
            session.step()
    assert session.grade().critical_errors == ()


# ── the size-up counts as part of the call ───────────────────────────────────

def test_a_step_covered_in_the_size_up_is_not_marked_missed():
    """BSI was ✓ in the size-up panel and ✗ two panels later in the same debrief."""
    size_up = grade_size_up("BSI, scene is safe, one patient")
    results = (ActionResult(index=1, action="Take Standard Precautions (gloves).",
                            status="missed"),)
    credited = credit_the_size_up(results, size_up)
    assert credited[0].status == "hit"
    assert credited[0].note == "covered in your scene size-up"


def test_a_step_the_size_up_never_covered_stays_missed():
    size_up = grade_size_up("scene is safe")
    results = (ActionResult(index=1, action="Administer aspirin 324 mg.",
                            status="missed"),)
    assert credit_the_size_up(results, size_up)[0].status == "missed"


# ── asking again gets an answer again ────────────────────────────────────────

def test_asking_for_the_vitals_again_reads_them_again():
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    said = ["scene is safe", "check the vital signs", "check the vital signs again"]
    index, observed = 0, []
    while not session.done:
        if session.awaiting_input:
            event = session.step(said[index] if index < len(said) else "end of call")
            index += 1
        else:
            event = session.step()
        if event.phase == "OBSERVE" and "Pulse" in event.text:
            observed.append(event.text)
    assert len(observed) >= 2, "a reassessment must produce the numbers a second time"


# ── an infant does not get an adult blood pressure ───────────────────────────

def test_an_unknown_age_leaves_the_blood_pressure_blank_rather_than_guessing():
    filled, generated = generate(Vitals(), age_group=None, seed="x")
    assert filled.bp is None and "bp" not in generated
