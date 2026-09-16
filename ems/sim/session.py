"""The full-call state machine: tone-out through debrief.

One `Session` plays one approved scenario. It owns the phase order, the
transcript, and the boundary that matters most in this project:

    The scenario's ``## Correct actions`` list never leaves this module except
    through `grade()`. No event payload contains it, so when Project 6 hands
    events to an LLM persona, the model physically cannot see the answer key.

What is deterministic here and stays that way: the phase order, the dispatch
text, the size-up prompt, and the scene narration. What is a placeholder until
Project 6 gives it an LLM: the patient's `ANSWER`, the `OBSERVE` narration, and
the `RESULT` line — this build has no physiology model, so vitals do not move in
response to an intervention. Grading does not depend on any of them.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ems.frontmatter import read_page
from ems.markdown import get_section
from ems.sim.grade import Grade, grade_deterministic, parse_actions
from ems.sim.intents import (
    ASSESSMENT_INTENTS, GATED_VITALS, classify, is_question, revealed_vitals,
)
from ems.sim.persona import LlmHealth, PersonaContext, scrub_vitals
from ems.sim.scene import Vitals, parse_vitals
from ems.sim.vitals import generate, infer_age_group

PHASES = (
    "TONE_OUT", "EN_ROUTE", "ARRIVAL", "SIZE_UP", "SCENE_NARRATION",
    "TURN", "ANSWER", "OBSERVE", "RESULT",
    "END_OF_CALL", "DEBRIEF",
)

#: Phases where the machine stops and waits for the EMT.
#:
#: There is one. The engine used to alternate ASK → DECIDE on a fixed cycle
#: regardless of what was typed, so a question routinely landed on a decision
#: turn and was answered "That is a question, not an action — nothing was
#: carried out." No real call has halves, and a trainee cannot see a cycle they
#: are being scored against. Now the EMT says one thing per turn and the engine
#: responds to what it actually was.
INTERACTIVE_PHASES = frozenset({"SIZE_UP", "TURN"})

#: Response phases, in the order they are emitted after the EMT speaks. Each
#: one self-suppresses when it has nothing to say, so queueing all three costs
#: nothing and a turn never produces filler.
_RESPONSE_ORDER = ("RESULT", "ANSWER", "OBSERVE")

# "end call" used to fall through this because the "of" was required, so a
# trainee who typed the obvious thing had their turn consumed as a question and
# had to guess again. Every phrasing anyone reached for now works.
#: A trainee reached for "end of scene", "end scene" and "stop" in one session
#: and got "Done." three times, because every branch here required the literal
#: word "call". The word for the thing being ended is now any of call / scene /
#: sim / simulation / session, and the bare verbs stand alone.
_ENDABLE = r"(?:call|scene|sim|simulation|session|exercise)"
_END_OF_CALL_RE = re.compile(
    rf"\bend(?:ing)?\s+(?:of\s+|the\s+|this\s+)?{_ENDABLE}\b"
    rf"|\b{_ENDABLE}\s+(?:is\s+)?(?:complete|over|done|finished)\b"
    rf"|\bclear(?:ing)?\s+the\s+{_ENDABLE}\b"
    rf"|\b(?:i'?m\s+)?(?:done|finished)\s+(?:with\s+)?(?:the\s+)?{_ENDABLE}\b"
    r"|^\s*(?:end|done|finished|stop|quit|exit|abort)\s*$"
    r"|^\s*end\s+of\s*$",
    re.I,
)

#: Broader than the above, and used only to *offer help*. Someone typing a short
#: line built around a stopping verb is trying to leave; if it did not match
#: above, answering "Done." tells them the sim did something, which is how a
#: trainee ends up typing three variants in a row. Kept to four words so a
#: clinical line ("end tidal CO2 is rising and the patient is stopping me")
#: cannot trip it.
_TRYING_TO_STOP_RE = re.compile(
    r"^(?:\W*\w+\W*){0,3}"
    r"\b(?:end|ended|stop|stopping|quit|exit|finish|finished|abort|terminate|over|wrap)\b"
    r"(?:\W*\w+\W*){0,2}$",
    re.I,
)


#: A stopping verb with one of these after it is an order, not an exit. "I want
#: to end the bleeding" has the same shape as "ok all finished up here" and the
#: intent table does not recognize it either, so the object is what separates
#: them. Answering a hemorrhage-control order with advice on how to quit is
#: worse than the "Done." this exists to replace.
_CLINICAL_OBJECT_RE = re.compile(
    r"\b(?:bleed\w*|h[ae]morrhag\w*|airway|breathing|ventilat\w*|compress\w*|"
    r"cpr|oxygen|pressure|pulse|seizure|vomit\w*|patient|wound|blood)\b",
    re.I,
)


def looks_like_stopping(utterance: str) -> bool:
    """A short line built around a stopping verb that did not end the call.

    Carrying no recognized intent is part of the test, not a nicety. "I want to
    end the bleeding" is the same shape as "ok all finished up here", and
    answering a real hemorrhage-control order with advice on how to quit is
    worse than the "Done." this exists to replace.
    """
    return bool(
        utterance
        and not _END_OF_CALL_RE.search(utterance)
        and _TRYING_TO_STOP_RE.match(utterance.strip())
        and not classify(utterance)
        and not _CLINICAL_OBJECT_RE.search(utterance)
    )

_SIZE_UP_PROMPT = "Size up the scene."
_TURN_PROMPT = "What do you do or say?"

#: Asking for a number a second time — "check the vitals again", "recheck her
#: pressure", "repeat the vitals".
_AGAIN_RE = re.compile(r"\bagain\b|\bre-?check\b|\bre-?assess\b|\brepeat\b", re.I)

#: How each gated vital gets talked about in prose, for matching a question to
#: the sentence that actually answers it.
_VITAL_TERMS = {
    "rr": ("breath", "respirat", "ventilat", "chest ris"),
    "hr": ("pulse", "heart rate", "brady", "tachy"),
    "spo2": ("spo2", "sat", "oximet", "oxygen level"),
    "bp": ("blood pressure", " bp ", "systolic", "diastolic"),
}


def _mentions_any(text: str, keys) -> bool:
    lowered = text.lower()
    return any(term in lowered for key in keys for term in _VITAL_TERMS[key])


def _about_another_vital(text: str, wanted) -> bool:
    """True when this sentence is about a vital other than the one asked for.

    Only fires when a specific vital was asked about. A sentence that names no
    vital at all is never disqualified — most of the corpus describes a patient
    in prose, and that prose is a fair answer to almost any question.
    """
    if not wanted:
        return False
    return _mentions_any(text, set(GATED_VITALS) - set(wanted)) and not _mentions_any(text, wanted)


@dataclass(frozen=True)
class Turn:
    """One line of the transcript, from either side."""
    seq: int
    phase: str
    speaker: str              # emt | dispatcher | patient | narrator
    utterance: str
    intents: tuple[str, ...] = ()
    at: str = ""


@dataclass(frozen=True)
class Event:
    """What the caller should show or say next."""
    phase: str
    speaker: str
    text: str
    awaiting_input: bool = False


def is_end_of_call(utterance: str) -> bool:
    return bool(_END_OF_CALL_RE.search(utterance or ""))


@dataclass
class Session:
    """A single played call. Construct with `Session.from_path`."""

    scenario_path: Path
    frontmatter: dict
    body: str
    unit: str = "Medic 41"
    #: Optional `persona(context, speaker) -> str`. Absent, the sim stays fully
    #: deterministic and needs no API key — Projects 2–5 behave unchanged.
    persona: Optional[Callable[[PersonaContext, str], str]] = None
    #: Filled in by `persona.tracked_speak` as the call runs. Present whenever
    #: personas were asked for, and the only evidence that distinguishes a model
    #: that answered from one that was never reached — every failure degrades to
    #: the same deterministic text, so the two calls read identically otherwise.
    llm_health: Optional["LlmHealth"] = None
    phase: str = "TONE_OUT"
    turns: list[Turn] = field(default_factory=list)
    _awaiting: bool = False
    _finished: bool = False
    _described: bool = False
    _answers: list[str] = field(default_factory=list)
    #: Gated vitals the EMT has assessed for, and those already narrated.
    _known: set[str] = field(default_factory=set)
    _narrated: set[str] = field(default_factory=set)
    #: "Nothing has changed" is worth saying once and grating thereafter.
    _said_unchanged: bool = False
    #: Response phases still owed for the turn the EMT just took.
    _pending: list[str] = field(default_factory=list)
    #: Cache for `_vitals` and the set of keys the simulator filled in.
    _filled_vitals: Optional["Vitals"] = None
    _generated: frozenset = frozenset()

    @classmethod
    def from_path(cls, path: Path, unit: str = "Medic 41", persona=None) -> "Session":
        frontmatter, body = read_page(path)
        session = cls(scenario_path=path, frontmatter=frontmatter, body=body,
                      unit=unit, persona=persona)
        session._answers = [
            s for s in _sentences(get_section(body, "Presentation") or "")
            if not _SECOND_PERSON_RE.match(s)
        ]
        return session

    # ── identity ────────────────────────────────────────────────────────────
    @property
    def scenario_id(self) -> str:
        return self.frontmatter.get("scenario_id", self.scenario_path.stem)

    @property
    def difficulty(self) -> str:
        return self.frontmatter.get("difficulty", "")

    @property
    def awaiting_input(self) -> bool:
        return self._awaiting

    @property
    def done(self) -> bool:
        """True once the debrief has been emitted — not merely reached."""
        return self._finished

    # ── the machine ─────────────────────────────────────────────────────────
    def step(self, utterance: str | None = None) -> Event:
        """Advance one phase, consuming ``utterance`` if one is awaited."""
        if self._awaiting:
            if utterance is None:
                raise ValueError(f"{self.phase} is waiting for the EMT to speak")
            self._record("emt", utterance)
            self._awaiting = False
            self.phase = self._next(utterance)

        event = self._build()
        if event.awaiting_input:
            self._awaiting = True
        else:
            # A silent phase still advances the machine, but it does not belong
            # in the transcript — a blank line is not something anybody said.
            if event.text:
                self._record(event.speaker, event.text)
            if self.phase == "DEBRIEF":
                self._finished = True
            else:
                self.phase = self._next(None)
        return event

    def _next(self, utterance: str | None) -> str:
        """The next phase.

        Fixed up to the scene narration, then driven by what the EMT said: a
        turn queues only the responses its utterance actually earns, and the
        machine returns to TURN once that queue drains.
        """
        if self.phase == "TURN" and is_end_of_call(utterance or ""):
            self._pending = []
            return "END_OF_CALL"
        if self.phase == "TURN":
            self._pending = self._responses_to(utterance or "")
            return self._pending.pop(0) if self._pending else "TURN"
        if self.phase in _RESPONSE_ORDER:
            return self._pending.pop(0) if self._pending else "TURN"
        return {
            "TONE_OUT": "EN_ROUTE",
            "EN_ROUTE": "ARRIVAL",
            "ARRIVAL": "SIZE_UP",
            "SIZE_UP": "SCENE_NARRATION",
            "SCENE_NARRATION": "TURN",
            "END_OF_CALL": "DEBRIEF",
        }[self.phase]

    def _responses_to(self, utterance: str) -> list[str]:
        """Which responses this utterance earns, in order.

        A turn can earn more than one. "Scene is safe, I'm putting on gloves,
        what's his name?" is an action *and* a question, and a ride-along that
        answers only half of it teaches the trainee to speak in fragments.
        """
        intents = classify(utterance)
        # Judged independently, not via `is_action`, which answers "is this
        # turn an instruction?" by shape first and so reports False for the
        # whole of "gloves are on, and what is her name?". That is one breath a
        # real EMT takes, and it earns both halves.
        acts = bool(intents - ASSESSMENT_INTENTS) or not (intents or is_question(utterance))
        asks = is_question(utterance) or bool(intents & ASSESSMENT_INTENTS)

        pending = []
        if acts:
            pending.append("RESULT")
        if asks:
            pending.append("ANSWER")
        # Always queued: `_observe` returns "" when the EMT has earned nothing
        # new, and an empty event advances the machine without being recorded.
        pending.append("OBSERVE")
        return pending

    def _build(self) -> Event:
        if self.phase == "TONE_OUT":
            dispatch = (get_section(self.body, "Dispatch") or "").strip()
            return Event("TONE_OUT", "dispatcher",
                         self._in_voice("dispatcher", f"{self.unit}, respond for: {dispatch}"))
        if self.phase == "EN_ROUTE":
            return Event("EN_ROUTE", "narrator", "Responding. ETA four minutes.")
        if self.phase == "ARRIVAL":
            return Event("ARRIVAL", "narrator", "On scene. Doors open.")
        if self.phase == "SIZE_UP":
            return Event("SIZE_UP", "sim", _SIZE_UP_PROMPT, awaiting_input=True)
        if self.phase == "SCENE_NARRATION":
            return Event(
                "SCENE_NARRATION", "narrator",
                self._in_voice(
                    "narrator", (get_section(self.body, "Presentation") or "").strip()
                ),
            )
        if self.phase == "TURN":
            return Event("TURN", "sim", _TURN_PROMPT, awaiting_input=True)
        if self.phase == "ANSWER":
            speaker, text = self._answer()
            return Event("ANSWER", speaker, text)
        if self.phase == "OBSERVE":
            return Event("OBSERVE", "narrator", self._observe())
        if self.phase == "RESULT":
            return Event("RESULT", "narrator", self._result())
        if self.phase == "END_OF_CALL":
            return Event("END_OF_CALL", "narrator", "End of call.")
        return Event("DEBRIEF", "sim", "Debrief ready.")

    def _in_voice(self, speaker: str, canned: str) -> str:
        """The same line, spoken rather than read out — when a persona is wired.

        The tone-out and the arrival description are what a trainee actually
        hears as mechanical: the dispatch field read verbatim and the whole
        Presentation paragraph delivered in one breath. Both prompts have existed
        in `persona.py` since Project 6 with nothing calling them.

        The deterministic text is the fallback, not the exception. A persona that
        is absent, fails, or scrubs to nothing leaves the call exactly as it was.
        """
        if self.persona is None or not canned:
            return canned
        spoken = self.persona(self.persona_context(canned), speaker).strip()
        spoken = scrub_vitals(spoken, self.known_vitals())
        return spoken or canned

    def _answer(self) -> tuple[str, str]:
        """Who replies and what they say.

        Returns a (speaker, text) pair because not every reply is the patient's.
        When the scenario has nothing that answers the question, the *narrator*
        says so — having the patient assert "nothing stands out" puts a clinical
        claim in their mouth that the scenario never made.
        """
        if self.persona is not None:
            asked = next(
                (t.utterance for t in reversed(self.turns) if t.speaker == "emt"), ""
            )
            spoken = self.persona(self.persona_context(asked), "patient").strip()
            # Scrubbed here, not only in `persona.speak`: this is the boundary
            # where a persona's words become the transcript, so the gate holds
            # whatever callable is wired in.
            spoken = scrub_vitals(spoken, self.known_vitals())
            if spoken:
                return "patient", spoken
        asked = next(
            (t.utterance for t in reversed(self.turns) if t.speaker == "emt"), ""
        )
        return self._canned_answer(asked)

    def _canned_answer(self, asked: str) -> tuple[str, str]:
        """The remaining Presentation sentence that best answers what was asked.

        These used to be popped in file order, so "check her SpO2" could be
        answered with the sentence about the pulse. In a training tool a
        confident irrelevant answer is worse than no answer: the trainee
        believes they asked and were told.
        """
        if not self._answers:
            return "narrator", "Nothing further stands out."

        # Both routes, because the intent table does not cover every phrasing:
        # "check her SpO2" classifies, a bare "what is her pulse" does not.
        lowered_ask = asked.lower()
        wanted = set(revealed_vitals(classify(asked))) | {
            key for key, terms in _VITAL_TERMS.items()
            if any(term in lowered_ask for term in terms)
        }

        # Order is kept — the Presentation reads as a description, not a FAQ, so
        # walking it in order is right. The one thing forbidden is answering
        # "what is her SpO2" with the sentence about her pulse.
        eligible = [
            i for i, text in enumerate(self._answers) if not _about_another_vital(text, wanted)
        ]
        if not eligible:
            return "narrator", "Nothing about that stands out."

        speaks_to_it = next(
            (i for i in eligible if _mentions_any(self._answers[i], wanted)), None
        )
        # The narrator, not the patient. `## Presentation` is written as what you
        # see on arrival — third person, about the patient — so attributing it to
        # her produces "She is on a chair just inside the doorway" *spoken by the
        # woman on the chair*. Blocking second-person frames last time fixed half
        # of this; the other half is that no sentence of arrival narration is
        # something a patient says. An LLM persona speaks in the first person and
        # is still attributed to `patient` above; this deterministic fallback is
        # description, and description belongs to the narrator.
        return "narrator", self._answers.pop(
            speaks_to_it if speaks_to_it is not None else eligible[0]
        )

    def persona_context(self, utterance: str = "") -> PersonaContext:
        """Everything a persona may see — the public sections and nothing else.

        The rubric is not on `PersonaContext` and is not read here, so a persona
        prompt cannot contain the answer key by construction.
        """
        return PersonaContext(
            scenario_id=self.scenario_id,
            phase=self.phase,
            dispatch=(get_section(self.body, "Dispatch") or "").strip(),
            presentation=(get_section(self.body, "Presentation") or "").strip(),
            age_group=self.frontmatter.get("age_group", "adult"),
            known_vitals=self.known_vitals(),
            transcript=tuple((t.speaker, t.utterance) for t in self.turns[-8:]),
            utterance=utterance,
        )

    def _result(self) -> str:
        """What came of the action the EMT just took.

        Only reached when the utterance actually was an action — the engine no
        longer alternates, so a question never lands here and never has to be
        told it was the wrong kind of turn.
        """
        last = next(
            (t.utterance for t in reversed(self.turns) if t.speaker == "emt"), ""
        )
        if looks_like_stopping(last):
            return "Say \"end of call\" to finish and get your debrief."
        return _acknowledge(classify(last))

    def _observe(self) -> str:
        """Report what the EMT has earned since the last look — nothing more.

        A number appears only once the EMT has assessed for it. Scenarios whose
        vitals are purely descriptive ("Alert; skin pale and diaphoretic") have
        no number to gate, so that text is narrated once as an observation.
        """
        # A vital the scenario never states cannot be reported, however hard the
        # EMT looks for it.
        fresh = [
            k for k in GATED_VITALS
            if k in self._known and k not in self._narrated
            and getattr(self._vitals, k) is not None
        ]
        if fresh:
            self._narrated.update(fresh)
            return "  ".join(_format_vital(k, getattr(self._vitals, k)) for k in fresh)

        if not self._described and not self._has_numbers():
            self._described = True
            return (get_section(self.body, "Vitals") or "").strip()

        # Say it once. Repeating it every cycle was a third of some transcripts
        # and taught the trainee to stop reading the scene line altogether.
        if not self._said_unchanged:
            self._said_unchanged = True
            return "Nothing has changed since your last look."
        return ""

    @property
    def _vitals(self):
        """What the scenario states, topped up so the monitor is not four blanks.

        Computed once and cached: the fill is seeded, but re-deriving it on every
        access would still be wasteful, and callers treat this as stable.
        """
        if self._filled_vitals is None:
            stated = parse_vitals(get_section(self.body, "Vitals") or "")
            self._filled_vitals, self._generated = generate(
                stated,
                conditions=self.frontmatter.get("conditions") or (),
                # Inferred rather than defaulted: 50 of the 95 playable cases
                # predate the `age_group` field, and defaulting them to adult
                # is how a five-month-old got a blood pressure of 118/68.
                age_group=infer_age_group(self.frontmatter, self.body),
                seed=self.scenario_id,
            )
            # Numbers the simulator guessed and wrote into the file parse as
            # stated, so nothing here would mark them. The frontmatter flag is
            # what keeps the SIM tag on until a practitioner reviews them and
            # clears it.
            if self.frontmatter.get("vitals_generated"):
                self._generated |= {
                    k for k in GATED_VITALS if getattr(self._filled_vitals, k) is not None
                }
        return self._filled_vitals

    @property
    def generated_vitals(self) -> frozenset[str]:
        """Which displayed vitals the simulator invented, for the SIM tag."""
        _ = self._vitals   # populates the cache
        return self._generated

    def _has_numbers(self) -> bool:
        return any(getattr(self._vitals, k) is not None for k in GATED_VITALS)

    def known_vitals(self) -> dict:
        """The measured values the monitor is allowed to display."""
        return {
            k: getattr(self._vitals, k)
            for k in GATED_VITALS
            if k in self._known and getattr(self._vitals, k) is not None
        }

    def _record(self, speaker: str, utterance: str) -> None:
        intents = frozenset(classify(utterance)) if speaker == "emt" else frozenset()
        if intents:
            self._known |= set(revealed_vitals(intents))
            # Asking again is the whole point of a reassessment, and the sim
            # answered "check the vital signs again" with silence because those
            # numbers had already been narrated once. Re-reading a vital is a
            # real request for a real number, so clear what has been said.
            #
            # Matched on the wording rather than by widening the `reassess`
            # intent: "check the vital signs again" carries no reassess tag, and
            # the intent table is what grading compares against, so loosening it
            # to catch "again" would move scores as a side effect.
            if "reassess" in intents or _AGAIN_RE.search(utterance):
                self._narrated -= set(revealed_vitals(intents)) or set(GATED_VITALS)
                self._said_unchanged = False
        self.turns.append(Turn(
            seq=len(self.turns),
            phase=self.phase,
            speaker=speaker,
            utterance=utterance,
            intents=tuple(sorted(intents)),
            at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ))

    # ── hidden state ────────────────────────────────────────────────────────
    def _rubric(self) -> tuple[str, ...]:
        """The answer key. Only `grade` may call this."""
        return parse_actions(self.body)

    # ── output ──────────────────────────────────────────────────────────────
    def emt_turns(self) -> list[Turn]:
        return [t for t in self.turns if t.speaker == "emt"]

    def grade(self) -> Grade:
        """Grade the call. Only meaningful once the EMT has ended it."""
        emt = self.emt_turns()
        size_up = next((t.utterance for t in emt if t.phase == "SIZE_UP"), "")
        actions = [
            t.utterance for t in emt
            if t.phase != "SIZE_UP" and not is_end_of_call(t.utterance)
        ]
        return grade_deterministic(self.frontmatter, self.body, size_up, actions)


#: What the narrator says back for an action, keyed by intent. Naming the action
#: is more use to a trainee than "Done." five times, and — because this build has
#: no physiology model — each line reports only that the thing was carried out.
#: None of them claims an effect the sim cannot actually simulate.
_ACKNOWLEDGEMENTS = (
    ("cpr", "Compressions started."),
    ("aed", "AED attached and analyzing."),
    ("airway-open", "Airway opened and held."),
    ("suction", "Suctioned; the airway is clear."),
    ("ventilate", "You are ventilating."),
    ("oxygen-bvm", "You are ventilating with the bag-valve mask."),
    ("oxygen", "Oxygen is running."),
    ("bleeding-control", "Pressure held on the wound."),
    ("spinal-motion-restriction", "Head and neck held in line."),
    ("position", "The patient is repositioned."),
    ("thermal-care", "The patient is covered."),
    ("medication-assist", "Medication given."),
    ("glucose-check", "Meter reading taken."),
    ("bsi", "Gloves and eye protection on."),
    ("als", "ALS is en route."),
    ("additional-resources", "The extra resources are requested."),
    ("medical-direction", "Medical direction is on the line."),
    ("transport", "Loaded and moving."),
    ("documentation", "Recorded."),
)


def _acknowledge(intents: frozenset[str]) -> str:
    """Report the action back in the order a call would prioritise it."""
    for intent, line in _ACKNOWLEDGEMENTS:
        if intent in intents:
            return line
    return "Done."


_VITAL_LABELS = {"rr": "RR", "hr": "Pulse", "spo2": "SpO2", "bp": "BP"}

#: Presentations in the early foundational sources are written as teaching
#: frames addressed to the reader — "You are preparing to secure a 6-year-old to
#: a backboard." Those are narration, not speech, and a patient who recites one
#: back is the single most immersion-breaking thing the sim does.
_SECOND_PERSON_RE = re.compile(r"^\s*(?:you|your)\b", re.IGNORECASE)


def _format_vital(key: str, value) -> str:
    return f"SpO2 {value}%." if key == "spo2" else f"{_VITAL_LABELS[key]} {value}."


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
