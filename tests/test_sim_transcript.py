"""
Exporting a call for review.
Offline: rows in, markdown out — no server and no LLM.
"""
import pytest

from ems.sim import store, transcript

SESSION = {
    "id": "9d61ef91c9f54316b9ac08a67c26deff",
    "scenario_id": "src1-s03",
    "difficulty": "intermediate",
    "started_at": "2026-08-15T01:26:40",
    "score": None,
    "environment_json": '{"time_of_day": "night", "hour": 21, "weather": "rain", "season": "summer"}',
}


def turn(seq, phase, speaker, utterance):
    return {"seq": seq, "phase": phase, "speaker": speaker, "utterance": utterance}


TURNS = [
    turn(0, "TONE_OUT", "dispatcher", "Medic 41, respond for: Sick young child."),
    turn(1, "SIZE_UP", "emt", "check if the scene is safe"),
    turn(2, "RESULT", "narrator", "Done."),
    turn(3, "DECIDE", "emt", "give oxygen"),
    turn(4, "RESULT", "narrator", "Done."),
    turn(5, "OBSERVE", "narrator", "Nothing has changed since your last look."),
]


# ── the file itself ──────────────────────────────────────────────────────────

def test_every_line_appears_with_its_sequence_and_speaker():
    text = transcript.render(SESSION, TURNS)
    assert "00  TONE_OUT" in text
    assert "DISPATCH" in text and "YOU" in text and "SCENE" in text
    for t in TURNS:
        assert t["utterance"] in text


def test_the_header_carries_what_the_call_ran_under():
    text = transcript.render(SESSION, TURNS)
    assert "src1-s03" in text
    assert "intermediate" in text
    assert "night" in text and "rain" in text and "hour 21" in text


def test_an_unfinished_call_says_so_rather_than_showing_no_score():
    """The session that prompted this feature never ended; that is the finding."""
    assert "never ended" in transcript.render(SESSION, TURNS)


def test_a_finished_call_shows_its_points_and_the_verdict():
    text = transcript.render(
        {**SESSION, "score": 19, "points_possible": 27, "passed": 1}, TURNS)
    assert "19/27 points" in text
    assert "PASS" in text
    assert "never ended" not in text
    assert "/100" not in text


def test_a_call_graded_before_the_scale_changed_says_so():
    """A legacy 72 was a percentage. Relabelling it 72/27 would be a lie.

    `points_possible IS NULL` is what separates the two, so an old call is never
    redrawn on a scale it was not measured with.
    """
    text = transcript.render({**SESSION, "score": 72}, TURNS)
    assert "72% (old scale)" in text


def test_repeated_lines_are_counted_not_left_to_be_noticed():
    text = transcript.render(SESSION, TURNS)
    assert "## Repeated lines" in text
    assert "×2  Done." in text


def test_known_filler_is_flagged_as_such():
    text = transcript.render(SESSION, TURNS)
    assert "Done.  ← filler" in text


def test_the_footer_totals_the_filler():
    text = transcript.render(SESSION, TURNS)
    assert "6 lines · 2 from the EMT" in text
    assert "3 filler (50%)" in text


def test_a_call_with_no_repeats_has_no_repeat_section():
    text = transcript.render(SESSION, TURNS[:2])
    assert "## Repeated lines" not in text


def test_the_reviewer_is_told_to_write_free_text():
    assert "free text" in transcript.render(SESSION, TURNS)


def test_an_empty_call_still_renders():
    assert "src1-s03" in transcript.render(SESSION, [])


def test_a_broken_environment_blob_does_not_break_the_export():
    text = transcript.render({**SESSION, "environment_json": "not json"}, TURNS)
    assert "src1-s03" in text


# ── the filename ─────────────────────────────────────────────────────────────

def test_the_filename_sorts_by_scenario_then_time():
    assert transcript.filename(SESSION) == "src1-s03-20260815-0126-9d61.md"


def test_two_runs_of_one_scenario_do_not_collide():
    other = {**SESSION, "id": "aaaa1111", "started_at": "2026-08-15T09:03:00"}
    assert transcript.filename(SESSION) != transcript.filename(other)


# ── through the API ──────────────────────────────────────────────────────────

pytest.importorskip("fastapi", reason="install with: pip install -e '.[web,dev]'")

from fastapi.testclient import TestClient  # noqa: E402

from ems.web.server import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db=tmp_path / "t.db")) as c:
        yield c


@pytest.fixture
def started(client):
    """A signed-in EMT mid-call. The transcript is theirs, not the public's."""
    user = store.upsert_user(client.app.state.db, "wv", "ry", years_experience=3)
    store.set_username(client.app.state.db, user["id"], "ry-wv")
    store.set_password(client.app.state.db, user["id"], "practice-password-0000")
    token = client.post("/api/login", json={
        "username": "ry-wv", "password": "practice-password-0000",
    }).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client.post("/api/session/start", json={"scenario_id": "src1-s01"}).json()


def test_the_endpoint_returns_a_downloadable_markdown_file(client, started):
    response = client.get(f"/api/session/{started['session_id']}/transcript")
    assert response.status_code == 200
    assert "text/markdown" in response.headers["content-type"]
    assert "attachment" in response.headers["content-disposition"]
    assert "src1-s01" in response.headers["content-disposition"]


def test_the_transcript_is_available_mid_call(client, started):
    """Turns are written on every request, so you can export without finishing."""
    client.post(f"/api/session/{started['session_id']}/turn",
                json={"utterance": "Scene is safe, gloves on, one patient"})
    body = client.get(f"/api/session/{started['session_id']}/transcript").text
    assert "Scene is safe, gloves on, one patient" in body
    assert "never ended" in body


def test_ending_the_call_puts_the_score_in_the_transcript(client, started):
    session_id = started["session_id"]
    client.post(f"/api/session/{session_id}/turn", json={"utterance": "Scene is safe"})
    client.post(f"/api/session/{session_id}/end", json={})
    assert "never ended" not in client.get(f"/api/session/{session_id}/transcript").text


def test_an_unknown_session_is_404(client, started):
    assert client.get("/api/session/nope/transcript").status_code == 404


def test_a_transcript_needs_a_login(client, started):
    """A call transcript is a record of one person's practice. Without this it
    was readable by anyone who could guess a session id."""
    session_id = started["session_id"]
    del client.headers["Authorization"]
    assert client.get(f"/api/session/{session_id}/transcript").status_code == 401


# ── which build spoke ────────────────────────────────────────────────────────

def test_the_header_says_whether_claude_voiced_the_call():
    """Otherwise a fallback is indistinguishable from a deterministic run.

    Every LLM failure — no key, a rate limit, a wrong model id — degrades to
    exactly the deterministic text, so the transcript of a call that never
    reached Claude reads the same as one that did. A reviewer deciding whether
    a bad line is the model's fault or the state machine's has to be told.
    """
    assert "deterministic" in transcript.render(SESSION, TURNS)
    assert "Claude voices" in transcript.render({**SESSION, "personas": 1}, TURNS)


def test_an_older_call_reads_as_deterministic():
    """Rows written before the column existed: the LLM was opt-in and off."""
    assert "deterministic" in transcript.render(SESSION, TURNS)


# ── the debrief reaches the file ────────────────────────────────────────────

def _graded_session(grade_extra: dict | None = None) -> dict:
    import json
    grade = {
        "summary": "You got 2 of the 3 key steps.",
        "breakdown": [["Scene size-up", 3, 5], ["Correct actions", 4, 6]],
        "critical_errors": [{"rule": "oxygen-flow-missing",
                             "detail": "NRB applied without a flow rate",
                             "guidance": "Say the number as well as the device."}],
        "actions": [
            {"index": 1, "action": "Open the airway", "status": "hit",
             "said": "I'll open his airway", "note": ""},
            {"index": 2, "action": "Give oxygen", "status": "missed", "said": "", "note": ""},
        ],
        "red_flags_missed": ["A rate under 10 read as calm breathing"],
        "rationale": "A slow rate is easy to read as calm. It is not.",
    }
    grade.update(grade_extra or {})
    return {"id": "abcd", "scenario_id": "src34-s04", "started_at": "2026-09-05T10:00:00",
            "score": 55, "grade_json": json.dumps(grade), "environment_json": "{}"}


def test_the_debrief_is_in_the_downloaded_transcript():
    """It used to end at the last spoken line.

    Everything the debrief said lived only in the browser's response to the call
    that ended the session, so the one artifact anybody keeps held the questions
    and none of the marking.
    """
    out = transcript.render(_graded_session(), [])
    assert "## Debrief" in out
    assert "You got 2 of the 3 key steps." in out
    assert "CRITICAL" in out and "Say the number as well as the device." in out
    assert "[x]  1. Open the airway" in out
    assert "[ ]  2. Give oxygen" in out
    assert "A slow rate is easy to read as calm." in out


def test_a_missed_step_can_be_told_from_one_the_grader_did_not_recognize():
    out = transcript.render(_graded_session(), [])
    assert "you said: I'll open his airway" in out


def test_the_model_narrative_is_rendered_when_it_was_stored():
    out = transcript.render(_graded_session({"narrative": {
        "summary": "A composed call.",
        "pros": ["Read the two numbers together."],
        "cons": ["Never palpated the abdomen."],
        "improvements": ["Say the reassessment interval out loud."],
    }}), [])
    assert "What Claude said about the call" in out
    assert "A composed call." in out
    assert "- Read the two numbers together." in out
    assert "- Never palpated the abdomen." in out


def test_an_unfinished_call_renders_without_a_debrief():
    """No grade yet is the normal mid-call state, not an error."""
    out = transcript.render(
        {"id": "abcd", "scenario_id": "src34-s04", "started_at": "2026-09-05T10:00:00",
         "environment_json": "{}"}, [])
    assert "## Debrief" not in out
    assert "never ended — no debrief" in out


# ── whether Claude answered, not whether it was asked ───────────────────────
#
# Reported from a phone test: a full call of canned lines with the header still
# claiming "Claude voices". The flag said what was *requested*; every LLM
# failure degrades to exactly the deterministic text, so nothing recorded what
# happened and the two calls read identically.

import json as _json


def _voiced(**health) -> dict:
    session = {"id": "abcd", "scenario_id": "src1-s06", "personas": 1,
               "started_at": "2026-09-06T00:44:00", "environment_json": "{}"}
    return {**session, "llm_json": _json.dumps(health)} if health else session


def test_a_call_where_claude_answered_everything_says_so():
    out = transcript.render(_voiced(attempted=14, answered=14, failed=0), [])
    assert "Claude voices (14 of 14)" in out


def test_a_call_where_claude_never_answered_does_not_claim_it_did():
    """The reported bug. A dead key must not read like a working one."""
    out = transcript.render(
        _voiced(attempted=14, answered=0, failed=14,
                first_error="AuthenticationError: invalid x-api-key"), [])
    assert "NEVER ANSWERED" in out
    assert "0 of 14" in out
    assert "invalid x-api-key" in out, "the reason has to travel with the finding"


def test_a_call_that_lost_claude_partway_reports_both_numbers():
    out = transcript.render(
        _voiced(attempted=14, answered=9, failed=5, first_error="RateLimitError: 429"), [])
    assert "PARTIAL — 9 of 14" in out
    assert "429" in out


def test_a_call_that_never_asked_for_claude_is_plainly_deterministic():
    out = transcript.render(
        {"id": "a", "scenario_id": "x", "personas": 0,
         "started_at": "2026-09-06T00:44:00", "environment_json": "{}"}, [])
    assert "deterministic" in out
    assert "Claude" not in out


def test_a_call_recorded_before_the_tally_existed_claims_only_what_it_knows():
    """`personas` alone proves the request, not the answer. Say that much."""
    out = transcript.render(_voiced(), [])
    assert "Claude voices requested" in out
    assert "of" not in out.splitlines()[2].split("·")[1]
