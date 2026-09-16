"""Deterministic grading of a simulated call — no LLM, no API key.

Ground truth is the scenario's own EMT-approved ``## Correct actions`` list, so
this module never decides what the right answer is; it only decides whether the
trainee said it. The LLM narrative debrief (Project 6) runs *after* this and
cannot overrule it — in particular, the critical-error checks stand regardless
of what any model later says about the call.
"""

import re
from dataclasses import asdict, dataclass, field, replace

from ems.markdown import get_section
from ems.sim.intents import (
    CRITICAL_INTENTS,
    DEVICE_FLOW_RANGE,
    SIZE_UP_ITEMS,
    classify,
    flow_rate,
    is_prohibition,
    named_device,
    prohibited_intents,
    spoken_intents,
)

#: Doing something to the patient, as opposed to assessing or asking.
INTERVENTION_INTENTS = frozenset(
    {
        "oxygen", "airway-open", "suction", "ventilate", "bleeding-control",
        "cpr", "aed", "medication-assist", "position", "spinal-motion-restriction",
        "thermal-care",
    }
)

_HIT_COVERAGE = 0.5      # share of an action's intents the EMT must hit
_PARTIAL_COVERAGE = 0.2

#: Intents are coarse. `sample-history` is one label covering "Obtain a SAMPLE
#: history" and "Ask specifically about previous allergic reactions that
#: required medical treatment" alike, so a generic history request used to score
#: a full hit against the specific line — credit for a question never asked.
#:
#: The fix is scoped to where the ambiguity actually is. When an action's
#: intents pick it out uniquely within its own scenario, matching the intent is
#: enough and the content check would only punish correct answers — rubric lines
#: carry rationale prose ("since she is in distress and appears to be having an
#: anaphylactic reaction") that no EMT would ever say aloud.
#:
#: When two or more lines in the same scenario carry the same intents, the
#: intent cannot tell them apart, so the words have to. Below the threshold it
#: is a `partial`: the right kind of step, the wrong level of detail.
_CONTENT_COVERAGE = 0.25

#: Steps that stop being right if they happen late. Doing the history first and
#: the epinephrine after is not the same call in a different order — the delay
#: is the error, and a grader that ignores sequence cannot say so.
#:
#: **This is a clinical judgement and it should be reviewed by an EMT.** It is a
#: deliberately short list of things that treat an immediate threat to life; the
#: intent tables it draws from have not themselves been vetted.
TIME_CRITICAL_INTENTS = frozenset({
    "cpr", "aed", "airway-open", "suction", "ventilate",
    "oxygen", "oxygen-nrb", "oxygen-nc", "oxygen-bvm",
    "bleeding-control", "medication-assist",
})
#: A critical error is not arithmetic. It ends the station.
#:
#: It used to cost 3 raw points before the total was scaled to 100, which meant
#: the same act — nitroglycerin into a systolic of 80 — cost 27 points on a
#: three-step scenario and 7 on an eighteen-step one. The danger is identical.
#: Now it fails the call outright, the way critical criteria work on an NREMT
#: skill sheet, and the points stand on their own as a record of what was done.
#:
#: PLACEHOLDER, and the one number here an EMT should set rather than a
#: programmer: the share of available points a call must earn to pass when
#: nothing critical went wrong.
_PASSING_FRACTION = 0.7

_STOPWORDS = frozenset(
    """the and for with that this from your you are was were has have had not but
    any all his her its their them they she him who when what which while into
    onto than then once only also more most such very just about before after
    during because since each other than take give keep make ensure recognize
    patient textbook indicated""".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


@dataclass(frozen=True)
class ActionResult:
    """How one line of ``## Correct actions`` fared."""
    index: int                    # 1-based position in the correct sequence
    action: str
    status: str                   # "hit" | "partial" | "missed"
    matched_turn: int | None = None   # 0-based index into the EMT's turns
    note: str = ""
    #: The EMT's own words that earned this step. A trainee who is told a step
    #: was hit but not by what cannot learn which phrasing counted, and one told
    #: it was missed cannot tell a wording problem from a clinical one.
    said: str = ""


@dataclass(frozen=True)
class CriticalError:
    rule: str
    detail: str
    #: Plain-language fix. The debrief showed the bare rule slug —
    #: `oxygen-device-missing` — which names the rule to someone who already
    #: knows it and teaches nothing to someone who does not.
    guidance: str = ""


@dataclass(frozen=True)
class SizeUpResult:
    covered: tuple[str, ...] = ()
    missed: tuple[str, ...] = ()

    @property
    def score(self) -> int:
        return len(self.covered)


@dataclass(frozen=True)
class Grade:
    scenario_id: str
    #: Raw points earned and available on *this* scenario. Deliberately not a
    #: percentage: the measurement is coarse — five size-up items and two points
    #: a step — and scaling it to 100 implied a precision it never had, so 52
    #: and 56 read as different when they are one partial credit apart.
    points: int
    points_possible: int
    #: Did the call pass? False whenever anything critical happened, whatever
    #: the points say. "You killed the patient but scored 71" is not sayable.
    passed: bool
    size_up: SizeUpResult
    actions: tuple[ActionResult, ...] = ()
    red_flags_caught: tuple[str, ...] = ()
    red_flags_missed: tuple[str, ...] = ()
    critical_errors: tuple[CriticalError, ...] = ()
    out_of_order: int = 0
    turns_to_first_intervention: int | None = None
    citations: tuple[str, ...] = field(default_factory=tuple)
    #: A sentence or two on how the call went, before any checklist. A trainee
    #: reading a bare "0/100" learns only that they failed.
    summary: str = ""
    #: The scenario's own ``## Rationale`` — the reasoning behind the answer
    #: key, written by the EMT who vetted the case. It explains *why* and was
    #: never reaching the debrief at all.
    rationale: str = ""
    #: Where the number came from, so the score can be argued with.
    breakdown: tuple[tuple[str, int, int], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        """JSON-ready form for the API and the stored debrief.

        `SizeUpResult.score` is computed, so `asdict` would drop it — and the
        size-up total is a headline number in the debrief.
        """
        data = asdict(self)
        data["size_up"]["score"] = self.size_up.score
        return data


# ── reading the answer key ───────────────────────────────────────────────────

def parse_actions(body: str) -> tuple[str, ...]:
    """The ordered ``## Correct actions`` list. This is the hidden rubric."""
    section = get_section(body, "Correct actions") or ""
    return tuple(m.strip() for m in re.findall(r"^\d+\.\s+(.*)$", section, re.MULTILINE))


def parse_red_flags(body: str) -> tuple[str, ...]:
    section = get_section(body, "Red flags") or ""
    return tuple(m.strip() for m in re.findall(r"^-\s+(.*)$", section, re.MULTILINE))


# ── matching one utterance against one action line ───────────────────────────

def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS}


def _match(utterance: str, action: str, disambiguate: bool = False) -> tuple[float, str, str]:
    """Return (coverage, status, note) for one utterance against one action.

    Uses intent sets when the action line is recognized by the table, and falls
    back to token overlap when it isn't, so an unusual line still grades.
    """
    action_intents = classify(action)
    utterance_intents = classify(utterance)

    if not action_intents:
        overlap = _tokens(utterance) & _tokens(action)
        coverage = len(overlap) / len(_tokens(action)) if _tokens(action) else 0.0
        if coverage >= _HIT_COVERAGE:
            return coverage, "hit", ""
        if coverage >= _PARTIAL_COVERAGE:
            return coverage, "partial", "partial wording match"
        return coverage, "none", ""

    shared = utterance_intents & action_intents
    if not shared:
        return 0.0, "none", ""
    coverage = len(shared) / len(action_intents)

    said, wanted = named_device(utterance_intents), named_device(action_intents)
    if said and wanted and said != wanted:
        return coverage, "partial", (
            f"oxygen given, but by {said.removeprefix('oxygen-').upper()} "
            f"where the call needs {wanted.removeprefix('oxygen-').upper()}"
        )

    if coverage >= _HIT_COVERAGE:
        if disambiguate:
            wanted = _tokens(action)
            touched = len(wanted & _tokens(utterance)) / len(wanted) if wanted else 1.0
            if touched < _CONTENT_COVERAGE:
                return coverage, "partial", (
                    "the right kind of step, but nothing you said addressed "
                    "what this line actually asks for"
                )
        return coverage, "hit", ""
    return coverage, "partial", "only part of this step was covered"


# ── the individual checks ────────────────────────────────────────────────────

def grade_size_up(utterance: str) -> SizeUpResult:
    """Score the scene size-up against the five NREMT items."""
    said = classify(utterance)
    covered = tuple(item for item in SIZE_UP_ITEMS if item in said)
    missed = tuple(item for item in SIZE_UP_ITEMS if item not in said)
    return SizeUpResult(covered=covered, missed=missed)


def grade_actions(utterances: list[str], actions: tuple[str, ...]) -> tuple[ActionResult, ...]:
    """Match the EMT's turns against the correct sequence.

    Every (action, turn) pair is scored, then assigned best-first: the strongest
    match in the whole call is settled before any weaker one, so a vague line
    cannot eat the sentence that would have satisfied a precise one. Turns are
    consumed, so saying "oxygen" once cannot satisfy two separate oxygen steps.

    A "Do NOT …" line is scored inverted: the EMT passes it by *not* doing the
    thing. Without this, doing the forbidden thing earns partial credit for
    wording overlap at the same time as it earns a critical error.
    """
    results: list[ActionResult] = []
    used: set[int] = set()
    # Lines whose intents do not pick them out from their neighbours: for these
    # the intent is not evidence, because a sibling line would match just as
    # well. See `_CONTENT_COVERAGE`.
    signatures = [frozenset(classify(a)) for a in actions]

    def _ambiguous(i: int) -> bool:
        """Could an utterance carrying only shared intents hit line `i`?

        Exact signature equality was too strict: "Obtain a SAMPLE history and
        take baseline vital signs" and "Ask specifically about previous
        allergic reactions" do not have the same intents, but the second is a
        subset of the first, so a bare history request satisfies it outright.
        """
        mine = signatures[i]
        if not mine:
            return False
        for j, other in enumerate(signatures):
            if j == i or not other:
                continue
            shared = mine & other
            if shared and len(shared) / len(mine) >= _HIT_COVERAGE:
                return True
        return False

    ambiguous = {i for i in range(len(actions)) if _ambiguous(i)}

    # Every (action, turn) pair scored once, then assigned best-first.
    #
    # Taking the first still-unused turn per action in rubric order let an
    # early line claim a turn on a *partial* while a later line would have
    # scored a full hit on it — the specific history question went unmatched
    # because the generic history line had already eaten the sentence.
    pairs = []
    for ai, action in enumerate(actions, 1):
        if prohibited_intents(action):
            continue
        for tj, utterance in enumerate(utterances):
            coverage, status, note = _match(
                utterance, action, disambiguate=(ai - 1) in ambiguous
            )
            if status != "none":
                # Hit-ness first: a full hit must outrank a partial whatever
                # their coverage numbers are. Sorting on coverage first let a
                # high-coverage *partial* claim the turn a hit needed, and the
                # step that was actually performed came back "missed".
                pairs.append((status == "hit", coverage, -ai, ai, tj, status, note))
    pairs.sort(reverse=True)
    _assigned: dict[int, tuple[str, str, int]] = {}
    for _cov, _hit, _neg, ai, tj, status, note in pairs:
        if ai in _assigned or tj in used:
            continue
        _assigned[ai] = (status, note, tj)
        used.add(tj)

    # A time-critical step done after a step the rubric puts later than it was
    # delayed, whatever else was right about it. The rubric's numbering is the
    # order the author says the call should run in.
    for ai, (status, note, turn) in list(_assigned.items()):
        if status != "hit" or not (signatures[ai - 1] & TIME_CRITICAL_INTENTS):
            continue
        overtaken = [
            other_turn
            for other_ai, (_s, _n, other_turn) in _assigned.items()
            if other_ai > ai and other_turn < turn
        ]
        if overtaken:
            _assigned[ai] = (
                "partial",
                "done, but only after steps that should have waited for it",
                turn,
            )

    for i, action in enumerate(actions, 1):
        forbidden = prohibited_intents(action)
        if forbidden:
            violation = next(
                (j for j, u in enumerate(utterances) if classify(u) & forbidden), None
            )
            results.append(ActionResult(
                index=i,
                action=action,
                status="missed" if violation is not None else "hit",
                matched_turn=violation,
                note="did the thing this step forbids" if violation is not None
                     else "correctly avoided",
                said=utterances[violation] if violation is not None else "",
            ))
            continue

        best = _assigned.get(i)
        status, note, turn = best if best else ("missed", "", None)
        results.append(
            ActionResult(
                index=i,
                action=action,
                status=status if turn is not None else "missed",
                matched_turn=turn,
                note=note,
                said=utterances[turn] if turn is not None else "",
            )
        )
    return tuple(results)


def count_out_of_order(results: tuple[ActionResult, ...]) -> int:
    """How many matched steps the EMT performed later than the step after them."""
    matched = [
        r.matched_turn for r in results
        if r.matched_turn is not None and not prohibited_intents(r.action)
    ]
    return sum(1 for a, b in zip(matched, matched[1:]) if b < a)


#: Ventilation deliberately delivered *without* supplemental oxygen. Neonatal
#: resuscitation starts on room air — the source says it is not necessary to
#: attach oxygen to the bag-valve mask during the initial stages, and to
#: consider it only if saturation stays low afterward. Without this, the
#: clinically correct answer earned `oxygen-flow-missing`, and since a critical
#: error fails the call outright, every neonatal scenario would have failed the
#: trainees who got it right.
#:
#: Anchored to the ventilation clause on purpose. "SpO2 90% on room air" is all
#: over the corpus as a *finding*, and "he's 90% on room air, put him on a
#: nonrebreather" must still earn the missing-flow-rate error.
_ROOM_AIR_RE = re.compile(
    r"(ventilat\w*|bag[- ]valve|\bbvm\b|positive[- ]pressure|bag\w*\s+(him|her|them))"
    r"[^.]{0,60}\broom air\b"
    r"|\broom air\b[^.]{0,40}(ventilat\w*|bag[- ]valve|\bbvm\b|positive[- ]pressure)",
    re.IGNORECASE,
)


#: Getting equipment out is not using it. "Have a BVM ready" names a device
#: with no flow rate and was charged `oxygen-flow-missing`, which fails the call
#: outright — the same shape as the room-air defect above, and found the same
#: way: by running a phrase through the grader before putting it in a scenario.
#:
#: Suppressed only when the utterance has no administration verb in it at all,
#: so "have a BVM ready and put her on a nonrebreather" still gets checked.
_READINESS_RE = re.compile(
    r"\b(have|get|keep|bring|prepare|prepping|set up)\w*\s+[^.]{0,45}"
    r"\b(ready|prepared|standing by|to hand|on standby|within reach)\b",
    re.IGNORECASE,
)
_ADMINISTER_RE = re.compile(
    r"\b(administer|appl(y|ies|ied)|start|begin|giv(e|ing|en)|deliver|"
    r"ventilat\w*|bag(ging)?\s+(him|her|them)|put\s+\w+\s+on|place\s+\w+\s+on|"
    r"titrat\w*|switch\w*\s+to)\b",
    re.IGNORECASE,
)


def find_critical_errors(
    utterances: list[str],
    actions: tuple[str, ...],
    results: tuple[ActionResult, ...],
) -> tuple[CriticalError, ...]:
    """Checks that run on every call regardless of what the rubric says."""
    errors: list[CriticalError] = []

    # 1. Every oxygen order names a device and a flow rate in range for it.
    for utterance in utterances:
        intents = classify(utterance)
        if "oxygen" not in intents:
            continue
        # Ventilating on room air is an order to give *no* supplemental oxygen,
        # so neither the device nor the flow-rate rule has anything to say.
        if _ROOM_AIR_RE.search(utterance):
            continue
        # Nor has it anything to say about equipment being made ready.
        if _READINESS_RE.search(utterance) and not _ADMINISTER_RE.search(utterance):
            continue
        device = named_device(intents)
        rate = flow_rate(utterance)
        if device is None:
            errors.append(CriticalError(
                "oxygen-device-missing",
                f"Oxygen ordered without naming a delivery device: {utterance!r}",
                guidance=(
                    "Name the device and the rate together — nasal cannula at "
                    "2-6 L/min, nonrebreather at 12-15, BVM at 15 with a "
                    "reservoir. 'Give oxygen' alone is not an order anyone can "
                    "carry out."
                ),
            ))
            continue
        label = device.removeprefix("oxygen-").upper()
        if rate is None:
            errors.append(CriticalError(
                "oxygen-flow-missing",
                f"{label} applied without naming a flow rate: {utterance!r}",
                guidance=(
                    f"Say the number as well as the device: "
                    f"'{label} at {DEVICE_FLOW_RANGE[device][0]}-"
                    f"{DEVICE_FLOW_RANGE[device][1]} L/min'."
                ),
            ))
            continue
        low, high = DEVICE_FLOW_RANGE[device]
        if not low <= rate <= high:
            errors.append(CriticalError(
                "oxygen-flow-out-of-range",
                f"{label} at {rate:g} L/min is outside the {low}–{high} L/min range.",
                guidance=f"A {label} runs at {low}-{high} L/min.",
            ))

    # 2. Nothing the scenario explicitly forbids was done.
    #
    # `spoken_intents` rather than `classify`, and only here: a critical error
    # is the heaviest thing this grader can say, so it has to rest on what the
    # EMT did and not on a drug they merely named. "I will check his vitals
    # again after administering nitroglycerin" is a plan to reassess, and it was
    # scored as assisting with a contraindicated drug a second time.
    #
    # Deliberately not applied to the credit above: dropping a subordinate
    # clause can also drop a real assessment ("give oxygen after a full set of
    # vitals"), and losing a point is a fair trade for never inventing a
    # critical error, while losing credit for work done is not.
    forbidden = {intent: a for a in actions for intent in prohibited_intents(a)}
    for utterance in utterances:
        for intent in spoken_intents(utterance) & set(forbidden):
            errors.append(CriticalError(
                "contraindicated-action",
                f"{utterance!r} does what this call forbids — {forbidden[intent]}",
            ))

    # 3. No airway, ventilation, bleeding, or CPR step was left undone.
    for result in results:
        if result.status != "missed" or prohibited_intents(result.action):
            continue  # a violated prohibition is already reported above
        if classify(result.action) & CRITICAL_INTENTS:
            errors.append(CriticalError(
                "critical-omission",
                f"Step {result.index} never happened: {result.action}",
            ))

    return tuple(errors)


def _token_seen(token: str, transcript: set[str]) -> bool:
    """Match on a common stem so "cyanosis" is caught by saying "cyanotic"."""
    if token in transcript:
        return True
    return any(
        (t.startswith(token[:5]) or token.startswith(t[:5]))
        for t in transcript
        if len(t) >= 5 and len(token) >= 5
    )


def _flag_tokens(flag: str) -> set[str]:
    """Only distinctive words count. "One-word dyspnea" must not be credited to
    someone who happened to say "one patient" during the size-up."""
    return {t for t in _tokens(flag) if len(t) >= 4 or t.isdigit()}


def catch_red_flags(utterances: list[str], red_flags: tuple[str, ...]) -> tuple[tuple, tuple]:
    """Split the scenario's red flags into those the EMT named and those missed."""
    transcript = _tokens(" ".join(utterances))
    caught, missed = [], []
    for flag in red_flags:
        wanted = _flag_tokens(flag)
        seen = sum(1 for t in wanted if _token_seen(t, transcript))
        hit = bool(wanted) and seen >= max(1, len(wanted) // 2)
        (caught if hit else missed).append(flag)
    return tuple(caught), tuple(missed)


def first_intervention_turn(utterances: list[str]) -> int | None:
    """1-based turn number of the first thing done *to* the patient."""
    for i, utterance in enumerate(utterances, 1):
        if classify(utterance) & INTERVENTION_INTENTS:
            return i
    return None


# ── the whole grade ──────────────────────────────────────────────────────────

def credit_the_size_up(
    results: tuple[ActionResult, ...], size_up: SizeUpResult
) -> tuple[ActionResult, ...]:
    """Stop a step being marked missed when the size-up already covered it.

    `grade_actions` only sees the post-size-up turns, so a scenario opening with
    "Take Standard Precautions" scored it missed even for a trainee who said
    "BSI, scene is safe, one patient" at the door. The debrief then showed BSI
    as covered in one panel and missing in the next, which reads as the tool not
    knowing what it saw.
    """
    covered = frozenset(size_up.covered)
    if not covered:
        return results
    return tuple(
        result if result.status != "missed" or not (classify(result.action) & covered)
        else replace(
            result,
            status="hit",
            note="covered in your scene size-up",
        )
        for result in results
    )


def grade_deterministic(
    frontmatter: dict,
    body: str,
    size_up_utterance: str,
    utterances: list[str],
) -> Grade:
    """Grade one completed call. ``utterances`` are the EMT's post-size-up turns."""
    actions = parse_actions(body)
    red_flags = parse_red_flags(body)

    size_up = grade_size_up(size_up_utterance)
    results = credit_the_size_up(grade_actions(utterances, actions), size_up)
    caught, missed = catch_red_flags([size_up_utterance, *utterances], red_flags)
    errors = find_critical_errors(utterances, actions, results)

    # A prohibition is pass/fail, not points. Doing nothing satisfies every
    # "Do NOT" line on the sheet, and an empty call was collecting 2 points a
    # piece for the forbidden things it had not got round to doing. Not doing
    # them is a criterion — the same shape as a critical error, which is what
    # breaking one already produces — so prohibitions leave the arithmetic
    # entirely, on both sides of the fraction. They stay in `results`, and so
    # stay in the debrief, because a trainee should still see they were there.
    scored = tuple(r for r in results if not is_prohibition(r.action))
    action_points = sum(
        2 if r.status == "hit" else 1 if r.status == "partial" else 0 for r in scored
    )
    # Red flags are reported, not scored.
    #
    # Catching one meant *saying it out loud*, and no EMT narrates "cold,
    # clammy, gray skin with tachycardia" on a real call — they act on it. So
    # the points measured a speech habit rather than clinical judgement, and a
    # trainee who did everything right and said nothing spare was marked down
    # for it. What the flags are actually good for is the debrief: this is what
    # the call turned on, whether or not anyone announced it.
    points = size_up.score + action_points
    possible = len(SIZE_UP_ITEMS) + 2 * len(scored)
    # Points and the verdict are separate judgements. A critical error fails the
    # call without touching the points, so the record still says what was done.
    passed = not errors and bool(possible) and points >= _PASSING_FRACTION * possible

    breakdown = (
        ("Scene size-up", size_up.score, len(SIZE_UP_ITEMS)),
        ("Correct actions", action_points, 2 * len(scored)),
    )

    return Grade(
        scenario_id=frontmatter.get("scenario_id", ""),
        points=points,
        points_possible=possible,
        passed=passed,
        size_up=size_up,
        actions=results,
        red_flags_caught=caught,
        red_flags_missed=missed,
        critical_errors=errors,
        out_of_order=count_out_of_order(results),
        turns_to_first_intervention=first_intervention_turn(utterances),
        citations=tuple(frontmatter.get("citations") or ()),
        summary=summarize(size_up, results, errors),
        rationale=(get_section(body, "Rationale") or "").strip(),
        breakdown=breakdown,
    )


def summarize(
    size_up: SizeUpResult,
    results: tuple[ActionResult, ...],
    errors: tuple[CriticalError, ...],
) -> str:
    """Two or three sentences on how the call went, in plain English.

    Deterministic and written from the same facts as the panels below it. The
    LLM narrative debrief may add to this; it may not contradict it.
    """
    hits = [r for r in results if r.status == "hit"]
    partials = [r for r in results if r.status == "partial"]
    missed = [r for r in results if r.status == "missed"]

    parts = []
    if hits:
        parts.append(
            f"You got {len(hits)} of the {len(results)} key steps"
            + (f", and part of {len(partials)} more" if partials else "")
            + "."
        )
    elif partials:
        parts.append(f"You partly covered {len(partials)} of the {len(results)} key steps.")
    else:
        parts.append(f"None of the {len(results)} key steps were covered.")

    if size_up.missed:
        parts.append(
            "Your size-up did not state "
            + _join(_readable(item) for item in size_up.missed) + "."
        )
    else:
        parts.append("Your scene size-up covered all five items.")

    if missed:
        parts.append("The step that matters most from here: " + _first_sentence(missed[0].action))
    if errors:
        parts.append(
            f"{len(errors)} critical error{'s' if len(errors) > 1 else ''} — see below. "
            "A critical error fails the call on its own, whatever the points say."
        )
    return " ".join(parts)


_READABLE_SIZE_UP = {
    "scene-safety": "the scene was safe",
    "bsi": "your precautions (BSI/PPE)",
    "patient-count": "how many patients there were",
    "moi-noi": "the mechanism of injury or nature of illness",
    "additional-resources": "whether you needed more resources",
}


def _readable(item: str) -> str:
    return _READABLE_SIZE_UP.get(item, item)


def _join(items) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


def _first_sentence(text: str) -> str:
    """Trim an action line to its first sentence, citations stripped."""
    text = re.sub(r"\s*\[[A-Z0-9\-]+:[^\]]+\]", "", text).strip()
    return re.split(r"(?<=[.!?])\s", text)[0]
