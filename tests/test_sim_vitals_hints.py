"""
Generated vitals and hint nudges.
Deterministic and offline: the fill is seeded, the hints are a lookup table.
"""
import pytest

from ems.paths import scenarios_dir
from ems.sim.hints import HINT_FOR_INTENT, hint_for_session, next_hint
from ems.sim.scene import Vitals
from ems.sim.session import Session
from ems.sim.vitals import generate, load_profiles, profile_for

PROFILES = load_profiles()


# ── generated vitals ─────────────────────────────────────────────────────────

def test_a_stated_vital_is_never_overwritten():
    stated = Vitals(rr=36, spo2=82)
    filled, generated = generate(stated, conditions=("asthma",), seed="x")
    assert (filled.rr, filled.spo2) == (36, 82)
    assert "rr" not in generated and "spo2" not in generated


def test_the_blanks_get_filled_and_flagged():
    filled, generated = generate(Vitals(), conditions=("asthma",), seed="x")
    assert generated == frozenset({"rr", "hr", "spo2", "bp"})
    assert filled.rr is not None and "/" in filled.bp


def test_the_same_scenario_always_has_the_same_numbers():
    first, _ = generate(Vitals(), conditions=("sepsis",), seed="src1-s02")
    second, _ = generate(Vitals(), conditions=("sepsis",), seed="src1-s02")
    assert first == second


def test_different_scenarios_get_different_numbers():
    a, _ = generate(Vitals(), conditions=("sepsis",), seed="src1-s02")
    b, _ = generate(Vitals(), conditions=("sepsis",), seed="src12-s07")
    assert a != b


def test_the_condition_drives_the_numbers():
    """An opioid overdose must not present with a textbook respiratory rate."""
    overdose, _ = generate(Vitals(), conditions=("opioid-overdose",), seed="s")
    healthy, _ = generate(Vitals(), conditions=(), seed="s")
    assert overdose.rr < healthy.rr
    assert overdose.spo2 < healthy.spo2


def test_age_changes_the_baseline():
    """A slow pulse for an adult is not a slow pulse for a neonate."""
    neonate, _ = generate(Vitals(), conditions=(), age_group="neonate", seed="s")
    adult, _ = generate(Vitals(), conditions=(), age_group="adult", seed="s")
    assert neonate.hr > adult.hr
    assert neonate.rr > adult.rr


def test_the_first_matching_condition_wins():
    ranges = profile_for(("chest-pain", "acute-mi"), "adult", PROFILES)
    assert ranges["rr"] == PROFILES["conditions"]["chest-pain"]["rr"]


def test_an_unknown_condition_falls_back_to_the_age_baseline():
    ranges = profile_for(("not-a-real-slug",), "pediatric", PROFILES)
    assert ranges == PROFILES["baseline"]["pediatric"]


def test_every_baseline_is_a_real_age_group():
    """A key that is not an age_group hands every such patient the adult ranges."""
    from ems.vocabulary import load_vocabulary
    allowed = set(load_vocabulary().get("age_groups", []))
    assert set(PROFILES["baseline"]) == allowed


def test_every_condition_profile_is_a_real_condition_slug():
    from ems.vocabulary import load_vocabulary
    allowed = set(load_vocabulary().get("conditions", []))
    assert set(PROFILES["conditions"]) <= allowed


def test_every_profile_key_is_a_vital_the_monitor_shows():
    allowed = {"rr", "hr", "spo2", "sbp", "dbp"}
    for name, ranges in PROFILES["conditions"].items():
        assert set(ranges) <= allowed, f"{name} sets something the monitor cannot show"


def test_every_range_is_low_then_high():
    for group in (PROFILES["baseline"], PROFILES["conditions"], PROFILES["findings"]):
        for name, ranges in group.items():
            for key, span in ranges.items():
                if span is None:
                    continue          # "do not invent this one"
                low, high = span
                assert low <= high, f"{name}.{key} is inverted"


def test_a_generated_blood_pressure_is_never_upside_down():
    """BP 6/19 is not a low blood pressure, it is a broken one."""
    for seed in range(60):
        for condition in ("hemorrhagic-shock", "cardiogenic-shock", "anaphylaxis", ""):
            filled, _ = generate(
                Vitals(), conditions=(condition,) if condition else (), seed=str(seed)
            )
            if not filled.bp:
                continue
            systolic, diastolic = (int(n) for n in filled.bp.split("/"))
            assert diastolic < systolic, f"{filled.bp} from {condition or 'baseline'}"
            assert systolic > 0 and diastolic > 0


def test_a_pulseless_patient_gets_no_invented_blood_pressure():
    """You cannot take a BP off an apneic pulseless patient. Blank is the truth."""
    filled, generated = generate(Vitals(), conditions=(), seed="x", effort="apneic")
    assert filled.rr == 0
    assert filled.bp is None and filled.hr is None
    assert "bp" not in generated and "hr" not in generated


def test_the_scenarios_own_words_outrank_its_condition_slug():
    """An apneic asthmatic is apneic, whatever the asthma profile says."""
    filled, _ = generate(Vitals(), conditions=("asthma",), seed="x", effort="apneic")
    assert filled.rr == 0


def test_inadequate_breathing_does_not_read_as_adequate():
    """The judgement the author wrote has to reach the numbers."""
    filled, _ = generate(Vitals(), conditions=(), seed="x", effort="inadequate-breathing")
    assert filled.rr <= 10
    assert filled.spo2 <= 90


def test_inadequate_breathing_is_deliberately_not_a_drawable_effort():
    """It is a conclusion, not an observation — the figure must not assert it."""
    from ems.sim.scene import EFFORT_STATES
    assert "inadequate-breathing" not in EFFORT_STATES


# ── the answer has to match the question ─────────────────────────────────────

def _asked(session, question):
    """Just the words. `_canned_answer` returns (speaker, text) — the speaker
    matters (the narrator says what the patient cannot claim) and is asserted
    separately in test_the_narrator_not_the_patient_reports_an_absence."""
    return session._canned_answer(question)[1]


def test_asking_about_one_vital_never_returns_another():
    """The reported bug: "check the child's SpO2" answered about the pulse."""
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    session._answers = [
        "When you assess the pulse, it is slow for the child's age.",
        "Her oxygen saturation is 84 percent on room air.",
    ]
    assert "saturation" in _asked(session, "check the child's spo2")


def test_a_vital_question_with_no_answer_says_so():
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    session._answers = ["When you assess the pulse, it is slow for the child's age."]
    assert _asked(session, "what is her blood pressure") == "Nothing about that stands out."


def test_prose_that_names_no_vital_still_answers_anything():
    """Most of the corpus is description, and description answers most questions."""
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    session._answers = ["She is slumped in a chair with bluish lips."]
    assert "slumped" in _asked(session, "what is her pulse")


def test_answers_are_still_consumed_in_order_when_nothing_is_asked_about():
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    session._answers = ["First thing.", "Second thing."]
    assert _asked(session, "what do you see") == "First thing."
    assert _asked(session, "anything else") == "Second thing."


def test_running_out_of_answers_is_graceful():
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    session._answers = []
    assert _asked(session, "anything else") == "Nothing further stands out."


# ── hints ────────────────────────────────────────────────────────────────────

def test_a_hint_never_quotes_the_answer_key():
    """A hint that echoes the rubric grades the trainee on reading."""
    rubric = ("Begin assisted ventilation with a bag-valve mask at 15 L/min",)
    hint = next_hint(rubric, ())
    assert hint is not None
    assert "bag-valve" not in hint.lower()
    assert "15" not in hint


def test_the_hint_moves_on_once_the_step_is_taken():
    rubric = ("Open the airway", "Begin bag-valve mask ventilation at 15 L/min")
    first = next_hint(rubric, ())
    second = next_hint(rubric, ("I open the airway with a head-tilt chin-lift",))
    assert first != second


def test_nothing_left_to_do_is_no_hint():
    rubric = ("Open the airway",)
    assert next_hint(rubric, ("I open the airway with a head-tilt chin-lift",)) is None


def test_an_empty_rubric_gives_no_hint():
    assert next_hint((), ()) is None


def test_the_most_urgent_missing_step_comes_first():
    """Airway outranks history, whatever order the rubric happens to be in."""
    rubric = ("Take a SAMPLE history", "Open the airway")
    assert next_hint(rubric, ()) == dict(HINT_FOR_INTENT)["airway-open"]


def test_hints_read_off_a_live_session():
    session = Session.from_path(scenarios_dir() / "src1-s01.md")
    assert hint_for_session(session)


@pytest.mark.parametrize("intent,hint", HINT_FOR_INTENT)
def test_every_hint_is_a_question_or_a_direction_not_an_instruction(intent, hint):
    """Hints point; they do not tell. A hint ending in a flow rate is a leak."""
    assert hint and hint[0].isupper()
    assert not any(ch.isdigit() for ch in hint), f"{intent} hint leaks a number"


#: Each assessment intent and the word its hint must actually say. Forgetting
#: one of these *is* the failure being nudged, so naming it gives nothing away —
#: and a hint the trainee has to decode is a hint that does not land.
NAMED_ASSESSMENTS = {
    "vitals-bp": "blood pressure",
    "vitals-spo2": "oxygen saturation",
    "glucose-check": "blood glucose",
    "pulse-check": "pulse",
    "breathing-assess": "breathing",
    "sample-history": "history",
    "reassess": "reassess",
}


@pytest.mark.parametrize("intent,word", NAMED_ASSESSMENTS.items())
def test_an_assessment_hint_names_what_is_missing(intent, word):
    assert word in dict(HINT_FOR_INTENT)[intent].lower()


@pytest.mark.parametrize("intent", ("oxygen", "oxygen-nrb", "oxygen-bvm", "medication-assist"))
def test_a_treatment_hint_still_withholds_its_parameters(intent):
    """The device, rate, dose and route are what the rubric scores."""
    hint = dict(HINT_FOR_INTENT)[intent].lower()
    for leak in ("nonrebreather", "nasal cannula", "bag-valve", "l/min",
                 "epinephrine", "aspirin", "naloxone", "nitroglycerin"):
        assert leak not in hint, f"{intent} hint names {leak}"


# ── arrest intents on a patient who has a pulse ──────────────────────────────

#: The shape that froze 14 of the playable cases: one rubric line that confirms
#: a pulse *and* names what to do without one.
_BRANCH_LINE = (
    "Confirm a pulse is present — a patient without one needs CPR and "
    "defibrillation, not an antidote"
)


def test_a_conditional_arrest_line_does_not_freeze_the_hints():
    rubric = (_BRANCH_LINE, "Take a blood pressure")
    said = ("I check for a carotid pulse",)
    assert next_hint(rubric, said, pulse_present=True) == \
        dict(HINT_FOR_INTENT)["vitals-bp"]


def test_the_arrest_hint_survives_when_there_is_no_pulse():
    """The fix must not silence CPR on the one call that needs it."""
    rubric = (_BRANCH_LINE,)
    assert next_hint(rubric, (), pulse_present=False) == \
        dict(HINT_FOR_INTENT)["cpr"]


def test_an_unknown_pulse_drops_nothing():
    rubric = (_BRANCH_LINE,)
    assert next_hint(rubric, ()) == dict(HINT_FOR_INTENT)["cpr"]


# ── a number on the monitor is not a number still missing ────────────────────

_VITALS_LINE = ("Take a full set of baseline vital signs including a blood pressure",)
_FULL_SET = frozenset({"rr", "hr", "spo2", "bp"})


def test_asking_for_all_vitals_satisfies_the_blood_pressure():
    """Reported from a call: the hint asked for a pressure already displayed."""
    assert next_hint(_VITALS_LINE, ("get all vitals",), on_monitor=_FULL_SET) is None


def test_the_same_bug_in_the_other_direction():
    """One reading is not a full set, so the full-set nudge is still right."""
    assert next_hint(_VITALS_LINE, ("take a blood pressure",),
                     on_monitor=frozenset({"bp"})) == \
        dict(HINT_FOR_INTENT)["vitals-full"]


def test_an_empty_monitor_changes_nothing():
    assert next_hint(_VITALS_LINE, ()) == dict(HINT_FOR_INTENT)["vitals-full"]


def test_the_monitor_satisfies_whatever_words_earned_it():
    """However the reading was asked for, having it is having it."""
    for utterance in ("get all vitals", "what is her pressure", "full set please"):
        assert next_hint(("Obtain a blood pressure",), (utterance,),
                         on_monitor=frozenset({"bp"})) is None

