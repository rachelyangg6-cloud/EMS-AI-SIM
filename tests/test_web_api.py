"""
Tests for the simulator API (Project 4).
Offline: no LLM, and the database is a throwaway file per test.
"""
from datetime import datetime

import pytest

pytest.importorskip("fastapi", reason="install with: pip install -e '.[web,dev]'")

from fastapi.testclient import TestClient  # noqa: E402

from ems.sim import store  # noqa: E402
from ems.sim.scene import WEATHER_STATES  # noqa: E402
from ems.web.server import create_app  # noqa: E402

SIZE_UP = ("Scene is safe, gloves and eye protection on, one patient, nature of illness is "
           "respiratory failure, requesting ALS.")
GOOD_CALL = [
    "She's cyanotic, one-word dyspnea, SpO2 82, mental status declining — breathing is inadequate",
    "Begin assisted ventilation with a bag-valve mask on oxygen at 15 L/min with a reservoir bag",
    "Ventilate at about 10 breaths per minute, only to visible chest rise",
    "No inhaler — she is not alert enough. Call ALS and transport, reassessing chest rise",
]


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "test.db")) as c:
        yield c


def account(client, name="ry", username="", password="practice-password-0000",
            corp="westchester-vac", **fields) -> dict:
    """Make an account the only way accounts are made — from the store, as
    `protocol-users` does — and return it. There is no sign-up endpoint."""
    db = client.app.state.db
    user = store.upsert_user(db, corp, name, **fields)
    store.set_username(db, user["id"], username or store.generate_username(name, corp))
    store.set_password(db, user["id"], password)
    return store.get_user(db, user["id"])


def sign_in(client, username, password="practice-password-0000") -> dict:
    """Log in and leave the token on the client, as the browser would."""
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    data = response.json()
    client.headers["Authorization"] = f"Bearer {data['token']}"
    return data


@pytest.fixture
def user(client):
    """The signed-in EMT. Every test that touches a real route needs one."""
    created = account(client, "ry", years_experience=6, region="Westchester, NY",
                      display_name="Westchester VAC")
    sign_in(client, created["username"])
    return created


def start(client, user, **kwargs):
    """Open a call. Deterministic unless the test asks for the LLM.

    The server turns personas and the narrative debrief on by default, which is
    right for a trainee and wrong for a test: it would put a live Claude call in
    the path of every assertion here the moment a developer has an `.env`, and
    "offline, no LLM" is the contract this module runs under. Tests that want
    the model pass the flags themselves.
    """
    body = {"scenario_id": "src1-s01", "personas": False,
            "narrative_debrief": False, **kwargs}
    response = client.post("/api/session/start", json=body)
    assert response.status_code == 200, response.text
    return response.json()


# ── signing in ───────────────────────────────────────────────────────────────

def test_the_right_credentials_return_a_token_and_a_profile(client):
    created = account(client, "ry")
    data = sign_in(client, created["username"])
    assert data["token"]
    assert data["user"]["name"] == "ry"
    assert data["user"]["corp_slug"] == "westchester-vac"


def test_the_login_response_carries_no_hash(client):
    created = account(client, "ry")
    data = sign_in(client, created["username"])
    assert "password_hash" not in data["user"] and "password_salt" not in data["user"]


def test_a_wrong_password_and_an_unknown_user_are_the_same_401(client):
    account(client, "ry")
    wrong = client.post("/api/login", json={"username": "ry-wvac", "password": "nope"})
    absent = client.post("/api/login", json={"username": "ghost-wvac", "password": "nope"})
    assert wrong.status_code == absent.status_code == 401
    # Identical text as well as identical status: a different message would
    # enumerate who has an account just as well as a different status would.
    assert wrong.json()["detail"] == absent.json()["detail"]


def test_the_token_rehydrates_a_profile(client, user):
    """What a page refresh does — the client holds a token, not a profile."""
    assert client.get("/api/me").json()["id"] == user["id"]


def test_logging_out_makes_the_token_useless(client, user):
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_logging_out_twice_is_not_an_error(client, user):
    client.post("/api/logout")
    assert client.post("/api/logout").status_code == 200


# ── what a request without a token can reach ─────────────────────────────────

def test_every_route_that_touches_practice_needs_a_token(client):
    """The hole this feature closes. Each of these used to answer anybody."""
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/profile").status_code == 401
    assert client.post("/api/profile", json={"name": "x"}).status_code == 401
    assert client.post("/api/session/start", json={}).status_code == 401
    assert client.get("/api/history").status_code == 401
    assert client.get("/api/history/anything").status_code == 401
    assert client.post("/api/session/x/turn", json={"utterance": "hi"}).status_code == 401
    assert client.post("/api/session/x/end").status_code == 401
    assert client.get("/api/session/x/transcript").status_code == 401


def test_health_stays_open(client):
    """The one route a load balancer needs and a stranger learns nothing from."""
    assert client.get("/api/health").status_code == 200


def test_corpus_stays_open(client):
    """The Features page's numbers, readable without signing in.

    The other exception to the token rule, and the test that records it as
    deliberate rather than an oversight.
    """
    response = client.get("/api/corpus")
    assert response.status_code == 200
    assert response.json()["pages"]["total"] > 0


def test_corpus_exposes_no_user_or_session_data(client):
    """Pinned key set: a new field cannot quietly widen an open route.

    If something derived from `ems.db` belongs on that page, it belongs behind
    `current_user`, and this test should fail until that move is made.
    """
    assert set(client.get("/api/corpus").json()) == {
        "pages", "scenarios", "topics", "citations",
        "sources", "lessons", "models", "files",
    }


def test_a_malformed_or_expired_token_is_a_401(client, user):
    for header in ("", "Bearer", "Bearer nonsense", "Basic abc123",
                   client.headers["Authorization"].replace("Bearer", "Token")):
        assert client.get("/api/me", headers={"Authorization": header}).status_code == 401


# ── editing your own profile ─────────────────────────────────────────────────

def test_a_profile_edit_updates_it_in_place(client, user):
    again = client.post("/api/profile", json={"years_experience": 7,
                                              "email": "ry@example.org"}).json()
    assert again["id"] == user["id"]
    assert again["years_experience"] == 7 and again["email"] == "ry@example.org"


def test_an_omitted_field_is_left_alone(client, user):
    """The form does not resend everything, and a default here would erase it."""
    client.post("/api/profile", json={"scope_level": "Paramedic", "email": "r@x.org"})
    again = client.post("/api/profile", json={"years_experience": 9}).json()
    assert again["scope_level"] == "Paramedic" and again["email"] == "r@x.org"


def test_renaming_keeps_the_same_profile_and_its_history(client, user):
    """Not a new row: `upsert_user` keys on (corp_slug, name), so a rename that
    went through it would leave the practice history behind on the old one."""
    start(client, user)
    again = client.post("/api/profile", json={"name": "Rachel Yang"}).json()
    assert again["id"] == user["id"] and again["name"] == "Rachel Yang"
    assert len(client.get("/api/history").json()["sessions"]) == 1


def test_a_client_cannot_promote_itself_to_certified(client, user):
    """The whole point of the login. This field decides who may write to the
    shared corpus, and it is set by the CLI or not at all."""
    client.post("/api/profile", json={"training_status": "certified"})
    assert client.get("/api/me").json()["training_status"] == "apprentice"


def test_a_client_cannot_move_itself_to_another_department(client, user):
    client.post("/api/profile", json={"corp_slug": "somewhere-else"})
    assert client.get("/api/me").json()["corp_slug"] == "westchester-vac"


def test_a_misspelled_scope_level_is_rejected_not_ignored(client, user):
    """Free text would mean a silently wrong scope nobody can account for."""
    assert client.post("/api/profile", json={"scope_level": "paramedic"}).status_code == 422


# ── starting a call ──────────────────────────────────────────────────────────

def test_the_environment_reaches_the_scene(client, user):
    scene = start(client, user, environment={"time_of_day": "night", "weather": "snow"})["scene"]
    assert (scene["time_of_day"], scene["weather"]) == ("night", "snow")


def test_unknown_environment_keys_are_ignored(client, user):
    scene = start(client, user, environment={"aqi": 412, "time_of_day": "night"})["scene"]
    assert scene["time_of_day"] == "night"


def test_an_unasked_for_environment_is_derived_rather_than_left_at_noon(client, user):
    """No environment in the request used to mean a clear day, always."""
    scene = start(client, user)["scene"]
    assert scene["time_of_day"] in ("day", "night", "dawn", "dusk")
    assert scene["weather"] in WEATHER_STATES
    assert scene["hour"] == datetime.now().hour


def test_forcing_conditions_shows_up_in_the_sky(client, user):
    """The instructor's smoke day has to be visible, not just weighted."""
    scene = start(client, user, conditions={"aqi": 400})["scene"]
    assert scene["weather"] == "smoke"


def test_an_explicit_environment_still_beats_the_derived_one(client, user):
    scene = start(client, user, conditions={"aqi": 400}, environment={"weather": "rain"})["scene"]
    assert scene["weather"] == "rain"


def test_forcing_a_time_of_day_drops_the_contradicting_clock_hour(client, user):
    """Ask for night at 20:00 and the renderer must not draw a dusk sky."""
    scene = start(client, user, environment={"time_of_day": "night"})["scene"]
    assert scene["time_of_day"] == "night"
    assert scene["hour"] is None


def test_an_explicit_hour_is_kept_alongside_an_explicit_time_of_day(client, user):
    scene = start(client, user, environment={"time_of_day": "night", "hour": 2})["scene"]
    assert (scene["time_of_day"], scene["hour"]) == ("night", 2)


def test_a_level_draws_an_approved_scenario_of_that_difficulty(client, user):
    data = client.post("/api/session/start", json={"level": "basic", "seed": 7}).json()
    assert data["difficulty"] == "basic"


def test_a_scenario_id_still_deals_exactly_that_call(client, user):
    assert start(client, user, scenario_id="src1-s01")["scenario_id"] == "src1-s01"


def test_a_topic_that_matches_nothing_says_what_it_might_have_meant(client, user):
    response = client.post("/api/session/start", json={"scenario_id": "hypoglicemia"})
    assert response.status_code == 404
    assert "hypoglycemia" in response.json()["detail"]


def test_start_rejects_unknown_scenarios_levels_and_modes(client, user):
    def code(**body):
        return client.post("/api/session/start", json=body).status_code

    assert code(scenario_id="src99-s99") == 404
    assert code(level="impossible") == 400
    assert code(mode="nonsense") == 400
    # "generated" was a placeholder that 400d; it is a real mode now. With no
    # drafts awaiting review it is 404 — nothing to deal, not a bad request.
    assert code(mode="generated") in (200, 404)


def test_start_ignores_a_user_id_in_the_body(client, user):
    """The call belongs to the token holder. A body field naming someone else
    must not practice into their history — and it is not even read."""
    other = account(client, "partner", years_experience=1)
    client.post("/api/session/start", json={"scenario_id": "src1-s01",
                                            "user_id": other["id"]})
    row = client.app.state.db.execute("SELECT user_id FROM sessions").fetchone()
    assert row["user_id"] == user["id"]


# ── playing the call ─────────────────────────────────────────────────────────

def test_a_turn_returns_everything_the_sim_says_back(client, user):
    session_id = start(client, user)["session_id"]
    data = client.post(f"/api/session/{session_id}/turn", json={"utterance": SIZE_UP}).json()
    phases = [e["phase"] for e in data["events"]]
    assert phases == ["SCENE_NARRATION", "TURN"]
    assert data["awaiting_input"] is True


def test_the_end_route_finishes_the_call(client, user):
    session_id = start(client, user)["session_id"]
    client.post(f"/api/session/{session_id}/turn", json={"utterance": SIZE_UP})
    data = client.post(f"/api/session/{session_id}/end").json()
    assert data["done"] is True
    assert "grade" in data


def test_turns_on_an_unknown_or_finished_session_are_rejected(client, user):
    assert client.post("/api/session/nope/turn", json={"utterance": "hi"}).status_code == 404

    session_id = start(client, user)["session_id"]
    client.post(f"/api/session/{session_id}/end")
    response = client.post(f"/api/session/{session_id}/turn", json={"utterance": "hi"})
    assert response.status_code == 409


# ── persistence ──────────────────────────────────────────────────────────────

def test_the_session_and_its_turns_land_in_sqlite(client, user):
    session_id = start(client, user)["session_id"]
    client.post(f"/api/session/{session_id}/turn", json={"utterance": SIZE_UP})
    client.post(f"/api/session/{session_id}/end")

    conn = client.app.state.db
    row = store.get_session(conn, session_id)
    assert row["scenario_id"] == "src1-s01"
    assert row["user_id"] == user["id"]
    assert row["ended_at"] and row["score"] is not None
    assert row["grade"]["size_up"]["covered"]

    turns = store.get_turns(conn, session_id)
    assert [t["seq"] for t in turns] == list(range(len(turns)))
    emt = [t for t in turns if t["speaker"] == "emt"]
    assert emt[0]["utterance"] == SIZE_UP
    assert "scene-safety" in emt[0]["intents"]
    # No physiology model yet, so no turn may claim a vitals change.
    assert all(t["vitals_json"] is None for t in turns)


def test_history_returns_the_graded_debrief(client, user):
    session_id = start(client, user)["session_id"]
    client.post(f"/api/session/{session_id}/turn", json={"utterance": SIZE_UP})
    client.post(f"/api/session/{session_id}/end")

    sessions = client.get("/api/history").json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id
    assert sessions[0]["grade"]["scenario_id"] == "src1-s01"

    detail = client.get(f"/api/history/{session_id}").json()
    assert detail["turns"]
    assert detail["grade"]["points"] == sessions[0]["score"]
    assert detail["grade"]["points_possible"] == sessions[0]["points_possible"]


def test_history_is_scoped_to_one_user(client, user):
    """And there is no parameter that would widen it: history is always the
    token holder's, so one EMT cannot read another's practice."""
    other = account(client, "partner")
    session_id = start(client, user)["session_id"]
    client.post(f"/api/session/{session_id}/end")
    assert len(client.get("/api/history").json()["sessions"]) == 1

    sign_in(client, other["username"])
    assert client.get("/api/history").json()["sessions"] == []
    assert client.get("/api/history", params={"user_id": user["id"]}).json()["sessions"] == []


def test_another_emts_call_is_a_404_not_a_403(client, user):
    """404 rather than 403: a 403 confirms the id exists, which turns this into
    a way to count somebody else's practice."""
    session_id = start(client, user)["session_id"]
    client.post(f"/api/session/{session_id}/end")

    sign_in(client, account(client, "partner")["username"])
    assert client.get(f"/api/history/{session_id}").status_code == 404
    assert client.get(f"/api/session/{session_id}/transcript").status_code == 404
    assert client.post(f"/api/session/{session_id}/end").status_code == 404
    assert client.post(f"/api/session/{session_id}/turn",
                       json={"utterance": SIZE_UP}).status_code == 404


def test_an_abandoned_session_leaves_its_transcript_behind(client, user):
    """A call that is never ended still has its turns on disk, ungraded."""
    session_id = start(client, user)["session_id"]
    client.post(f"/api/session/{session_id}/turn", json={"utterance": SIZE_UP})

    row = store.get_session(client.app.state.db, session_id)
    assert row["ended_at"] is None and row["score"] is None
    assert store.get_turns(client.app.state.db, session_id)


def test_history_for_an_unknown_session_is_404(client, user):
    assert client.get("/api/history/no-such-session").status_code == 404


# ── vitals gating over the wire ──────────────────────────────────────────────

# ── the LLM layer is on by default, and still optional ───────────────────────

def test_the_llm_layer_is_on_unless_a_caller_says_otherwise(client, user):
    """Claude plays the call by default — a trainee is never asked to opt in."""
    response = client.post("/api/session/start", json={"scenario_id": "src1-s01"})
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    assert client.app.state.live[session_id].persona is not None
    assert client.app.state.narrative[session_id] is True


def test_the_llm_layer_can_be_switched_off(client, user):
    """The deterministic call is what `?llm=off` and every test here rely on."""
    session_id = start(client, user)["session_id"]
    assert client.app.state.live[session_id].persona is None
    assert client.app.state.narrative[session_id] is False

    client.post(f"/api/session/{session_id}/turn", json={"utterance": SIZE_UP})
    grade = client.post(f"/api/session/{session_id}/end").json()["grade"]
    assert "narrative" not in grade and "narrative_error" not in grade


def test_no_credentials_costs_the_voices_and_not_the_call(client, user, monkeypatch):
    """The whole arc still plays when every LLM call fails.

    This is what makes the default safe to flip: personas on with a dead key
    must degrade to the scenario's own words, not to a broken call.
    """
    from ems.web import server

    def boom(*a, **kw):
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    monkeypatch.setattr(server.persona, "call_llm", boom)
    monkeypatch.setattr(server, "grade_llm", boom)

    session_id = client.post(
        "/api/session/start", json={"scenario_id": "src1-s01"}
    ).json()["session_id"]
    client.post(f"/api/session/{session_id}/turn", json={"utterance": SIZE_UP})
    grade = client.post(f"/api/session/{session_id}/end").json()["grade"]

    assert grade["points"] >= 0 and grade["points_possible"] > 0
    # The paragraph is missing and says why; the result is untouched.
    assert "narrative" not in grade and grade["narrative_error"]


def test_personas_and_narrative_can_be_turned_on(client, user, monkeypatch):
    from ems.sim.debrief import Debrief
    from ems.web import server

    # `safe_speak`, not `speak` — the server wraps the persona so a rate limit
    # loses a line rather than the whole call.
    monkeypatch.setattr(server.persona, "safe_speak",
                        lambda ctx, who="patient", **kw: "I can't... catch... my breath.")
    monkeypatch.setattr(server, "grade_llm",
                        lambda *a, **kw: Debrief(scenario_id="src1-s01", summary="Solid."))

    data = start(client, user, personas=True, narrative_debrief=True)
    session_id = data["session_id"]
    client.post(f"/api/session/{session_id}/turn", json={"utterance": SIZE_UP})
    reply = client.post(f"/api/session/{session_id}/turn",
                        json={"utterance": "How are you doing?"}).json()
    assert any("catch" in e["text"] for e in reply["events"] if e["phase"] == "ANSWER")

    grade = client.post(f"/api/session/{session_id}/end").json()["grade"]
    assert grade["narrative"]["summary"] == "Solid."


def test_a_failed_narrative_never_costs_the_trainee_their_score(client, user, monkeypatch):
    """No API key is a missing paragraph, not a lost debrief."""
    from ems.web import server

    def boom(*a, **kw):
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    monkeypatch.setattr(server, "grade_llm", boom)
    session_id = start(client, user, narrative_debrief=True)["session_id"]
    client.post(f"/api/session/{session_id}/turn", json={"utterance": SIZE_UP})

    grade = client.post(f"/api/session/{session_id}/end").json()["grade"]
    assert grade["points"] is not None and grade["passed"] in (True, False)
    assert "ANTHROPIC_API_KEY" in grade["narrative_error"]
    stored = store.get_session(client.app.state.db, session_id)
    assert stored["score"] is not None and stored["points_possible"] is not None


# ── voice endpoints: the contract exists, the capability does not ────────────

def test_stt_and_tts_are_declared_but_not_implemented(client):
    """501 so ServerVoice can be written now and pointed here later."""
    tts = client.post("/api/tts", json={"text": "Medic 41, respond.", "persona": "dispatcher"})
    assert tts.status_code == 501
    assert "Piper" in tts.json()["detail"]

    stt = client.post("/api/stt", files={"audio": ("u.webm", b"\x00\x01", "audio/webm")})
    assert stt.status_code == 501
    assert "Whisper" in stt.json()["detail"]


def test_tts_validates_its_contract(client):
    """A wrong body is a 422, not a 501 — the schema is real."""
    assert client.post("/api/tts", json={"persona": "dispatcher"}).status_code == 422


# ── who is allowed to vouch for a scenario ───────────────────────────────────

def test_a_new_account_defaults_to_apprentice(client, user):
    assert user["training_status"] == "apprentice"


def test_editing_a_profile_does_not_demote_a_certified_emt(client, user):
    """The form does not resend every field. An unconditional overwrite would
    quietly take away the right to approve a case."""
    _certify(client, user)
    again = client.post("/api/profile", json={"years_experience": 9}).json()
    assert again["training_status"] == "certified" and again["years_experience"] == 9


# ── reviewing a generated draft from the browser ─────────────────────────────

@pytest.fixture
def draft(tmp_path, monkeypatch):
    """A playable generated draft in an isolated quarantine and corpus."""
    import tests.test_sim_generate as gen_tests
    from ems.sim import generate as gen
    from ems.web import server as server_mod

    quarantine, vetted = tmp_path / "generated", tmp_path / "vetted"
    vetted.mkdir(parents=True, exist_ok=True)
    drafted = gen.draft(["asthma"], llm=gen_tests.stub(gen_tests.GOOD),
                        context=gen_tests.CONTEXT, lessons="")
    path = gen.save_draft(drafted, dest=quarantine)

    # Both namespaces. `server` imported `generated_dir` directly, so patching
    # only the one `review` sees leaves the session start resolving against the
    # real quarantine — and the draft id is date-based, so on the day the repo's
    # own gen-YYYYMMDD-01 was written the ids collide and the test passes while
    # playing the wrong file.
    monkeypatch.setattr(server_mod, "generated_dir", lambda: quarantine)
    monkeypatch.setattr(server_mod.review_lib, "generated_dir", lambda: quarantine)
    monkeypatch.setattr(server_mod, "scenarios_dir", lambda: vetted)
    monkeypatch.setattr(server_mod, "list_generated",
                        lambda *a, **kw: sorted(quarantine.glob("gen-*.md")))
    return {"path": path, "quarantine": quarantine, "vetted": vetted, "id": path.stem}


def _played_generated(client, user, draft):
    """Start a generated-mode call on the draft and end it."""
    started = client.post("/api/session/start", json={
        "mode": "generated", "scenario_id": draft["id"],
    }).json()
    session_id = started["session_id"]
    client.post(f"/api/session/{session_id}/turn", json={"utterance": SIZE_UP})
    client.post(f"/api/session/{session_id}/end")
    return session_id


def _certify(client, user):
    """What `protocol-users promote` does. There is no route for this, which is
    the point — see test_a_client_cannot_promote_itself_to_certified."""
    store.upsert_user(client.app.state.db, user["corp_slug"], user["name"],
                      training_status="certified")
    return store.get_user(client.app.state.db, user["id"])


def test_an_apprentice_cannot_promote_and_the_draft_stays_put(client, user, draft):
    """A 403 that had already moved the file would be the failure that matters."""
    session_id = _played_generated(client, user, draft)
    response = client.post(f"/api/session/{session_id}/review",
                           json={"decision": "approve"})
    assert response.status_code == 403
    assert draft["path"].exists(), "the draft must still be in quarantine"
    assert list(draft["vetted"].glob("gen-*.md")) == []


def test_a_certified_emt_promotes_the_draft_into_the_corpus(client, user, draft):
    from ems.frontmatter import read_page

    _certify(client, user)
    session_id = _played_generated(client, user, draft)
    body = client.post(f"/api/session/{session_id}/review", json={
        "decision": "approve", "comment": "reads like a real call", "realism_rating": 4,
    }).json()

    assert body["location"] == "vetted" and body["status"] == "approved"
    assert not draft["path"].exists(), "an approved draft leaves quarantine"
    promoted = draft["vetted"] / f"{draft['id']}.md"
    frontmatter, _ = read_page(promoted)
    assert frontmatter["status"] == "approved"
    assert frontmatter["labeled_by"] == user["name"]
    assert frontmatter["realism_rating"] == 4
    # Which call the judgement came out of — the other half of the provenance.
    assert frontmatter["reviewed_after_session"] == session_id


def test_a_rejection_keeps_the_draft_and_writes_a_lesson(client, user, draft, tmp_path,
                                                         monkeypatch):
    from ems.frontmatter import read_page
    from ems.sim import review as review_lib

    lessons = tmp_path / "generation-lessons.md"
    monkeypatch.setattr(review_lib, "lessons_path", lambda: lessons)

    _certify(client, user)
    session_id = _played_generated(client, user, draft)
    body = client.post(f"/api/session/{session_id}/review", json={
        "decision": "reject",
        "comment": "A 58-year-old with this history would already be on home oxygen.",
    }).json()

    assert body["lesson_recorded"] and body["location"] == "generated"
    assert draft["path"].exists(), "a rejected draft is kept, not deleted"
    assert read_page(draft["path"])[0]["status"] == "rejected"
    assert "already be on home oxygen" in lessons.read_text()


def test_a_rejection_without_a_comment_is_refused(client, user, draft):
    _certify(client, user)
    session_id = _played_generated(client, user, draft)
    response = client.post(f"/api/session/{session_id}/review",
                           json={"decision": "reject", "comment": "   "})
    assert response.status_code == 422


def test_reviewing_the_same_draft_twice_is_refused(client, user, draft):
    _certify(client, user)
    session_id = _played_generated(client, user, draft)
    client.post(f"/api/session/{session_id}/review", json={"decision": "approve"})
    again = client.post(f"/api/session/{session_id}/review", json={"decision": "approve"})
    assert again.status_code == 409
    assert len(list(draft["vetted"].glob("gen-*.md"))) == 1, "exactly one copy"


def test_a_vetted_case_has_nothing_to_review(client, user):
    _certify(client, user)
    started = start(client, user)
    session_id = started["session_id"]
    client.post(f"/api/session/{session_id}/end")
    response = client.post(f"/api/session/{session_id}/review",
                           json={"decision": "approve"})
    assert response.status_code == 409


def test_an_unfinished_call_cannot_be_reviewed(client, user, draft):
    _certify(client, user)
    started = client.post("/api/session/start", json={
        "mode": "generated", "scenario_id": draft["id"],
    }).json()
    response = client.post(f"/api/session/{started['session_id']}/review",
                           json={"decision": "approve"})
    assert response.status_code == 409


def test_an_unknown_session_is_a_404(client, user):
    assert client.post("/api/session/nope/review",
                       json={"decision": "approve"}).status_code == 404


def test_start_reports_the_mode_so_the_ui_can_offer_review(client, user):
    assert start(client, user)["mode"] == "vetted"


def test_the_review_fixture_plays_the_temp_draft_not_the_repo_one(client, user, draft):
    """Guards the isolation itself. Generated ids are date-based, so a fixture
    that patched only one namespace would silently exercise the repo's own
    quarantine on the day those ids collide."""
    started = client.post("/api/session/start", json={
        "mode": "generated", "scenario_id": draft["id"],
    }).json()
    # The temp draft is the asthma exemplar; the repo's is not.
    tone_out = started["events"][0]["text"]
    assert "asthma" in tone_out.lower() or "wheeze" in tone_out.lower()


# ── setting a draft aside ────────────────────────────────────────────────────

def test_skip_leaves_the_draft_unjudged_in_quarantine(client, user, draft):
    from ems.frontmatter import read_page

    _certify(client, user)
    session_id = _played_generated(client, user, draft)
    body = client.post(f"/api/session/{session_id}/review", json={
        "decision": "skip", "comment": "like it, not sure about the BP yet",
    }).json()

    assert body["decision"] == "skip"
    assert body["status"] == "pending"
    assert body["location"] == "generated"
    assert body["lesson_recorded"] is False
    assert draft["path"].exists(), "skip must not move the file"
    assert list(draft["vetted"].glob("gen-*.md")) == [], "skip must not promote"

    frontmatter, _ = read_page(draft["path"])
    assert frontmatter["status"] == "pending", "still unjudged"
    assert frontmatter["labeled_by"] == "", "skip is not a verdict, so it signs nothing"
    assert frontmatter["deferred_after_session"] == session_id
    assert "not sure about the BP" in frontmatter["deferred_note"]


def test_skip_does_not_teach_the_generator_anything(client, user, draft):
    """Only a rejection writes a lesson. Hesitation is not a critique."""
    from ems.sim import review as review_lib

    _certify(client, user)
    before = review_lib.load_lessons_text()
    session_id = _played_generated(client, user, draft)
    client.post(f"/api/session/{session_id}/review",
                json={"decision": "skip", "comment": "come back to this"})
    assert review_lib.load_lessons_text() == before


def test_an_apprentice_may_skip(client, user, draft):
    """Skip settles nothing, so it is not gated the way approving is."""
    session_id = _played_generated(client, user, draft)
    response = client.post(f"/api/session/{session_id}/review", json={"decision": "skip"})
    assert response.status_code == 200


def test_skip_needs_no_comment(client, user, draft):
    _certify(client, user)
    session_id = _played_generated(client, user, draft)
    assert client.post(f"/api/session/{session_id}/review",
                       json={"decision": "skip"}).status_code == 200


def test_a_deferred_draft_sorts_behind_one_nobody_has_seen(tmp_path):
    """The point of skipping: it comes back last, not next."""
    from ems.frontmatter import read_page, write_frontmatter
    from ems.sim import review as review_lib
    from ems.sim.generate import list_generated
    import tests.test_sim_generate as gen_tests
    from ems.sim import generate as gen

    quarantine = tmp_path / "generated"
    first = gen.save_draft(
        gen.draft(["asthma"], llm=gen_tests.stub(gen_tests.GOOD),
                  context=gen_tests.CONTEXT, lessons=""),
        dest=quarantine,
    )
    second = quarantine / "gen-29991231-99.md"
    second.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")
    frontmatter, _ = read_page(second)
    frontmatter["scenario_id"] = second.stem
    write_frontmatter(second, frontmatter)

    assert list_generated(dest=quarantine) == [first, second]
    review_lib.defer(first, session_id="s1")
    assert list_generated(dest=quarantine) == [second, first]


def test_an_exported_call_says_whether_claude_voiced_it(client, user):
    """The question that sent a reviewer to read the source to answer it."""
    off = start(client, user)["session_id"]
    text = client.get(f"/api/session/{off}/transcript").text
    assert "deterministic" in text and "Claude voices" not in text

    on = client.post(
        "/api/session/start", json={"scenario_id": "src1-s01"}
    ).json()["session_id"]
    assert "Claude voices" in client.get(f"/api/session/{on}/transcript").text
