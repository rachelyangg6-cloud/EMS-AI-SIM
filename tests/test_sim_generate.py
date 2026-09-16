"""Project 9 — generated cases, and the review loop that promotes them.

Offline: the LLM is a stub. The two invariants under test are that a model never
authors clinical truth, and that nothing unplayable ever reaches disk.
"""
import pytest

from ems.frontmatter import read_page
from ems.scenarios import list_approved
from ems.sim import generate as gen
from ems.sim import review
from ems.sim.playable import unplayable

GOOD = """## Dispatch
58-year-old woman, severe difficulty breathing, audible wheeze, conscious.

## Presentation
She is sitting bolt upright at the kitchen table, tripoding on her elbows and speaking two words at a time. Her lips have a bluish tinge and she is using her neck muscles to breathe. Her husband says her inhaler has not touched it.

## Vitals
RR 34 and labored, pulse 126, SpO2 86%, BP 148/92; cyanotic lips, accessory muscle use, alert but frightened.

## Correct actions
1. Take Standard Precautions and perform a primary assessment [SRC-10:p271]
2. Administer oxygen by nonrebreather mask at 15 L/min [SRC-10:p279]
3. Assist with her prescribed inhaler per protocol [SRC-10:p282]

## Rationale
Tripoding, one-to-two word dyspnea and a saturation of 86% together mark severe distress [SRC-10:p271].

## Red flags
- Speaking two words at a time
- SpO2 86% with cyanosis
"""

CONTEXT = (
    "[SRC-10:p271] [SRC-10:p279] [SRC-10:p282] "
    "airway breathing oxygen nonrebreather inhaler"
)


def stub(body):
    return lambda prompt, system="": body


@pytest.fixture
def quarantine(tmp_path):
    return tmp_path / "generated"


# ── nothing unplayable reaches disk ──────────────────────────────────────────

def test_a_good_draft_passes_every_check():
    drafted = gen.draft(["asthma"], llm=stub(GOOD), context=CONTEXT, lessons="")
    assert drafted.playable and drafted.problems == ()


@pytest.mark.parametrize("mangled,expected", [
    (GOOD.replace("58-year-old woman, severe difficulty breathing, audible wheeze, conscious.",
                  "Difficulty breathing call."),
     "dispatch"),
    (GOOD.replace("She is sitting bolt upright", "You are assessing a patient sitting bolt upright"),
     "teaching frame"),
    (GOOD.replace("RR 34 and labored, pulse 126, SpO2 86%, BP 148/92;", "She looks unwell;"),
     "vitals"),
    (GOOD.replace("nonrebreather mask at 15 L/min", "oxygen"), "oxygen step"),
])
def test_a_bad_draft_is_never_written(mangled, expected, quarantine):
    with pytest.raises(gen.GenerationFailed) as failure:
        gen.draft(["asthma"], llm=stub(mangled), context=CONTEXT, lessons="", max_attempts=2)
    assert any(expected in problem for problem in failure.value.problems)
    assert not quarantine.exists(), "a failed generation must write nothing"


def test_save_refuses_an_unplayable_draft(quarantine):
    bad = gen.Draft(body="## Dispatch\nnothing\n", problems=("dispatch names no person",))
    with pytest.raises(ValueError, match="unplayable"):
        gen.save_draft(bad, dest=quarantine)


def test_a_retry_is_told_what_was_wrong():
    seen = []

    def watching(prompt, system=""):
        seen.append(prompt)
        return GOOD if len(seen) > 1 else GOOD.replace(
            "58-year-old woman, severe difficulty breathing, audible wheeze, conscious.",
            "Difficulty breathing call.")

    drafted = gen.draft(["asthma"], llm=watching, context=CONTEXT, lessons="")
    assert drafted.playable
    assert "previous attempt was rejected" in seen[1]
    assert "dispatch" in seen[1]


# ── a model never authors clinical truth ─────────────────────────────────────

def test_an_invented_citation_is_stripped():
    """A fabricated citation reads as provenance, so it must not survive."""
    invented = GOOD.replace("[SRC-10:p282]", "[SRC-99:p999]")
    drafted = gen.draft(["asthma"], llm=stub(invented), context=CONTEXT, lessons="")
    assert "SRC-99" not in drafted.body
    assert "SRC-99:p999" in drafted.stripped_citations
    # The brackets go with it. A bare "[]" reads as a citation that failed to
    # render rather than one that was never real.
    assert "[]" not in drafted.body


def test_a_saved_draft_is_pending_and_marked_generated(quarantine):
    drafted = gen.draft(["asthma"], llm=stub(GOOD), context=CONTEXT, lessons="")
    path = gen.save_draft(drafted, dest=quarantine)
    frontmatter, _ = read_page(path)
    assert frontmatter["status"] == "pending"
    assert frontmatter["labeled_by"] == ""
    assert frontmatter["origin"] == "generated"


def test_quarantine_is_invisible_to_the_simulator(quarantine, tmp_path):
    """`list_approved` globs one level, so `generated/` cannot be dealt."""
    drafted = gen.draft(["asthma"], llm=stub(GOOD), context=CONTEXT, lessons="")
    gen.save_draft(drafted, dest=tmp_path / "generated")
    assert list_approved(dest_dir=tmp_path) == []


# ── the review loop ──────────────────────────────────────────────────────────

def test_approving_promotes_it_into_the_vetted_corpus(tmp_path):
    quarantine, vetted = tmp_path / "generated", tmp_path / "scenarios"
    drafted = gen.draft(["asthma"], llm=stub(GOOD), context=CONTEXT, lessons="")
    path = gen.save_draft(drafted, dest=quarantine)

    promoted = review.approve(path, labeled_by="ry", realism_rating=4,
                              realism_note="plausible", dest=vetted)

    assert not path.exists(), "an approved draft must leave quarantine"
    frontmatter, body = read_page(promoted)
    assert frontmatter["status"] == "approved" and frontmatter["labeled_by"] == "ry"
    assert frontmatter["realism_rating"] == 4
    assert list_approved(dest_dir=vetted) == [promoted]
    assert unplayable(frontmatter, body) == []


def test_a_rejection_stays_in_quarantine_and_becomes_a_lesson(tmp_path):
    quarantine = tmp_path / "generated"
    lessons = tmp_path / "generation-lessons.md"
    drafted = gen.draft(["asthma"], llm=stub(GOOD), context=CONTEXT, lessons="")
    path = gen.save_draft(drafted, dest=quarantine)

    review.reject(path, labeled_by="ry",
                  critique="A 58-year-old with this history would already be on home oxygen.",
                  lessons=lessons)

    assert path.exists(), "a rejected draft is kept, not deleted"
    assert read_page(path)[0]["status"] == "rejected"
    assert "already be on home oxygen" in lessons.read_text()


def test_a_rejection_needs_a_critique(tmp_path):
    drafted = gen.draft(["asthma"], llm=stub(GOOD), context=CONTEXT, lessons="")
    path = gen.save_draft(drafted, dest=tmp_path / "generated")
    with pytest.raises(ValueError, match="critique"):
        review.reject(path, labeled_by="ry", critique="   ")


def test_the_lesson_reaches_the_next_generation_prompt(tmp_path):
    lessons = tmp_path / "generation-lessons.md"
    review.record_lesson("Bystanders rarely volunteer a medication list unprompted.",
                         path=lessons)
    seen = []

    def watching(prompt, system=""):
        seen.append(prompt)
        return GOOD

    gen.draft(["asthma"], llm=watching, context=CONTEXT,
              lessons=lessons.read_text(encoding="utf-8"))
    assert "rarely volunteer a medication list" in seen[0]


def test_the_same_lesson_is_not_recorded_twice(tmp_path):
    lessons = tmp_path / "generation-lessons.md"
    for _ in range(3):
        review.record_lesson("Do not give a COPD patient a normal SpO2.", path=lessons)
    assert lessons.read_text().count("normal SpO2") == 1


# ── the real retrieval path ──────────────────────────────────────────────────

def test_a_draft_grounded_in_the_real_wiki_keeps_its_citations():
    context, used = gen.context_for(["asthma"], limit=4)
    real = [c for c in ("SRC-10:p271", "SRC-10:p279") if c in context]
    if not real:
        pytest.skip("wiki pages moved; this test pins format, not content")
    drafted = gen.draft(["asthma"], llm=stub(GOOD), context=context, lessons="")
    assert drafted.playable


# ── playing a draft before reviewing it ──────────────────────────────────────

def test_a_draft_can_be_played_before_it_is_reviewed(tmp_path, monkeypatch):
    """The review loop is "play it, then review it", so quarantine has to be
    reachable by the thing you play it with — and only by naming it."""
    from ems.sim.session import Session

    quarantine = tmp_path / "generated"
    drafted = gen.draft(["asthma"], llm=stub(GOOD), context=CONTEXT, lessons="")
    path = gen.save_draft(drafted, dest=quarantine)

    session = Session.from_path(path)
    said = ["BSI, scene safe, one patient", "nonrebreather at 15 L/min", "end of call"]
    index = 0
    while not session.done:
        if session.awaiting_input:
            session.step(said[index] if index < len(said) else "end of call")
            index += 1
        else:
            session.step()
    assert session.grade().points > 0, "a draft has to be gradeable to be worth reviewing"


def test_playing_a_draft_does_not_put_it_in_the_vetted_pool(tmp_path):
    from ems.scenarios import list_approved

    drafted = gen.draft(["asthma"], llm=stub(GOOD), context=CONTEXT, lessons="")
    gen.save_draft(drafted, dest=tmp_path / "generated")
    assert list_approved(dest_dir=tmp_path) == []


# ── steps the grader cannot see ──────────────────────────────────────────────

def test_the_gate_refuses_commentary_dressed_as_a_step():
    """Reported after a played draft: "this is not really a step."

    "Do not delay epinephrine to finish the history" is an ordering rule, and
    carries no action at all. It was graded on word overlap and could never be
    hinted, so the reviewer lost points on steps they had actually performed.
    """
    from ems.sim.generate import rubric_problems

    problems = rubric_problems(
        "## Correct actions\n"
        "1. Do not delay epinephrine to finish the history — it is the priority\n"
    )
    assert problems and "step 1" in problems[0]


def test_the_gate_refuses_an_action_buried_behind_its_reason():
    from ems.sim.generate import rubric_problems

    problems = rubric_problems(
        "## Correct actions\n"
        "1. Ensure a safe scene, because patients with diabetic emergencies "
        "can be agitated and sometimes violent\n"
    )
    assert problems, "an action behind a because-clause matches nothing"


def test_the_same_step_written_plainly_passes():
    from ems.sim.generate import rubric_problems

    assert rubric_problems(
        "## Correct actions\n"
        "1. Ensure the scene is safe and take Standard Precautions\n"
    ) == []


def test_ordering_allows_a_repeat_dose_after_the_paperwork():
    """A second autoinjector two minutes later is meant to come after.

    The first version of this rule flagged it, which made a correctly ordered
    anaphylaxis call look wrong. Only the first step of a given kind binds.
    """
    from ems.sim.generate import rubric_problems

    assert rubric_problems(
        "## Correct actions\n"
        "1. Administer one adult autoinjector into the lateral thigh\n"
        "2. Record the dose and the time given on the patient care report\n"
        "3. Reassess 2 minutes after the dose and give a second autoinjector "
        "if she has not improved\n"
    ) == []


def test_ordering_still_catches_the_history_before_the_drug():
    from ems.sim.generate import rubric_problems

    problems = rubric_problems(
        "## Correct actions\n"
        "1. Take a SAMPLE history from the family\n"
        "2. Administer epinephrine by autoinjector into the lateral thigh\n"
    )
    assert problems and "numbered after" in problems[0]


def test_assessing_before_treating_is_not_an_ordering_error():
    """"Confirm the autoinjector is indicated" precedes giving it, correctly."""
    from ems.sim.generate import rubric_problems

    assert rubric_problems(
        "## Correct actions\n"
        "1. Confirm the epinephrine autoinjector is indicated and prescribed for her\n"
        "2. Administer one adult autoinjector into the lateral thigh\n"
    ) == []
