"""Turn a recorded session back into something a person can mark up.

Every line of every call is already in the `turns` table — the sim writes them
as it goes. This renders them as markdown so a reviewer can say which lines
earned their place and which are filler.

**Free text, not checkboxes.** A reviewer writes whatever they want under any
line; nothing here parses it back. The file is for a human to write and for a
human to read, so it stays plain.

**Repeats are counted rather than left to be noticed.** A call that says
"Nothing has changed since your last look." three times is doing something wrong,
and the tally at the foot of the file says so without the reviewer keeping count.
"""

import json
from collections import Counter
from typing import Iterable, Optional

SPEAKER_LABEL = {
    "dispatcher": "DISPATCH",
    "narrator": "SCENE",
    "patient": "PATIENT",
    "sim": "SIM",
    "emt": "YOU",
}

#: Lines the sim emits to keep the loop turning. Counted separately, because a
#: reviewer cares about how often they fire, not about reading each one.
FILLER = frozenset({
    "Done.",
    "Nothing has changed since your last look.",
    "The patient has nothing more to add.",
    "Nothing about that stands out.",
})

HEADER_NOTE = (
    "Write a note on the line below any entry you want to comment on — free "
    "text, as much or as little as you like. Nothing parses it; it is read by a "
    "person."
)


def _voices(session: dict) -> str:
    """Whether Claude actually spoke, rather than whether it was asked to.

    This line used to read `personas`, the request flag, and so said "Claude
    voices" over a call in which a revoked key had failed every single turn.
    Every LLM failure degrades to exactly the deterministic text, so the two
    calls are otherwise indistinguishable — and a reviewer reading a flat patient
    or a "Done." needs to know which one they are looking at before deciding
    what went wrong. The counts come from `llm_json`, written at the end of the
    call from the tally `safe_speak` keeps.
    """
    if not session.get("personas"):
        return "deterministic"
    try:
        health = json.loads(session.get("llm_json") or "") or {}
    except ValueError:
        health = {}
    if not health:
        # Personas were asked for, but the call predates the tally or never
        # ended. Do not claim more than that.
        return "Claude voices requested"
    answered, attempted = health.get("answered", 0), health.get("attempted", 0)
    if attempted and answered == attempted:
        return f"Claude voices ({answered} of {attempted})"
    if answered:
        return (f"**Claude voices PARTIAL — {answered} of {attempted}**"
                f" — {health.get('first_error') or 'no reason recorded'}")
    return (f"**Claude NEVER ANSWERED — 0 of {attempted}, every line is canned**"
            f" — {health.get('first_error') or 'no reason recorded'}")


def _environment(raw: str) -> str:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return ""
    bits = [
        data.get("time_of_day"),
        f"hour {data['hour']}" if data.get("hour") is not None else None,
        data.get("weather"),
        data.get("season"),
    ]
    return ", ".join(b for b in bits if b)


#: How a graded action reads in the debrief. The symbol carries the status so a
#: reviewer skimming the left margin can find the misses without reading prose.
_STATUS_MARK = {"hit": "[x]", "partial": "[~]", "missed": "[ ]"}


def _debrief(session: dict) -> list[str]:
    """The score and what earned it, from the stored `grade_json`.

    The transcript used to end at the last spoken line. Everything the debrief
    said — the summary, the critical errors, which steps were missed, the
    scenario's own rationale — lived only in the browser's response to the call
    that ended the session, and was gone as soon as the page was closed. So the
    one artifact a reviewer takes away held the questions and none of the marking.
    """
    try:
        grade = json.loads(session.get("grade_json") or "") or {}
    except ValueError:
        return []
    if not grade:
        return []

    lines = ["---", "", "## Debrief", ""]
    if grade.get("points_possible") is not None:
        verdict = "PASS" if grade.get("passed") else "FAIL"
        lines += [f"**{verdict}** — {grade['points']} of {grade['points_possible']} points", ""]
    if grade.get("summary"):
        lines += [grade["summary"], ""]

    for label, earned, possible in grade.get("breakdown") or ():
        lines.append(f"- {label}: {earned}" + (f" / {possible}" if possible else ""))
    if grade.get("breakdown"):
        lines.append("")

    for error in grade.get("critical_errors") or ():
        lines.append(f"- **CRITICAL — {error.get('detail', error.get('rule', ''))}**")
        if error.get("guidance"):
            lines.append(f"      {error['guidance']}")
    if grade.get("critical_errors"):
        lines.append("")

    if actions := grade.get("actions") or ():
        lines += ["### Correct actions", ""]
        for action in actions:
            mark = _STATUS_MARK.get(action.get("status", ""), "[?]")
            lines.append(f"{mark} {action.get('index', '?'):>2}. {action.get('action', '')}")
            # What the trainee actually said, so a missed step can be told apart
            # from a step done in words the grader did not recognize.
            if action.get("said"):
                lines.append(f"       you said: {action['said']}")
            if action.get("note"):
                lines.append(f"       {action['note']}")
        lines.append("")

    if missed := grade.get("red_flags_missed") or ():
        lines += ["### Red flags not mentioned", ""]
        lines += [f"- {flag}" for flag in missed] + [""]

    if grade.get("rationale"):
        lines += ["### Why", "", grade["rationale"], ""]

    # Written by the model, and only present when it was asked for and answered.
    # A `Debrief` is a summary plus three bullet lists; anything the model said
    # that the rubric did not support has already been stripped before storage.
    if narrative := grade.get("narrative") or {}:
        lines += ["### What Claude said about the call", ""]
        if narrative.get("summary"):
            lines += [narrative["summary"], ""]
        for heading, key in (
            ("Done well", "pros"),
            ("Went wrong", "cons"),
            ("Do differently", "improvements"),
        ):
            if bullets := narrative.get(key) or ():
                lines += [f"**{heading}**", ""]
                lines += [f"- {b}" for b in bullets] + [""]

    return lines


def render(session: dict, turns: Iterable[dict]) -> str:
    """One session as markdown. `session` and `turns` are plain row dicts."""
    turns = list(turns)
    started = (session.get("started_at") or "")[:16].replace("T", " ")
    lines = [
        f"# {session.get('scenario_id', '?')} · {started}",
        "",
    ]

    facts = [f"session `{session.get('id', '')}`"]
    if session.get("difficulty"):
        facts.append(session["difficulty"])
    if environment := _environment(session.get("environment_json", "")):
        facts.append(environment)
    facts.append(_voices(session))
    if session.get("score") is None:
        facts.append("**never ended — no debrief**")
    elif session.get("points_possible") is None:
        # Written before the score stopped being a percentage. Labelled rather
        # than silently redrawn on the new scale, which it was never measured on.
        facts.append(f"scored {session['score']}% (old scale)")
    else:
        verdict = "PASS" if session.get("passed") else "FAIL"
        facts.append(f"{session['score']}/{session['points_possible']} points  ·  {verdict}")
    lines += ["  ·  ".join(facts), "", HEADER_NOTE, "", "---", ""]

    for turn in turns:
        who = SPEAKER_LABEL.get(turn["speaker"], turn["speaker"].upper())
        lines.append(f"{turn['seq']:02d}  {turn['phase']:<16} {who:<9} {turn['utterance']}")
        lines.append("")

    repeats = Counter(t["utterance"] for t in turns)
    duplicated = [(text, n) for text, n in repeats.most_common() if n > 1]
    if duplicated:
        lines += ["---", "", "## Repeated lines", ""]
        for text, n in duplicated:
            flag = "  ← filler" if text in FILLER else ""
            lines.append(f"- ×{n}  {text}{flag}")
        lines.append("")

    emt = sum(1 for t in turns if t["speaker"] == "emt")
    filler = sum(1 for t in turns if t["utterance"] in FILLER)
    lines += [
        "---",
        "",
        f"{len(turns)} lines · {emt} from the EMT · {filler} filler "
        f"({filler * 100 // max(1, len(turns))}%)",
        "",
    ]
    lines += _debrief(session)
    return "\n".join(lines)


def filename(session: dict) -> str:
    """A name that sorts by scenario then time, and stays unique per session."""
    started = (session.get("started_at") or "").replace("-", "").replace(":", "")
    stamp = started[:13].replace("T", "-")     # YYYYMMDD-HHMM
    short = (session.get("id") or "")[:4]
    return f"{session.get('scenario_id', 'session')}-{stamp}-{short}.md"


def load(conn, session_id: Optional[str] = None) -> tuple[dict, list[dict]]:
    """One session and its turns. Latest session when no id is given."""
    if session_id:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return {}, []
    session = dict(row)
    turns = [
        dict(t) for t in conn.execute(
            "SELECT * FROM turns WHERE session_id = ? ORDER BY seq", (session["id"],)
        )
    ]
    return session, turns
