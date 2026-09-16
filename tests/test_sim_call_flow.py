"""
Turn-taking fixes found by replaying a real testing session (src1-s01).
Offline and deterministic.
"""
import pytest

from ems.cli.context_check import problems
from ems.paths import scenarios_dir
from ems.sim.intents import classify, is_action, is_question, revealed_vitals
from ems.sim.session import Session, is_end_of_call


# ── ending a call ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "end call", "end of call", "end the call", "ending call", "clear the call",
    "call complete", "call is over", "end", "done", "finished",
    "I'm done with the call",
])
def test_every_way_anyone_says_it_ends_the_call(said):
    """"end call" was not accepted, so a trainee's turn was eaten and they guessed again."""
    assert is_end_of_call(said)


@pytest.mark.parametrize("said", [
    "end tidal CO2 is rising",
    "I want to end the bleeding",
    "recommend calling ALS",
    "send the call sheet with the patient",
])
def test_clinical_language_does_not_end_the_call_by_accident(said):
    assert not is_end_of_call(said)


# ── asking for a number by naming it ─────────────────────────────────────────

@pytest.mark.parametrize("said", ["what is the pulse", "pulse", "what is her heart rate", "hr"])
def test_naming_the_pulse_is_asking_for_it(said):
    """Asked three times in the real session and never answered, for want of a verb."""
    assert "hr" in revealed_vitals(classify(said))


@pytest.mark.parametrize("said", ["respirations", "what is the respiratory rate"])
def test_naming_the_respiratory_rate_is_asking_for_it(said):
    assert "rr" in revealed_vitals(classify(said))


def test_a_pulse_oximeter_is_a_saturation_not_a_pulse():
    assert "hr" not in revealed_vitals(classify("pulse oximetry"))


def test_pulseless_is_not_a_request_for_a_pulse():
    assert "pulse-check" not in classify("the patient is pulseless")


def test_naming_the_whole_set_counts_as_asking_for_a_full_set():
    """The exact phrasing that scored "record a full set of vital signs" as missed."""
    intents = classify("what is the patients pulse, respiratory rate, spo2, and blood pressure")
    assert "vitals-full" in intents
    assert revealed_vitals(intents) == frozenset({"rr", "hr", "spo2", "bp"})


def test_naming_only_two_is_not_a_full_set():
    assert "vitals-full" not in classify("check the blood pressure and the sats")


# ── a question is not an action ──────────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "what do I do", "what is the pulse", "does the patient have any history",
    "is the pulse better", "how is she breathing", "any medications?",
])
def test_questions_are_recognised_as_questions(said):
    assert is_question(said)
    assert not is_action(said)


@pytest.mark.parametrize("said", [
    "give a nasal cannula at 4 liters", "begin bag-valve mask ventilation",
    "transport rapidly", "open the airway",
])
def test_instructions_are_recognised_as_actions(said):
    assert is_action(said)


def test_a_question_on_a_decision_turn_is_not_answered_done():
    """"what do I do" answered "Done." is how a trainee learns to distrust the sim."""
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    said = ["scene is safe", "what is the pulse", "what do I do"]
    spoken, index = [], 0
    while not session.done and index <= len(said):
        if session.awaiting_input:
            event = session.step(said[index] if index < len(said) else "end call")
            index += 1
        else:
            event = session.step()
        if event.text:
            spoken.append(event.text)
    assert not any(text == "Done." for text in spoken)


def test_an_action_is_acknowledged_by_name():
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    said = ["scene is safe", "check the pulse", "give oxygen by nasal cannula at 4 L/min"]
    spoken, index = [], 0
    while not session.done and index <= len(said):
        if session.awaiting_input:
            event = session.step(said[index] if index < len(said) else "end call")
            index += 1
        else:
            event = session.step()
        if event.text:
            spoken.append(event.text)
    # Was `"Done." in spoken`. Naming the action back is more use to a trainee
    # than the same word five times, and it still claims no physiologic effect.
    assert "Oxygen is running." in spoken


# ── the sim stops repeating itself ───────────────────────────────────────────

def test_nothing_has_changed_is_said_once_not_every_cycle():
    """It was a third of the lines in a real transcript."""
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    spoken, index = [], 0
    said = ["scene is safe"] + ["what about that"] * 8
    while not session.done and index <= len(said):
        if session.awaiting_input:
            event = session.step(said[index] if index < len(said) else "end call")
            index += 1
        else:
            event = session.step()
        if event.text:
            spoken.append(event.text)
    assert spoken.count("Nothing has changed since your last look.") <= 1


def test_a_silent_phase_leaves_no_blank_line_in_the_transcript():
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    index, said = 0, ["scene is safe"] + ["what about that"] * 6
    while not session.done and index <= len(said):
        if session.awaiting_input:
            session.step(said[index] if index < len(said) else "end call")
            index += 1
        else:
            session.step()
    assert all(turn.utterance.strip() for turn in session.turns)


# ── dispatches that give the trainee nothing ─────────────────────────────────

def test_a_dispatch_naming_nobody_is_reported():
    assert "names no person" in problems({}, "## Dispatch\nHead-on motor-vehicle collision.\n")


def test_a_dispatch_with_a_person_but_no_age_is_reported():
    found = problems({}, "## Dispatch\nAdult choking at a restaurant.\n")
    assert "no age or life stage" in found


def test_a_good_dispatch_is_not_reported():
    body = "## Dispatch\n62-year-old man, chest pain and short of breath, conscious.\n"
    assert problems({}, body) == []


def test_a_paediatric_dispatch_is_not_reported():
    body = "## Dispatch\nFour-year-old with difficulty breathing; mother on scene.\n"
    assert problems({}, body) == []


@pytest.mark.parametrize("age", ["One-month-old", "Eight-month-old", "Three-week-old"])
def test_an_infant_aged_in_months_is_not_reported(age):
    """src21-s04 and src21-s05 name an age; only "year-old" was recognized."""
    assert problems({}, f"## Dispatch\n{age} girl, unresponsive in her crib.\n") == []


# ── one input per turn (the ask/decide split is gone) ────────────────────────

def _play(scenario: str, said: list[str]):
    """Every event a call produces, driving the EMT's lines in order."""
    session = Session.from_path(scenarios_dir() / scenario)
    events, index = [], 0
    while not session.done:
        if session.awaiting_input:
            event = session.step(said[index] if index < len(said) else "end call")
            index += 1
        else:
            event = session.step()
        events.append(event)
    return events


def test_a_question_is_never_told_it_was_the_wrong_kind_of_turn():
    """The engine used to alternate ask -> decide regardless of what was typed.

    A question landing on a decision turn was answered "That is a question, not
    an action — nothing was carried out", which describes a cycle the trainee
    cannot see and no real call has. Rachel flagged it as confusing in testing.
    """
    events = _play("src1-s01.md", [
        "scene is safe",
        "what is her name",
        "how long has she been like this",
        "check the pulse",
    ])
    spoken = " ".join(e.text for e in events)
    assert "not an action" not in spoken
    assert "nothing was carried out" not in spoken


def test_only_one_phase_ever_waits_for_the_emt():
    events = _play("src1-s01.md", ["scene is safe", "check the pulse"])
    waiting = {e.phase for e in events if e.awaiting_input}
    assert waiting == {"SIZE_UP", "TURN"}


def test_a_question_earns_an_answer_and_no_result():
    events = _play("src1-s01.md", ["scene is safe", "what is her name"])
    after = [e.phase for e in events if e.phase in ("ANSWER", "RESULT")]
    assert "ANSWER" in after and "RESULT" not in after


def test_an_action_earns_a_result_and_no_patient_reply():
    events = _play("src1-s01.md", ["scene is safe", "give oxygen by nonrebreather at 15 L/min"])
    after = [e.phase for e in events if e.phase in ("ANSWER", "RESULT")]
    assert "RESULT" in after and "ANSWER" not in after


def test_one_breath_that_acts_and_asks_earns_both():
    """A real EMT says "gloves are on, what's his name?" in one breath."""
    events = _play("src1-s01.md", [
        "scene is safe",
        "I'm putting on gloves, and what is her name?",
    ])
    after = [e.phase for e in events if e.phase in ("ANSWER", "RESULT")]
    assert "RESULT" in after and "ANSWER" in after


# ── the patient stops reciting the textbook ──────────────────────────────────

def test_an_absence_is_reported_by_the_narrator_not_the_patient():
    """"Nothing about that stands out" is an observation, not something the
    patient can claim — putting it in their mouth invents a clinical assertion
    the scenario never made."""
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    while session._answers:
        session._answers.pop()
    speaker, text = session._canned_answer("what is her name")
    assert speaker == "narrator" and text == "Nothing further stands out."


def test_the_patient_never_narrates_the_scene_about_themselves():
    """Found by playing gen-20260818-01: the patient said "She is on a chair
    just inside the restaurant doorway" — about herself.

    Blocking second-person frames fixed half of this. The other half is that
    `## Presentation` is arrival narration in the third person, so none of it is
    something a patient says. An LLM persona speaks in the first person and is
    still attributed to `patient`; the deterministic fallback is description.
    """
    events = _play("src1-s01.md", [
        "scene is safe", "what happened", "what does she look like", "tell me more",
    ])
    for event in events:
        if event.speaker == "patient":
            assert not event.text.startswith(("She ", "He ", "They ", "A patient", "The patient"))


# ── ending it, the second time round ─────────────────────────────────────────

@pytest.mark.parametrize("said", [
    "end of scene", "end scene", "stop", "quit", "exit",
    "end the sim", "end the simulation", "end this session",
    "scene complete", "sim is over", "end of",
])
def test_the_other_words_people_reach_for_also_end_it(said):
    """Rachel typed "end of scene", then "end scene", then "stop" — and got
    "Done." three times, because every branch required the literal word "call".
    """
    assert is_end_of_call(said)


@pytest.mark.parametrize("said", [
    "end tidal CO2 is rising",
    "I want to end the bleeding",
    "recommend calling ALS",
    "send the call sheet with the patient",
    "stop the bleeding with direct pressure",
])
def test_widening_it_did_not_swallow_clinical_lines(said):
    assert not is_end_of_call(said)


def test_a_missed_attempt_to_stop_is_offered_the_way_out():
    """A regex will always miss a phrasing, so the failure has to be helpful.

    Answering "Done." says the sim carried something out, which is what sent a
    trainee through three variants in a row.
    """
    from ems.sim.session import looks_like_stopping

    assert looks_like_stopping("ok all finished up here") is True
    events = _play("src1-s01.md", ["scene is safe", "ok all finished up here"])
    spoken = " ".join(e.text for e in events)
    assert 'Say "end of call"' in spoken


@pytest.mark.parametrize("said", [
    "I want to end the bleeding",
    "stop the bleeding with direct pressure",
    "stop compressions",
    "stop ventilating",
    "end tidal CO2 is rising",
])
def test_a_clinical_order_is_never_answered_with_advice_on_quitting(said):
    """These have the same shape as "ok all finished up here", and the intent
    table does not recognize "end the bleeding" either — the clinical object is
    what separates them. Telling someone how to quit when they ordered
    hemorrhage control is worse than the "Done." this replaced."""
    from ems.sim.session import looks_like_stopping

    assert not looks_like_stopping(said)
