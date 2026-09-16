"""The debrief has to teach, not just score.

Rachel, after two sessions: "This simulation isn't educational because it
doesn't tell me the correct steps in the debrief" and "the debrief doesn't tell
me the proper action and steps."

The data was mostly there; what was missing was the reasoning, the trainee's own
words, and any plain-English account of the call.
"""
import pytest

from ems.paths import scenarios_dir
from ems.sim.grade import CriticalError, SizeUpResult, ActionResult, summarize
from ems.sim.session import Session


@pytest.fixture(scope="module")
def graded():
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    said = [
        "BSI scene is safe one patient",
        "what is the respiratory rate pulse ox and blood pressure",
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
    return session.grade()


def test_the_debrief_opens_with_a_sentence_not_a_number(graded):
    assert graded.summary
    assert "key steps" in graded.summary


def test_the_scenario_reasoning_reaches_the_debrief(graded):
    """Every scenario has a `## Rationale` explaining why. It was never shown."""
    assert graded.rationale
    assert len(graded.rationale) > 80


def test_the_score_can_be_argued_with(graded):
    labels = [row[0] for row in graded.breakdown]
    assert labels[:2] == ["Scene size-up", "Correct actions"]
    for _, earned, possible in graded.breakdown:
        assert isinstance(earned, int) and isinstance(possible, int)


def test_red_flags_are_reported_but_not_scored(graded):
    """Catching one meant saying it aloud, which no EMT does on a real call.

    Reported by a reviewer: "in real life, an EMT wouldn't say these things out
    loud, they would just have to be taken into account." The points were
    measuring a speech habit, so they are gone — the flags stay in the debrief
    as what the call turned on.
    """
    assert not any(row[0].startswith("Red flags") for row in graded.breakdown)
    assert graded.red_flags_caught or graded.red_flags_missed, "still reported"


def test_a_hit_shows_the_words_that_earned_it(graded):
    """Told a step was hit but not by what, a trainee cannot learn what counted."""
    hits = [a for a in graded.actions if a.status == "hit" and a.matched_turn is not None]
    assert hits, "expected at least one matched step"
    assert all(a.said for a in hits)


def test_a_critical_error_says_what_to_do_instead():
    """The debrief showed the bare slug `oxygen-device-missing`."""
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    said = ["scene is safe", "give him oxygen", "end of call"]
    index = 0
    while not session.done:
        if session.awaiting_input:
            session.step(said[index] if index < len(said) else "end of call")
            index += 1
        else:
            session.step()
    errors = session.grade().critical_errors
    assert errors and all(e.guidance for e in errors)
    assert "nasal cannula" in errors[0].guidance


def test_the_summary_names_what_the_size_up_left_out():
    result = summarize(
        SizeUpResult(covered=("scene-safety",),
                     missed=("bsi", "patient-count", "moi-noi", "additional-resources")),
        (ActionResult(index=1, action="Give oxygen.", status="hit"),),
        (),
    )
    assert "your precautions" in result
    assert "how many patients" in result


def test_the_summary_leads_with_the_step_that_matters_most():
    result = summarize(
        SizeUpResult(covered=tuple(), missed=tuple()),
        (
            ActionResult(index=1, action="Open the airway.", status="missed"),
            ActionResult(index=2, action="Give oxygen.", status="missed"),
        ),
        (),
    )
    assert "Open the airway." in result


def test_a_critical_error_is_called_out_in_the_summary():
    result = summarize(
        SizeUpResult(covered=tuple(), missed=tuple()),
        (ActionResult(index=1, action="Give oxygen.", status="hit"),),
        (CriticalError("oxygen-device-missing", "detail", "guidance"),),
    )
    assert "1 critical error" in result
