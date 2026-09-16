"""Nudges for a trainee who is stuck, without handing over the answer.

The implementation plan wants proactive nudges at Basic, hints on request at
Intermediate and none at Expert. This is the machinery: given the scenario's
answer key and what has been said so far, produce one sentence pointing at the
*kind* of thing still missing.

**A hint names what is missing; it never names the answer.** Those are two
different lines, and where the line falls depends on what is being graded.

*Assessments* are named outright. Forgetting the blood pressure **is** the
failure, so "You have not taken a blood pressure" gives nothing away — it just
stops the trainee guessing at what the hint means. The earlier riddling form
("One number is missing that would change your thinking") was reported as
confusing in practice, which is the whole cost of a hint nobody can decode.

*Treatments* keep their parameters back, because the device, the flow rate, the
dose and the route are exactly what the rubric scores. The rubric line "Begin
assisted ventilation with a bag-valve mask at 15 L/min with a reservoir" becomes
"They are not moving enough air on their own — they need help breathing. Say the
device and the rate." The trainee is told plainly what they owe and still has to
know what it is.

Two invariants hold the line, both tested: a hint never contains a digit, and a
hint never repeats the rubric's own words.
"""

from typing import Optional

from ems.sim.grade import parse_actions
from ems.sim.intents import classify

#: Intent → the nudge it earns. Ordered by how badly it wants saying, so a
#: missing airway outranks a missing history every time.
HINT_FOR_INTENT: tuple[tuple[str, str], ...] = (
    # ── life threats, in the order they kill ──
    ("cpr", "Establish whether this patient has a pulse before you decide anything else."),
    ("aed", "If there is no pulse, something else should be on this patient's chest by now."),
    ("airway-open", "You have not opened the airway. Do that before anything else."),
    ("suction", "There is something in this patient's airway. Clear it."),
    ("ventilate", "This patient is not moving enough air on their own."),
    ("oxygen-bvm", "They need help breathing, not just oxygen. Say the device and the rate."),
    ("bleeding-control", "This patient is losing blood. Find where, and stop it."),
    ("oxygen-nrb", "This patient needs high-concentration oxygen. Say the device and the flow rate."),
    ("oxygen-nc", "This patient needs oxygen, but not at the highest concentration. Say the device and the flow rate."),
    ("oxygen", "This patient needs oxygen. Say the device and the flow rate."),

    # ── scene, before you touch anyone ──
    ("scene-safety", "You have not established that this scene is safe to work in."),
    ("bsi", "You have not taken standard precautions. Say what you are putting on."),
    ("patient-count", "You have not said how many patients there are."),
    ("moi-noi", "You have not said what happened — the mechanism of injury or nature of illness."),
    ("additional-resources", "Decide what else you need on this scene, and call for it."),

    # ── the primary assessment, in its own order ──
    ("general-impression", "You have not formed a general impression — how sick does this patient look?"),
    ("recognize-condition", "Say what you think is going on. Name it."),
    ("pupils", "You have not looked at the pupils."),
    ("mental-status", "You have not checked her level of responsiveness."),
    ("breathing-assess", "You have not assessed breathing. Look at the rate, the depth and the effort."),
    ("pulse-check", "You have not felt a pulse. Check the rate, the rhythm and the quality."),

    # ── numbers and history ──
    ("vitals-full", "You have no vital signs. Get a full set — respirations, pulse, oxygen saturation and blood pressure."),
    ("vitals-bp", "You have not taken a blood pressure."),
    ("vitals-spo2", "You have not checked an oxygen saturation."),
    ("glucose-check", "You have not checked a blood glucose."),
    ("vitals", "You are working without numbers. Go and get some."),
    ("physical-exam", "You have not examined the patient — head to toe, or focused on the complaint."),
    ("abdominal-exam", "You have not examined the abdomen. Look at it first, then feel it — and mind the order."),
    ("opqrst", "You have not asked about the pain itself — what it is like, where, how bad, since when."),
    ("sample-history", "You have not taken a SAMPLE history. Ask the patient, not the room."),
    ("menstrual-history", "There are questions this patient is owed that nobody has asked. Think about who she is and where the pain is."),
    ("onset-time", "Nobody has established when this started, or when they were last well."),
    ("stroke-scale", "You have not run the stroke scale on this patient."),
    ("temperature", "You have not taken a temperature."),

    # ── treatment and disposition ──
    ("medication-assist", "A medication may be indicated here. Decide which, and whether you may give it."),
    ("medication-check", "Check the medication before it goes in — the right patient, and in date."),
    ("ecg", "This heart wants looking at properly."),
    ("patient-movement", "Decide how this patient gets to the ambulance, and whether they should walk."),
    ("decontaminate", "Something is still on this patient that should not be."),
    ("collect-evidence", "Something on this scene should travel with the patient."),
    ("exposure-response", "You have been exposed. Deal with it before you leave."),
    ("explain-to-patient", "Somebody here does not understand what is happening. Tell them."),
    ("therapeutic-communication", "Meet this patient where they are — pitch it to who they are."),
    ("protect-patient", "This patient can still come to harm where they are."),
    ("handover-report", "Decide what you are telling the hospital, and how."),
    ("medical-direction", "This decision is not yours alone to make. Who are you calling?"),
    ("position", "This patient is in the wrong position for what is wrong with them."),
    ("nothing-by-mouth", "Settle what this patient may and may not be given by mouth."),
    ("spinal-motion-restriction", "Consider the mechanism — this spine may need protecting."),

    # ── musculoskeletal (source 32) ──
    #
    # The CSM check is an assessment, so it is named outright — forgetting it
    # *is* the failure and there is no answer to give away. The three
    # treatments keep their parameters back: the trainee is told what they
    # owe and still has to know what it is.
    ("distal-csm-check", "You have not checked circulation, sensation and movement below the injury."),
    ("splint", "This limb needs immobilizing. Say what you are splinting and how far the splint reaches."),
    ("manual-traction", "This limb is deformed. Say what you would do about the angulation before splinting it."),
    ("pelvic-wrap", "This pelvis is unstable. Say what you would stabilize it with and where it sits."),
    ("traction-splint", "A mid-thigh femur fracture has a splint of its own. Say which, and what you checked before choosing it."),
    ("sling-and-swathe", "A rigid splint will not work on this one. Say what you would support it with."),

    # ── head and spine (source 33) ──
    #
    # The two assessments are named outright, because forgetting to do them
    # *is* the failure. The helmet is a decision rather than a step, so the
    # nudge names the decision and leaves the answer alone.
    ("glasgow-coma-scale", "You have not scored this patient's level of consciousness, or you have scored it once."),
    ("nexus-spinal-assessment", "You have not worked out whether this spine needs restricting. Say what you checked."),
    ("helmet-removal", "This patient is wearing a helmet. Say whether it stays on or comes off, and why."),
    ("thermal-care", "This patient is losing or gaining heat. Do something about it."),
    ("consent-refusal", "Settle whether you have this patient's permission to treat."),
    ("als", "Decide whether this is within your scope or whether you need ALS."),
    ("transport", "You have not made a transport decision — where, and how fast."),
    ("reassess", "You have not reassessed since you last intervened."),
    ("hospital-notify", "The hospital does not know what is coming. Call ahead."),
    ("documentation", "Something here needs recording — the time, the dose, or what you found."),

    # ── multisystem trauma (source 34) ──
    ("sensory-calm", "This scene is doing some of the harm. Change the scene."),
    ("mandated-report", "What you suspect has somewhere it has to go, and it is not this room."),
    ("dressing", "That wound is still open to the air."),
    ("establish-baseline", "Normal for this patient may not be normal. Somebody here knows which."),
    ("device-troubleshoot", "The machine is part of the patient. Work it as well as them."),
    ("assist-delivery", "This baby is being born whatever you do. Your hands have a job."),
    ("cord-care", "There is a cord, and what you do about it is time-sensitive."),
    ("newborn-warming", "A newborn loses heat faster than anything else you carry, and it costs them more."),
    ("perineal-pad", "There is bleeding you can absorb but must not pack."),
    ("uterine-massage", "The bleeding stops when the muscle tightens. Make it tighten."),
    ("apgar", "The newborn needs a number written down, twice."),
    ("descent", "Where this patient is doing more harm than anything you carry. Deal with that first."),
    ("oral-fluids", "This patient is alert, swallowing, and short of something you can hand them."),
    ("gentle-handling", "How you move this patient matters as much as where you move them to."),
    ("remove-constriction", "Something on this limb will not come off once it swells."),
    ("trauma-triage", "Where this one goes is a decision in itself. Say what in your findings settles it."),
    ("air-medical", "Consider whether the ground is fast enough for this patient, and what going by air would ask of you."),
    ("family-presence", "Someone else on this scene should not be left behind."),
)

#: Intents that only apply to a patient in arrest. A rubric line may *mention*
#: them while instructing the opposite — "Confirm a pulse is present, because a
#: patient without one needs CPR and defibrillation" classifies as `pulse-check`
#: **and** `cpr` **and** `aed`, since the words are all in the sentence.
#:
#: On a patient who has a pulse those two can never be cleared: the only
#: utterance that satisfies `cpr` is starting compressions, which would be
#: wrong. They then sit at the top of the priority order and freeze every hint
#: behind them for the whole call — the bug that made hints look broken on most
#: cardiac and overdose scenarios.
ARREST_ONLY_INTENTS = frozenset({"cpr", "aed"})


#: Vitals intent → the monitor readings that satisfy it. A hint is a question
#: about what the trainee still needs; a number already on the monitor is not
#: still needed, however they came to ask for it.
#:
#: Matching intent-for-intent got this wrong in both directions, because
#: `vitals-full` and `vitals-bp` are unrelated labels to `classify` even though
#: a full set *contains* a blood pressure. "Get all vitals" left `vitals-bp`
#: outstanding and the hint asked for a pressure already displayed; "take a
#: blood pressure" left `vitals-full` outstanding and the hint said there were
#: no vital signs at all.
#:
#: `classify` also returns a bare `vitals` alongside the specific label, and
#: that umbrella wants *any* reading rather than all of a set — so it is applied
#: separately below rather than being given an entry here.
SATISFIED_BY_MONITOR: dict[str, frozenset[str]] = {
    "vitals-bp": frozenset({"bp"}),
    "vitals-spo2": frozenset({"spo2"}),
    "pulse-check": frozenset({"hr"}),
    "vitals-full": frozenset({"rr", "hr", "spo2", "bp"}),
}


def next_hint(
    rubric: tuple[str, ...],
    said: tuple[str, ...],
    phase: str = "TURN",
    pulse_present: Optional[bool] = None,
    on_monitor: frozenset[str] = frozenset(),
) -> Optional[str]:
    """One nudge toward the highest-priority action not yet taken.

    `rubric` is the scenario's ``## Correct actions``; `said` is every EMT
    utterance so far. Returns None when nothing is outstanding.

    `pulse_present` comes from the scenario's own vitals. Pass True and the
    arrest-only intents are dropped from what is outstanding — see
    `ARREST_ONLY_INTENTS`. None means unknown, and nothing is dropped.

    `on_monitor` is the set of readings already revealed to the trainee. Any
    intent those satisfy is not outstanding, whatever words earned them — see
    `SATISFIED_BY_MONITOR`.
    """
    done = frozenset().union(*(classify(line) for line in said)) if said else frozenset()
    outstanding = frozenset().union(
        *(classify(line) for line in rubric)
    ) if rubric else frozenset()
    if pulse_present:
        outstanding -= ARREST_ONLY_INTENTS
    if on_monitor:
        done |= {"vitals"} | {
            intent for intent, needs in SATISFIED_BY_MONITOR.items()
            if needs <= on_monitor
        }
    missing = outstanding - done

    if not missing:
        return None
    for intent, hint in HINT_FOR_INTENT:
        if intent in missing:
            return hint
    return HINT_FOR_PHASE.get(phase, _FALLBACK)


def hint_for_session(session, phase: Optional[str] = None) -> Optional[str]:
    """`next_hint` against a live session, reading the answer key it holds.

    This is the only place outside grading that touches the rubric, and it never
    returns any of its text — only a category nudge from the table above.
    """
    said = tuple(t.utterance for t in session.turns if t.speaker == "emt")
    # `_vitals` is the scenario's own numbers (generated only where it was
    # silent). A patient the scenario gives a heart rate to is a patient with a
    # pulse; `generate` leaves `hr` None for the pulseless.
    hr = session._vitals.hr
    return next_hint(
        parse_actions(session.body), said, phase or session.phase,
        pulse_present=None if hr is None else hr > 0,
        # What the trainee can actually read off the monitor right now.
        on_monitor=frozenset(session.known_vitals()),
    )
