"""
Tests for the deterministic grader (Project 2).
Fully offline — no LLM anywhere in this path by design.
"""
import pytest

from ems.sim import grade as G
from ems.sim.intents import classify, flow_rate, prohibited_intents

# A miniature answer key in the same shape the real scenario files use.
BODY = """
## Dispatch
58-year-old female, difficulty breathing.

## Presentation
Slumped in a recliner, dusky lips, one-word speech, becoming drowsy.

## Vitals
RR 36 shallow, HR 118, SpO2 82%, cyanotic.

## Correct actions
1. Take standard precautions and ensure the scene is safe before approaching.
2. Recognize inadequate breathing and begin assisted ventilation with a bag-valve mask
   connected to supplemental oxygen at 15 L/min with a reservoir bag.
3. Ventilate at about 10 breaths/minute, only until the chest just begins to rise.
4. Do NOT assist the inhaler — she is not alert enough to use it.
5. Call ALS and transport without delay, reassessing chest rise and pulse.

## Rationale
Respiratory failure needs positive pressure ventilation.

## Red flags
- Cyanosis
- One-word dyspnea
- Declining mental status
- SpO2 82%
"""

FRONTMATTER = {"scenario_id": "test-s01", "citations": ["[SRC-19:p541]"]}


# ── the intent table ─────────────────────────────────────────────────────────

def test_classify_separates_oxygen_devices():
    assert "oxygen-nrb" in classify("put her on a non-rebreather at 15 liters per minute")
    assert "oxygen-bvm" in classify("start bagging her with a BVM at 15 L/min")
    assert "oxygen-nc" in classify("nasal cannula at 4 lpm")


def test_naming_a_device_implies_oxygen():
    assert "oxygen" in classify("non-rebreather at 15 L/min")


def test_flow_rate_parses_common_phrasings():
    assert flow_rate("15 L/min") == 15
    assert flow_rate("15 liters per minute") == 15
    assert flow_rate("oxygen at 4 liters") == 4
    assert flow_rate("give her some oxygen") is None


def test_prohibition_only_when_the_negation_opens_the_line():
    forbidden = prohibited_intents("Do NOT assist the inhaler — she is not alert enough.")
    assert "medication-assist" in forbidden

    # "Do not wait" is an instruction to act, not a prohibition on ventilating.
    assert not prohibited_intents(
        "Do not wait — immediately begin positive pressure ventilation with a BVM."
    )
    # A mid-line negation is guidance, not a prohibition.
    assert not prohibited_intents("Recognize hypoxia and do NOT withhold oxygen.")


# ── size-up ──────────────────────────────────────────────────────────────────

def test_size_up_scores_all_five():
    result = G.grade_size_up(
        "Scene is safe, I'm in gloves and eye protection, one patient only, "
        "nature of illness is respiratory distress, no additional resources needed."
    )
    assert result.score == 5
    assert result.missed == ()


def test_size_up_gives_partial_credit_when_bsi_is_omitted():
    result = G.grade_size_up(
        "The scene is safe, single patient, nature of the illness is trouble breathing, "
        "I'll request additional resources."
    )
    assert result.score == 4
    assert result.missed == ("bsi",)


# ── action matching ──────────────────────────────────────────────────────────

def test_wrong_oxygen_device_is_a_partial_not_a_hit():
    actions = G.parse_actions(BODY)
    results = G.grade_actions(["I'll put her on a non-rebreather at 15 liters"], actions)
    ventilation = results[1]
    assert ventilation.status == "partial"
    assert "NRB" in ventilation.note and "BVM" in ventilation.note


def test_correct_device_and_flow_is_a_hit():
    actions = G.parse_actions(BODY)
    results = G.grade_actions(
        ["Start BVM ventilation with oxygen at 15 L/min with a reservoir"], actions
    )
    assert results[1].status == "hit"


def test_each_turn_is_consumed_by_at_most_one_action():
    actions = G.parse_actions(BODY)
    results = G.grade_actions(["BVM at 15 L/min with a reservoir"], actions)
    matched = [r.matched_turn for r in results if r.matched_turn is not None]
    assert matched == [0]


def test_out_of_order_is_counted():
    actions = G.parse_actions(BODY)
    results = G.grade_actions(
        [
            "Call ALS and transport now",                        # step 5 said first
            "BVM at 15 L/min with a reservoir",                  # step 2 said second
        ],
        actions,
    )
    assert G.count_out_of_order(results) >= 1


# ── critical errors ──────────────────────────────────────────────────────────

def test_bvm_without_a_flow_rate_is_critical():
    grade = G.grade_deterministic(
        FRONTMATTER, BODY, "scene is safe, gloves on",
        ["Start bagging her with a BVM", "Ventilate at 10 breaths per minute",
         "Call ALS and transport"],
    )
    rules = {e.rule for e in grade.critical_errors}
    assert "oxygen-flow-missing" in rules


def test_oxygen_without_a_device_is_critical():
    errors = G.find_critical_errors(["Give her oxygen"], (), ())
    assert [e.rule for e in errors] == ["oxygen-device-missing"]


def test_flow_rate_outside_the_device_range_is_critical():
    errors = G.find_critical_errors(["Non-rebreather at 4 L/min"], (), ())
    assert [e.rule for e in errors] == ["oxygen-flow-out-of-range"]


def test_naming_device_and_flow_correctly_raises_no_oxygen_error():
    for utterance in (
        "nasal cannula at 4 L/min",
        "non-rebreather at 15 liters per minute",
        "BVM at 15 L/min with a reservoir",
    ):
        assert G.find_critical_errors([utterance], (), ()) == ()


def test_doing_what_the_scenario_forbids_is_critical():
    actions = G.parse_actions(BODY)
    errors = G.find_critical_errors(["I'll assist her with her inhaler"], actions, ())
    assert "contraindicated-action" in {e.rule for e in errors}


def test_a_forbidden_step_is_scored_inverted():
    """Step 4 is "Do NOT assist the inhaler" — you pass it by not doing it."""
    actions = G.parse_actions(BODY)

    avoided = G.grade_actions(["BVM at 15 L/min with a reservoir"], actions)[3]
    assert avoided.status == "hit" and avoided.note == "correctly avoided"

    violated = G.grade_actions(["I'll assist her with her inhaler"], actions)[3]
    assert violated.status == "missed"


def test_violating_a_prohibition_earns_no_partial_credit_for_it():
    """Doing the forbidden thing must not score points and a critical error at once."""
    grade = G.grade_deterministic(
        FRONTMATTER, BODY, "scene is safe, gloves on",
        ["I'll assist her with her inhaler"],
    )
    inhaler_step = grade.actions[3]
    assert inhaler_step.status == "missed"
    assert "contraindicated-action" in {e.rule for e in grade.critical_errors}
    # …and it is not double-reported as a plain omission.
    assert sum(1 for e in grade.critical_errors if "inhaler" in e.detail) == 1


def test_missing_the_ventilation_step_is_a_critical_omission():
    grade = G.grade_deterministic(
        FRONTMATTER, BODY, "scene is safe, gloves on", ["Call ALS and transport"]
    )
    assert "critical-omission" in {e.rule for e in grade.critical_errors}


# ── the whole grade ──────────────────────────────────────────────────────────

def test_a_clean_call_scores_well_with_no_critical_errors():
    grade = G.grade_deterministic(
        FRONTMATTER, BODY,
        "Scene is safe, gloves and eye protection on, one patient, nature of illness is "
        "respiratory failure, I want ALS for additional resources.",
        [
            "She's cyanotic, one-word dyspnea, mental status is declining, SpO2 82 — "
            "breathing is inadequate",
            "Begin assisted ventilation with a bag-valve mask on oxygen at 15 L/min "
            "with a reservoir bag",
            "Ventilate at about 10 breaths per minute, just to chest rise",
            "Call ALS and transport, reassessing chest rise and pulse",
        ],
    )
    assert grade.critical_errors == ()
    assert grade.points >= 0.7 * grade.points_possible
    assert grade.passed
    assert grade.red_flags_missed == ()
    assert grade.turns_to_first_intervention == 2


def test_an_empty_call_earns_nothing_and_is_not_scored_out_of_its_prohibitions():
    """Saying nothing earns nothing, and the "Do NOT" step is not on the sheet.

    Doing nothing satisfies every prohibition a rubric contains, and each was
    worth two points, so silence collected credit for the forbidden things it
    had not got round to doing. A prohibition is a criterion rather than a
    skill — the same shape as a critical error, which is what breaking one
    already produces — so it leaves the arithmetic on *both* sides: 15 possible
    becomes 13, and the free 2 points are gone.
    """
    grade = G.grade_deterministic(FRONTMATTER, BODY, "", [])
    assert grade.points == 0
    assert grade.points_possible == 13
    assert not grade.passed
    assert grade.size_up.score == 0
    # The prohibition is still reported as vacuously passed, so the trainee sees
    # the line existed and was not breached — it just earns nothing.
    assert [r.status for r in grade.actions] == ["missed", "missed", "missed", "hit", "missed"]
    assert grade.turns_to_first_intervention is None


@pytest.mark.parametrize("section,parser,expected", [
    ("Correct actions", G.parse_actions, 5),
    ("Red flags", G.parse_red_flags, 4),
])
def test_answer_key_parsing(section, parser, expected):
    assert len(parser(BODY)) == expected


# ── one intent, several steps ────────────────────────────────────────────────

_HISTORY_RUBRIC = (
    "Obtain a SAMPLE history and take baseline vital signs",
    "Ask specifically about any previous allergic reactions that required "
    "medical treatment, and about prior severe airway problems",
)


def test_a_generic_history_does_not_hit_the_specific_history_step():
    """Reported from a call: credited for a question that was never asked.

    Both lines classify as the single intent `sample-history`, so intent
    overlap alone scored the specific line a full hit.
    """
    results = G.grade_actions(
        ["take the patient's sample history like allergies and medication"],
        _HISTORY_RUBRIC,
    )
    assert results[1].status == "partial"


def test_a_unique_step_is_not_punished_for_the_rubric_s_prose():
    """The mirror risk: rubric lines carry rationale no EMT would say aloud.

    Nothing else in this rubric is an oxygen step, so the intent identifies it
    and the words do not have to.
    """
    rubric = (
        "Administer high-concentration oxygen by nonrebreather mask at "
        "12-15 L/min, since she is in distress and appears to be having an "
        "anaphylactic reaction",
    )
    results = G.grade_actions(["give oxygen by non-rebreather at 15 liters per minute"], rubric)
    assert results[0].status == "hit"


def test_the_specific_step_is_reachable_by_actually_asking_it():
    results = G.grade_actions(
        ["have you ever had a previous allergic reaction that needed treatment"],
        _HISTORY_RUBRIC,
    )
    assert results[1].status == "hit"


# ── time-critical steps done late ────────────────────────────────────────────

_EPI_THEN_HISTORY = (
    "Administer epinephrine by autoinjector into the lateral thigh",
    "Obtain a SAMPLE history from the patient and any bystanders",
)


def test_a_time_critical_step_done_late_is_not_a_full_hit():
    """Reported: "giving epi should be BEFORE taking the history."

    Expressed by position — the rubric's numbering is the order the call should
    run in — rather than by a "do not delay" line the grader cannot read.
    """
    results = G.grade_actions(
        ["take a sample history", "give the epipen in the thigh"], _EPI_THEN_HISTORY
    )
    assert results[0].status == "partial"
    assert "after steps that should have waited" in results[0].note


def test_the_same_two_steps_in_the_right_order_are_both_hits():
    results = G.grade_actions(
        ["give the epipen in the thigh", "take a sample history"], _EPI_THEN_HISTORY
    )
    assert [r.status for r in results] == ["hit", "hit"]


def test_order_only_binds_the_time_critical_step():
    """A history taken late is not an error; adrenaline taken late is."""
    results = G.grade_actions(
        ["give the epipen in the thigh", "take a sample history"], _EPI_THEN_HISTORY
    )
    assert results[1].status == "hit"


# ── ventilating on room air is an order to give no oxygen ────────────────────


@pytest.mark.parametrize("said", [
    "Begin positive pressure ventilations with a neonate bag-valve mask using room air.",
    "Ventilate with a neonate bag-valve mask on room air at 40 breaths per minute.",
    "Bag him on room air until the heart rate comes up.",
])
def test_room_air_ventilation_is_not_a_missing_flow_rate(said):
    """Neonatal resuscitation starts on room air, and the grader used to fail it.

    Source 36 says it is not necessary to attach supplemental oxygen to the
    bag-valve mask during the initial stages, and to consider oxygen only if
    saturation stays low afterward. The flow-rate rule read that as an oxygen
    order with no number and charged a critical error — which, since a critical
    error fails the call outright, failed every trainee who got it right.
    """
    assert G.find_critical_errors([said], (), ()) == ()


@pytest.mark.parametrize("said,rule", [
    ("He's 90% on room air, put him on a nonrebreather.", "oxygen-flow-missing"),
    ("His sat is 88 on room air. Give oxygen.", "oxygen-device-missing"),
])
def test_room_air_as_a_finding_does_not_excuse_a_real_oxygen_error(said, rule):
    """"On room air" is how the corpus reports a saturation, in scores of lines.

    The exemption is anchored to the ventilation clause precisely so that
    mentioning it as a finding cannot suppress the error on the order that
    follows it.
    """
    assert [e.rule for e in G.find_critical_errors([said], (), ())] == [rule]


# ── getting equipment out is not using it ───────────────────────────────────


@pytest.mark.parametrize("said", [
    "Have a bag-valve mask ready to connect directly to the trach tube.",
    "Have suction and a BVM ready.",
    "Keep a nonrebreather within reach.",
])
def test_preparing_a_device_is_not_an_oxygen_order(said):
    """"Have a BVM ready" named a device with no flow rate and failed the call.

    Same shape as the room-air defect, and found the same way — by running a
    phrase through the grader before putting it in a scenario. Readiness is not
    administration, and a critical error fails the station outright.
    """
    assert G.find_critical_errors([said], (), ()) == ()


@pytest.mark.parametrize("said", [
    "Put her on a nonrebreather.",
    "Have a BVM ready and put him on a nonrebreather.",
    "Bag him with a BVM.",
])
def test_readiness_wording_does_not_excuse_an_actual_order(said):
    """The exemption lifts the moment an administration verb appears.

    The middle case is the one that matters: a sentence can prepare one device
    and order another, and the order still has to name its flow rate.
    """
    assert [e.rule for e in G.find_critical_errors([said], (), ())] == ["oxygen-flow-missing"]
