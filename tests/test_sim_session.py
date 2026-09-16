"""
Tests for the full-arc session machine (Project 2).
Offline: the session is deterministic and never calls an LLM.
"""
import pytest

from ems.sim.session import Session, is_end_of_call

SCENARIO = """---
type: scenario
scenario_id: test-s01
source_index: 19
status: approved
labeled_by: ry
difficulty: expert
citations:
- '[SRC-19:p541]'
---

## Dispatch
58-year-old female, difficulty breathing.

## Presentation
She is slumped in a recliner. Her lips are dusky. She speaks one word at a time.

## Vitals
RR 36 shallow, HR 118, SpO2 82%, cyanotic.

## Correct actions
1. Take standard precautions and ensure the scene is safe.
2. Begin assisted ventilation with a bag-valve mask on oxygen at 15 L/min with a reservoir.
3. Call ALS and transport without delay.

## Rationale
Respiratory failure needs positive pressure ventilation.

## Red flags
- Cyanosis
- SpO2 82%
"""


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "test-s01.md"
    path.write_text(SCENARIO, encoding="utf-8")
    return Session.from_path(path)


def _drain(session, answers):
    """Play the session, feeding ``answers`` whenever it waits. Returns events."""
    queue = list(answers)
    events = []
    while not session.done:
        if session.awaiting_input:
            events.append(session.step(queue.pop(0) if queue else "end of call"))
        else:
            events.append(session.step())
    return events


def test_the_call_opens_on_the_radio(session):
    event = session.step()
    assert event.phase == "TONE_OUT"
    assert event.speaker == "dispatcher"
    assert "difficulty breathing" in event.text
    assert not event.awaiting_input


def _to_first_prompt(session):
    """Play the cinematic opening; return the first event that waits on the EMT."""
    events = []
    while not session.awaiting_input:
        events.append(session.step())
    return events


def test_size_up_is_the_first_thing_asked_of_the_emt(session):
    events = _to_first_prompt(session)
    assert [e.phase for e in events] == ["TONE_OUT", "EN_ROUTE", "ARRIVAL", "SIZE_UP"]
    assert all(not e.awaiting_input for e in events[:3])
    assert events[-1].awaiting_input


def test_scene_narration_follows_the_size_up(session):
    _to_first_prompt(session)
    event = session.step("Scene is safe, gloves on, one patient.")
    assert event.phase == "SCENE_NARRATION"
    assert "slumped in a recliner" in event.text


def test_asking_for_input_when_none_is_given_raises(session):
    _to_first_prompt(session)
    with pytest.raises(ValueError):
        session.step()


def test_full_arc_reaches_debrief(session):
    events = _drain(session, [
        "Scene is safe, gloves on, one patient, nature of illness is trouble breathing.",
        "How long has she been like this?",
        "BVM at 15 L/min with a reservoir.",
        "end of call",
    ])
    phases = [e.phase for e in events]
    assert phases[0] == "TONE_OUT"
    assert phases[-1] == "DEBRIEF"
    assert "SIZE_UP" in phases and "TURN" in phases
    assert session.done


def test_end_of_call_can_be_said_at_any_interactive_turn(session):
    _drain(session, ["Scene is safe.", "end of call"])
    assert session.phase == "DEBRIEF"


def test_is_end_of_call_phrasings():
    assert is_end_of_call("end of call")
    assert is_end_of_call("Okay, I'm going to end the call.")
    assert not is_end_of_call("I'll call ALS")


def test_the_answer_key_never_appears_in_an_event(session):
    """The whole product rests on this: the rubric is hidden state."""
    events = _drain(session, [
        "Scene is safe, gloves on.",
        "What's her history?",
        "BVM at 15 L/min with a reservoir.",
        "end of call",
    ])
    rubric = session._rubric()
    assert rubric, "fixture should have a rubric to leak"
    transcript = " ".join(e.text for e in events)
    for action in rubric:
        assert action not in transcript


def test_only_emt_turns_carry_intents(session):
    _drain(session, ["Scene is safe, gloves on.", "end of call"])
    for turn in session.turns:
        if turn.speaker != "emt":
            assert turn.intents == ()
    assert any(turn.intents for turn in session.emt_turns())


def test_grade_uses_the_size_up_turn_and_ignores_the_end_phrase(session):
    _drain(session, [
        "Scene is safe, gloves and eye protection, one patient, nature of illness is "
        "respiratory failure, requesting ALS.",
        "How long has she been short of breath?",
        "BVM at 15 L/min with a reservoir.",
        "end of call",
    ])
    grade = session.grade()
    assert grade.scenario_id == "test-s01"
    assert grade.size_up.score == 5
    assert grade.critical_errors == ()
    assert grade.citations == ("[SRC-19:p541]",)


# ── vitals gating ────────────────────────────────────────────────────────────

def test_the_monitor_starts_blank(session):
    _to_first_prompt(session)
    assert session.known_vitals() == {}


def test_a_number_appears_only_once_the_emt_assesses_for_it(session):
    events = _drain(session, [
        "Scene is safe, gloves on.",
        "How long has she been like this?",                  # asks nothing measurable
        "I'll hold off for now.",
        "Put a pulse ox on her and check a radial pulse",     # now it is earned
        "Keep ventilating.",
        "end of call",
    ])
    # Empty observations are not filtered by the engine — they advance the
    # machine without being spoken — so the assertion is about what was said.
    observes = [e.text for e in events if e.phase == "OBSERVE" and e.text]
    assert "82" not in observes[0]
    assert "SpO2 82%" in observes[1] and "Pulse 118" in observes[1]
    assert session.known_vitals() == {"hr": 118, "spo2": 82}


def test_a_vital_is_narrated_once_not_every_look(session):
    events = _drain(session, [
        "Scene is safe.",
        "Check a radial pulse",
        "Continue.",
        "Anything else I should see?",
        "end of call",
    ])
    # Empty observations are not filtered by the engine — they advance the
    # machine without being spoken — so the assertion is about what was said.
    observes = [e.text for e in events if e.phase == "OBSERVE" and e.text]
    assert "Pulse 118" in observes[0]
    assert observes[1] == "Nothing has changed since your last look."


def test_asking_for_full_vitals_reveals_everything_the_scenario_states(session):
    events = _drain(session, [
        "Scene is safe.",
        "Get me a full set of vital signs",
        "end of call",
    ])
    text = next(e.text for e in events if e.phase == "OBSERVE")
    assert "RR 36" in text and "Pulse 118" in text and "SpO2 82%" in text
    # A stated number is authored content and is reported as itself.
    assert not {"rr", "hr", "spo2"} & session.generated_vitals


def test_a_vital_the_scenario_omits_is_filled_in_and_flagged(session):
    """The monitor gets a blood pressure this scenario never states — labelled.

    Four blank tiles taught nothing, so the simulator fills the gaps from
    `system/vital-profiles.yaml`. What it invents it declares.
    """
    events = _drain(session, [
        "Scene is safe.",
        "Get me a full set of vital signs",
        "end of call",
    ])
    text = next(e.text for e in events if e.phase == "OBSERVE")
    assert "BP" in text
    assert "bp" in session.known_vitals()
    assert "bp" in session.generated_vitals
