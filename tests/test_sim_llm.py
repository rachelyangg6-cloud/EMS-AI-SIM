"""
Tests for the LLM layer (Project 6): personas, re-skin, and the narrative debrief.
Fully offline — every LLM is injected, so no API key is involved.

These assert *structure*, not model quality: what the model is shown, what it is
allowed to change, and what happens when it makes something up.
"""
import json

import pytest

from ems.frontmatter import read_page
from ems.markdown import get_section
from ems.paths import scenarios_dir
from ems.sim import reskin as R
from ems.sim.debrief import Debrief, grade_llm
from ems.sim.grade import grade_deterministic
from ems.sim.persona import PersonaContext, context_as_dict, scrub_vitals
from ems.sim.session import Session

CH19 = scenarios_dir() / "src1-s01.md"
CITATIONS = ["[SRC-19:p541]", "[SRC-19:p542]"]


@pytest.fixture
def scenario():
    return read_page(CH19)


def echo_llm(prompt, system="", model=None):
    """Returns the prompt it was given, so tests can inspect what was sent."""
    return json.dumps({"prompt": prompt, "system": system, "model": model})


def canned(payload):
    def _llm(prompt, system="", model=None):
        return json.dumps(payload) if isinstance(payload, dict) else payload
    return _llm


# ── the boundary: a persona never sees the answer key ────────────────────────

def test_persona_context_has_no_rubric_field():
    """If someone adds `correct_actions` here, this test is why they shouldn't."""
    fields = set(PersonaContext.__dataclass_fields__)
    assert not fields & {"correct_actions", "rationale", "rubric", "body"}


def test_the_answer_key_never_reaches_a_persona_prompt(scenario):
    frontmatter, body = scenario
    session = Session.from_path(CH19)
    session.step()  # tone-out, so the transcript is non-empty

    context = session.persona_context("How long has she been like this?")
    serialized = json.dumps(context_as_dict(context))

    actions = get_section(body, "Correct actions") or ""
    assert actions.strip()
    for line in actions.splitlines():
        stripped = line.strip().lstrip("0123456789. ")
        if len(stripped) > 30:
            assert stripped not in serialized
    assert (get_section(body, "Rationale") or "").strip() not in serialized


# ── the gating invariant survives a chatty persona ───────────────────────────

def test_unmeasured_vitals_are_scrubbed_from_persona_output():
    leaky = "My oxygen was 82% this morning and my pulse was 118."
    assert "82" not in scrub_vitals(leaky, known={})
    assert "118" not in scrub_vitals(leaky, known={})


def test_a_measured_vital_may_be_spoken():
    leaky = "My oxygen was 82% this morning."
    assert "82" in scrub_vitals(leaky, known={"spo2": 82})


def test_blood_pressure_is_scrubbed_when_never_taken():
    assert "140/90" not in scrub_vitals("My blood pressure runs 140/90.", known={})


def test_a_leaky_persona_cannot_defeat_the_monitor_gate():
    session = Session.from_path(
        CH19, persona=lambda ctx, who: "I feel awful. My sat was 82 percent."
    )
    events = []
    queue = ["Scene is safe.", "How are you feeling?", "end of call"]
    while not session.done:
        events.append(session.step(queue.pop(0) if session.awaiting_input else None))
    answer = next(e.text for e in events if e.phase == "ANSWER")
    assert "82" not in answer
    assert session.known_vitals() == {}


# ── re-skin: the model may change the story, not the case ────────────────────

def test_reskin_rejects_a_changed_clinical_presentation(scenario):
    """The model made the patient better. That is not a re-skin."""
    frontmatter, body = scenario
    with pytest.raises(R.ReskinError, match="clinical presentation"):
        R.reskin(frontmatter, body, llm=canned({
            "dispatch": "Man in his 70s, mild trouble breathing.",
            "presentation": "He is sitting upright, pink and dry, alert and chatty.",
        }))


def test_reskin_rejects_an_empty_rewrite(scenario):
    frontmatter, body = scenario
    with pytest.raises(R.ReskinError):
        R.reskin(frontmatter, body, llm=canned({"dispatch": "", "presentation": ""}))


def test_validate_reskin_catches_a_tampered_answer_key(scenario):
    frontmatter, body = scenario
    tampered = body.replace("15 L/min", "6 L/min")
    with pytest.raises(R.ReskinError, match="Correct actions"):
        R.validate_reskin(frontmatter, body, tampered)


# ── the debrief: the deterministic grade is authoritative ────────────────────

def _grade(scenario):
    frontmatter, body = scenario
    return grade_deterministic(
        frontmatter, body, "Scene is safe, gloves on.",
        ["Put her on a non-rebreather at 15 liters"],
    )


def test_uncited_prose_is_allowed_but_a_wrong_citation_is_not(scenario):
    """Plain language needs no citation; a *fabricated* one is the failure."""
    frontmatter, body = scenario
    result = grade_llm(_grade(scenario), frontmatter, body, llm=canned({
        "summary": "You worked the call calmly.",
        "pros": ["You stayed organized"],
        "cons": [],
        "improvements": ["Slow down before you commit to a device"],
    }))
    assert result.pros == ("You stayed organized",)
    assert result.stripped == ()


def test_debrief_is_json_serializable(scenario):
    frontmatter, body = scenario
    result = grade_llm(_grade(scenario), frontmatter, body, llm=canned({
        "summary": "", "pros": [], "cons": [], "improvements": [],
    }))
    assert json.loads(json.dumps(result.to_dict()))["scenario_id"] == "src1-s01"
    assert isinstance(result, Debrief)


# ── a persona failure must not cost the call ─────────────────────────────────

def test_a_persona_that_raises_does_not_end_the_call():
    """`Session._answer` calls its persona bare, so before `safe_speak` a rate
    limit or dropped connection propagated out of `step()` — a traceback in the
    terminal, a 500 on a turn over HTTP, with the session stuck awaiting input.
    """
    from ems.paths import scenarios_dir
    from ems.sim.persona import safe_speak
    from ems.sim.session import Session

    def unreachable(*args, **kwargs):
        raise RuntimeError("429 rate limited")

    session = Session.from_path(
        scenarios_dir() / "src1-s01.md",
        persona=lambda ctx, who: safe_speak(ctx, who, llm=unreachable),
    )
    said, index = ["scene is safe", "what is her name", "end of call"], 0
    spoken = []
    while not session.done:                      # must not raise
        if session.awaiting_input:
            event = session.step(said[index] if index < len(said) else "end of call")
            index += 1
        else:
            event = session.step()
        if event.text:
            spoken.append(event.text)

    assert session.grade().points >= 0, "the call still grades"
    assert any("Debrief" in line for line in spoken)


# ── the opening, not just the replies ────────────────────────────────────────

def test_the_tone_out_and_the_scene_are_voiced_too():
    """ANSWER alone is one of eleven phases. The lines a trainee finds
    mechanical are mostly the fixed ones — the dispatch read verbatim and the
    whole Presentation delivered in a breath — and the dispatcher and narrator
    prompts had been written since Project 6 with nothing calling them."""
    from ems.paths import scenarios_dir
    from ems.sim.session import Session

    heard = []

    def persona(context, speaker):
        heard.append(speaker)
        return f"({speaker}) something in character"

    session = Session.from_path(scenarios_dir() / "src1-s02.md", persona=persona)
    # SCENE_NARRATION comes after SIZE_UP, which waits, so the size-up has to be
    # given before the arrival description is reached at all.
    while not session.awaiting_input:
        session.step()
    session.step("BSI, scene is safe, one patient")
    assert "dispatcher" in heard and "narrator" in heard


def test_the_deterministic_text_is_the_fallback_not_the_exception():
    from ems.paths import scenarios_dir
    from ems.sim.session import Session

    session = Session.from_path(scenarios_dir() / "src1-s02.md",
                                persona=lambda ctx, who: "   ")
    tone_out = session.step()
    assert "Medic 41, respond for:" in tone_out.text


@pytest.mark.parametrize("text", [
    "Medic 41, respond for: 34-year-old man, chest pain and shortness of breath",
    "He is responsive to voice",
    "A 5-month-old, responsive, brought in by a parent",
])
def test_scrubbing_leaves_an_age_alone(text):
    """`resp\\w*` matched "respond" and "responsive", so a tone-out lost its
    patient's age — harmless while only patient replies were scrubbed, not once
    the dispatcher speaks."""
    from ems.sim.persona import scrub_vitals

    assert scrub_vitals(text, {}) == text


@pytest.mark.parametrize("text", ["respirations 32", "RR 28", "resp 30", "pulse 120"])
def test_scrubbing_still_catches_an_unmeasured_vital(text):
    from ems.sim.persona import scrub_vitals

    assert not scrub_vitals(text, {}).strip()


# ── the tally behind the transcript header ──────────────────────────────────

def test_llm_health_counts_an_answer_and_a_failure_apart():
    from ems.sim.persona import LlmHealth, PersonaContext, safe_speak

    health = LlmHealth()
    ctx = PersonaContext(scenario_id="t", phase="TURN", dispatch="d", presentation="p")

    def boom(*_a, **_k):
        raise RuntimeError("authentication_error: invalid x-api-key")

    assert safe_speak(ctx, "patient", llm=boom, health=health) == "", "still degrades"
    assert (health.attempted, health.answered, health.failed) == (1, 0, 1)
    assert "invalid x-api-key" in health.first_error

    assert safe_speak(ctx, "patient", llm=lambda *_a, **_k: "It hurts.", health=health)
    assert (health.attempted, health.answered, health.failed) == (2, 1, 1)


def test_only_the_first_failure_is_kept():
    """Forty identical auth errors are one fact, not forty."""
    from ems.sim.persona import LlmHealth

    health = LlmHealth()
    health.record(RuntimeError("first"))
    health.record(RuntimeError("second"))
    assert "first" in health.first_error and "second" not in health.first_error
    assert health.failed == 2


def test_a_tracked_persona_is_still_the_two_argument_callable_a_session_wants():
    from ems.sim.persona import LlmHealth, PersonaContext, tracked_speak

    health = LlmHealth()
    ctx = PersonaContext(scenario_id="t", phase="TURN", dispatch="d", presentation="p")
    import ems.sim.persona as persona_mod
    spoken = tracked_speak(health)(ctx, "patient")
    assert isinstance(spoken, str)
    assert health.attempted == 1
