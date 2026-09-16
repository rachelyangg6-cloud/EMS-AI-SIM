import pytest

from ems.sim.intents import classify, is_action, is_question, spoken_intents


def test_reading_a_medical_id_counts_as_examining_the_patient():
    """Reported from a call: the trainee read the bracelet and got no credit.

    Nothing in the table matched medical ID jewelry, an insulin pump or a
    glucose meter, so looking the patient over for what they are wearing was
    invisible — on a hypoglycemia call where the bracelet was the point.
    """
    for utterance in (
        "check what the medical ID bracelet says",
        "look for a medical alert bracelet",
        "does she have an insulin pump",
        "is there a glucose meter anywhere",
    ):
        assert "physical-exam" in classify(utterance), utterance


def test_the_book_s_phrasings_reach_the_intents_they_mean():
    """The table was written from paraphrase; the corpus quotes the resource.

    Each line below appeared in an approved scenario and carried no intent at
    all, which means it was graded on bare word overlap and could never surface
    as a hint — a trainee who did the right thing was marked down for it.
    """
    for line, intent in (
        ("Listen to both sides of the chest.", "breathing-assess"),
        ("Ask about vomiting with blood or coffee-ground material.", "sample-history"),
        ("Examine the head for the swelling and any other injury.", "physical-exam"),
        ("Assess the neck for wounds, tenderness and deformity.", "physical-exam"),
        ("Monitor her airway continuously en route.", "reassess"),
        ("Immediately request an additional ambulance.", "additional-resources"),
        ("Keep reassuring the patient.", "explain-to-patient"),
    ):
        assert intent in classify(line), f"{line!r} should carry {intent}"


def test_being_reassured_by_a_reading_is_not_reassuring_a_patient():
    """`reassur\\w*` is too greedy, and the difference is clinical.

    "Do not be reassured by the 99% reading" is a caution about pulse oximetry
    reading falsely normal in carbon monoxide poisoning. Scoring it as comforting
    the patient would credit a trainee for the opposite of the lesson.
    """
    assert "explain-to-patient" not in classify(
        "Do not be reassured by the 99% reading — pulse oximetry can read "
        "falsely normal in carbon monoxide poisoning."
    )


# ── asking, narrated rather than spoken ──────────────────────────────────────

@pytest.mark.parametrize("line", [
    "ask him if he has any past heart conditions",
    "ask him about his past medical history",
    "ask her whether she has taken her inhaler today",
    "ask the wife what happened before they called",
    "ask if there is any chest pain",
    "find out if he has been outside in the smoke",
    "inquire about allergies",
])
def test_narrating_a_question_counts_as_asking_one(line):
    """A trainee describing the question means the question.

    Found in a real transcript: "ask him if he has any past heart conditions"
    came back "Done." — no interrogative opening word, so it read as an
    instruction and earned a RESULT. RESULT never reaches a persona, so no API
    key could have fixed it; the patient was simply never asked.
    """
    assert is_question(line), f"{line!r} is a question"
    assert not is_action(line), f"{line!r} must not be answered 'Done.'"


@pytest.mark.parametrize("line", [
    "ask for ALS",
    "ask for a second unit",
    "ask dispatch for additional resources",
])
def test_asking_for_something_on_the_radio_is_still_an_action(line):
    """"Ask" is not enough on its own — this is traffic, not a patient question.

    The guard is what may follow, which is why the narrated-ask pattern lists
    its objects instead of accepting anything after the verb.
    """
    assert not is_question(line), f"{line!r} is a request, not a question"


# ── naming a thing is not doing it ───────────────────────────────────────────

def test_a_drug_named_in_a_trailing_clause_was_not_given():
    """The second of two critical errors on a real call, and it was not real.

    "I will check his vitals again after administering nitroglycerin" is a plan
    to reassess. The EMT was charged with assisting with a contraindicated drug
    for a second time because the word was in the sentence.
    """
    said = "I will check his vitals again after administering nitroglycerin"
    assert "medication-assist" in classify(said)          # the word is there
    assert "medication-assist" not in spoken_intents(said)  # the act is not
    assert {"vitals", "vitals-full"} & spoken_intents(said)


@pytest.mark.parametrize("said,intent", [
    ("Give him nitro after you check the blood pressure", "medication-assist"),
    ("assist him with his prescribed nitroglycerin", "medication-assist"),
    ("start CPR when you confirm there is no pulse", "cpr"),
    ("begin ventilation once the airway is open", "ventilate"),
])
def test_an_instruction_survives_its_trailing_clause(said, intent):
    """The main clause is still an order. Nothing may make an act disappear."""
    assert intent in spoken_intents(said)


@pytest.mark.parametrize("said", [
    "After giving nitro, recheck the pressure",
    "Once you have given the epinephrine, reassess",
])
def test_a_clause_initial_reference_is_read_whole(said):
    """No main clause before the marker, so there is nothing to prefer.

    Reading only what precedes "after" would be reading nothing at all.
    """
    assert spoken_intents(said) == classify(said)


def test_a_line_with_no_subordinate_clause_is_untouched():
    for said in ("assist him with his nitroglycerin", "give oxygen by nasal cannula at 4 L/min"):
        assert spoken_intents(said) == classify(said)


# ── word senses that collide across sources ─────────────────────────────────
#
# `classify` is global: every pattern runs against every line in every source.
# So a phrase that means one thing in the source an intent was written for can
# mean something else entirely in a source nobody was looking at. Each case
# below is a real line from the corpus that classified wrongly.


@pytest.mark.parametrize("said,intent", [
    # Source 32 realigns a limb; source 5 uses the phrase for the reference
    # posture anatomy is described from.
    ("Align the injured limbs in the anatomic position", "manual-traction"),
    # Applying a splint, versus listing one among things already on the patient.
    ("Splint the hand and forearm", "splint"),
    ("Apply a padded board splint to the forearm", "splint"),
    ("Secure him to a long spine board so the board serves as a full-body splint", "splint"),
    # Spinal care that never names the anatomy.
    ("Keep manual stabilization until the patient is fully secured", "spinal-motion-restriction"),
    ("Provide manual in-line stabilization of the head and neck", "spinal-motion-restriction"),
    # A genuine distal check.
    ("Check the distal pulse in the left foot", "distal-csm-check"),
    ("Check distal circulation and sensation in the fingers", "distal-csm-check"),
])
def test_the_sense_that_should_match(said, intent):
    assert intent in classify(said)


@pytest.mark.parametrize("said,intent", [
    ("Base the description on anatomic position regardless of how the patient is lying",
     "manual-traction"),
    ("Check all interventions (oxygen, bleeding control, collar/splints) and adjust",
     "splint"),
    ("Perform the detailed head-to-toe exam, working around the splints", "splint"),
    # The tightening this lookahead defends: splinting a forearm is not spinal care.
    ("Manually stabilize the forearm above and below the injury",
     "spinal-motion-restriction"),
    # Source 13 teaches taking a rate here, not checking circulation past an injury.
    ("For a patient 1 year or older, palpate the radial pulse at the wrist",
     "distal-csm-check"),
])
def test_the_sense_that_should_not_match(said, intent):
    assert intent not in classify(said)
