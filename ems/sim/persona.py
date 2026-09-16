"""LLM voices for the call — dispatcher, patient, bystander, narrator.

The model performs the conversation. It does not decide what is correct.

Two boundaries are enforced here rather than asked for politely:

1. **The answer key never reaches a persona.** A persona is handed a
   `PersonaContext`, which is built by `Session.persona_context()` from the
   scenario's public sections only. The rubric is not a field on it, so there is
   no prompt in which it can appear.
2. **A persona cannot leak a vital the EMT has not measured.** Project 5 gates
   numbers behind assessment; a chatty patient volunteering "my oxygen was 82"
   would undo that. Persona output is scrubbed of unmeasured vitals before it
   reaches the transcript.
"""

import os
import re
from functools import partial
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from ems.config import SIM_PERSONA_MODEL
from ems.llm import INTERACTIVE_TIMEOUT, call_llm
from ems.sim.intents import GATED_VITALS

PERSONAS = ("dispatcher", "patient", "bystander", "narrator")

#: The default LLM for every persona. Time-boxed rather than bare
#: `call_llm`, because a trainee is waiting on this line; a fake injected
#: by a test or a CLI still arrives as a plain two-argument callable.
_llm = partial(call_llm, timeout=INTERACTIVE_TIMEOUT)


@dataclass(frozen=True)
class PersonaContext:
    """Everything a persona may see. The rubric is deliberately not a field.

    If you are tempted to add `correct_actions` here, that is the thing this
    class exists to prevent.
    """
    scenario_id: str
    phase: str
    dispatch: str
    presentation: str
    age_group: str = "adult"
    #: Only what the EMT has actually measured.
    known_vitals: dict = field(default_factory=dict)
    #: (speaker, text) in order, so the persona can stay consistent.
    transcript: tuple[tuple[str, str], ...] = ()
    #: What the EMT just said, when it is the persona's turn to answer.
    utterance: str = ""


_SYSTEM = {
    "dispatcher": (
        "You are an EMS dispatcher reading a call over the radio. One or two "
        "sentences, clipped radio cadence, unit designator first. State the "
        "location, the patient's age and sex, and the reported complaint. Never "
        "diagnose and never advise — you relay what the caller said."
    ),
    "patient": (
        "You are the patient on an EMS call. Speak in the first person, in your "
        "own words, one or two sentences. Answer only what you are asked. You do "
        "not know medical terminology and you do not know your diagnosis — "
        "describe how you feel, not what is wrong with you. If you are short of "
        "breath, speak in short broken phrases. If you are drowsy or confused, "
        "answer vaguely or not at all. Never state a number for any vital sign; "
        "the EMT has to measure those."
    ),
    "bystander": (
        "You are a bystander on an EMS call — family, a coworker, a passer-by. "
        "One or two sentences. You are worried and not medically trained. You "
        "know what you saw and what led up to this, and nothing more. Do not "
        "diagnose, and never state a number for any vital sign."
    ),
    "narrator": (
        "You narrate what the EMT observes, in the second person, in one or two "
        "sentences. Describe only what is visible, audible, or smellable from "
        "where the EMT is standing. Never state a measured number — no rate, no "
        "saturation, no blood pressure. Never say what the EMT should do."
    ),
}

_SHARED = (
    "\n\nThis is a training simulation for EMTs. Stay in character. Do not "
    "narrate the correct treatment, evaluate the EMT's performance, or hint at "
    "what they should do next — a separate grader does that after the call."
)

# Numbers next to a vital-sign word. Used to scrub, not to parse.
_VITAL_LEAK = {
    # `resp\w*` also matched "respond" and "responsive", so "respond for: a
    # 34-year-old" read as a respiratory rate and the tone-out lost the age.
    # Harmless while scrubbing only ever saw patient replies; not once the
    # dispatcher and narrator speak.
    "rr": r"\b(?:rr|resps?|respirat\w*|breath\w*)\b\D{0,12}\d{1,3}\b"
          r"|\b\d{1,3}\D{0,12}(?:breaths?|respirations?)\b",
    "hr": r"\b(?:hr|pulse|heart\s*rate|bpm)\D{0,12}\d{1,3}\b|\b\d{1,3}\s*bpm\b",
    "spo2": r"\b(?:spo2|sat\w*|oxygen\s*level|pulse\s*ox)\D{0,12}\d{1,3}\b|\b\d{1,3}\s*%",
    "bp": r"\b(?:bp|blood\s*pressure)\D{0,12}\d{2,3}\s*/\s*\d{2,3}\b|\b\d{2,3}\s*/\s*\d{2,3}\b",
}
_COMPILED_LEAK = {k: re.compile(v, re.IGNORECASE) for k, v in _VITAL_LEAK.items()}


def scrub_vitals(text: str, known: dict) -> str:
    """Remove numeric vitals the EMT has not measured.

    The persona is *told* not to state numbers, but a prompt is a request and
    this is an invariant — the whole point of gating is that a number appears
    only when it was earned.
    """
    for key, pattern in _COMPILED_LEAK.items():
        if key in known:
            continue
        text = pattern.sub("[…]", text)
    return re.sub(r"\s*\[…\]\s*", " ", text).strip()


def _prompt(context: PersonaContext, speaker: str) -> str:
    lines = [
        f"Dispatch said: {context.dispatch}",
        f"What is in front of the EMT: {context.presentation}",
        f"Patient age group: {context.age_group}",
    ]
    if context.transcript:
        recent = context.transcript[-8:]
        lines.append("Recent exchange:")
        lines += [f"  {who}: {said}" for who, said in recent]
    if context.utterance:
        lines.append(f"The EMT just said: {context.utterance}")
    lines.append(
        {
            "dispatcher": "Read the tone-out.",
            "patient": "Reply as the patient.",
            "bystander": "Reply as the bystander.",
            "narrator": "Narrate what the EMT sees now.",
        }[speaker]
    )
    return "\n".join(lines)


def speak(
    context: PersonaContext,
    speaker: str = "patient",
    llm: Callable = _llm,
    model: Optional[str] = None,
) -> str:
    """One line, in character, with unmeasured vitals scrubbed out."""
    if speaker not in PERSONAS:
        raise ValueError(f"speaker must be one of {PERSONAS}; got {speaker!r}")

    raw = llm(
        _prompt(context, speaker),
        system=_SYSTEM[speaker] + _SHARED,
        model=model or os.environ.get("EMS_PERSONA_MODEL", SIM_PERSONA_MODEL),
    )
    return scrub_vitals(raw.strip(), context.known_vitals)


@dataclass
class LlmHealth:
    """Whether Claude actually answered, counted as the call runs.

    `safe_speak` degrades to the deterministic text on any failure, which is the
    right behavior and was also completely silent: a revoked key produced a full
    call of canned lines, and the transcript still said "Claude voices" because
    that field was read from the *request flag* rather than from anything that
    happened. A reviewer could not tell a model that answered flatly from a model
    that was never reached, and those need different fixes.
    """
    attempted: int = 0
    answered: int = 0
    failed: int = 0
    #: The first failure only. They are nearly always the same cause repeated,
    #: and one readable line beats forty identical ones.
    first_error: str = ""

    def record(self, error: Optional[BaseException] = None) -> None:
        self.attempted += 1
        if error is None:
            self.answered += 1
            return
        self.failed += 1
        if not self.first_error:
            self.first_error = f"{type(error).__name__}: {error}"[:300]

    def to_dict(self) -> dict:
        return asdict(self)


def tracked_speak(health: LlmHealth) -> Callable:
    """`safe_speak` bound to a tally — the persona a graded session should use.

    Returns the same two-argument callable `Session.persona` expects, so nothing
    downstream changes shape.
    """
    def speaker(context: PersonaContext, speaker_name: str = "patient") -> str:
        return safe_speak(context, speaker_name, health=health)
    return speaker


def safe_speak(
    context: PersonaContext,
    speaker: str = "patient",
    llm: Callable = _llm,
    model: Optional[str] = None,
    health: Optional[LlmHealth] = None,
) -> str:
    """`speak`, but a failure loses the line rather than the call.

    `Session._answer` calls its persona bare, so anything raised here — a rate
    limit, a dropped connection, a bad key — propagates out of `Session.step`.
    In the terminal that is a traceback mid-call; over HTTP it is a 500 on a
    turn, with the session left waiting for input that can never arrive.

    Returning "" is the whole recovery: `_answer` already falls through to
    `_canned_answer` on empty output, so the call continues deterministically
    and the trainee sees a plainer line instead of losing their work.

    Deliberately broad. There is no exception from an HTTP client worth ending
    somebody's practice over, and narrowing this to the SDK's error types would
    tie the simulator to that SDK.
    """
    try:
        spoken = speak(context, speaker, llm, model)
    except ValueError:
        # A bad speaker name is a programming error, not a network blip.
        raise
    except Exception as error:                          # noqa: BLE001
        if health is not None:
            health.record(error)
        return ""
    if health is not None:
        health.record()
    return spoken


def enrich_narration(scene, presentation: str, llm: Callable = _llm,
                     model: Optional[str] = None) -> str:
    """Elaborate the scene in prose. Cannot change a `SceneSpec` field.

    The spec is passed in for grounding and passed back untouched — this
    returns a string, so there is no path by which enrichment edits the data the
    animation renders from.
    """
    facts = scene.to_dict()
    patient = facts.get("patient") or {}
    described = ", ".join(
        f"{k}: {v}" for k, v in patient.items()
        if v is not None and k not in GATED_VITALS
    )
    prompt = (
        f"Setting: {facts['setting']}, {facts['time_of_day']}, {facts['weather']}.\n"
        f"Hazards: {', '.join(facts['hazards']) or 'none'}.\n"
        f"People present: {', '.join(b['role'] for b in facts['bystanders']) or 'no one else'}.\n"
        f"The patient: {described or 'not described'}.\n"
        f"Vetted description: {presentation}\n"
        "Describe this scene as the EMT walks in."
    )
    return llm(
        prompt,
        system=_SYSTEM["narrator"] + _SHARED,
        model=model or os.environ.get("EMS_PERSONA_MODEL", SIM_PERSONA_MODEL),
    ).strip()


def context_as_dict(context: PersonaContext) -> dict:
    """Serialized form — used by tests asserting the rubric never appears."""
    return asdict(context)
