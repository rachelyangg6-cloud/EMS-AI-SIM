"""FastAPI layer over the simulator — the API the React UI will drive.

One request per EMT turn. The client sends what the EMT said; the server runs the
state machine forward until it is the EMT's turn again (or the call is over) and
returns every event produced along the way. That keeps all phase logic on the
server and leaves the UI to render a list.

**In-flight sessions live in memory** (`app.state.live`), keyed by session id.
Turns and debriefs are written to SQLite as they happen, so completed practice is
durable, but a server restart abandons calls that are mid-flight. For a
single-instance deployment that is the right trade: rehydrating a state machine
on every request buys nothing a trainee would notice.

The LLM layer is per session (`personas`, `narrative_debrief`), on by default.
Both remain parameters so a call can be run deterministically — no API key, no
cost, the same words every time — and every LLM failure already falls back to
that same deterministic text, so an outage degrades the call rather than ending it.

**Everything except `/api/health` and `/api/login` needs a bearer token.**
Accounts are issued by `protocol-users` and there is no sign-up route, so the
server can believe a profile's `training_status` — which is what makes the
certified-reviewer gate on generated drafts a boundary rather than a hint. A
route never takes a user id from the request body: the caller is whoever holds
the token, and a session belongs to the user who started it.
"""

import random
from dataclasses import asdict, replace
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field, model_validator

from ems.corpus_stats import cached_stats
from ems.frontmatter import read_page
from ems.paths import scenarios_dir
from ems.scenarios import list_approved
from ems.sim.playable import playable_cases, unplayable
from ems.sim import persona, select, store, topic
from ems.sim.generate import generated_dir, list_generated
from ems.sim import review as review_lib
from ems.sim.debrief import grade_llm
from ems.sim.difficulty import DIFFICULTY_LEVELS
from ems.sim.hints import hint_for_session
from ems.sim import patterns, transcript
from ems.sim.patterns import Conditions, fetch_live
from ems.sim.scene import Environment, derive_scene
from ems.sim.session import Session

#: "vetted" deals from the approved, playable corpus. "generated" deals an
#: unreviewed draft out of quarantine so it can be played *before* it is
#: reviewed — which is the order the review loop needs, and the one thing
#: quarantine has to allow. A generated draft is never in the vetted pool; asking
#: for this mode is the reviewer choosing to play one.
MODES = ("vetted", "generated")


# ── request bodies ───────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    username: str
    password: str


class ProfileIn(BaseModel):
    """An edit to the signed-in user's own profile.

    Three things a person cannot change about themselves, and each is absent
    here on purpose:

    * **corp_slug** — which department they belong to. Moving between corps is
      an administrative act, not a form field.
    * **username** — the stable handle their practice history hangs off.
    * **training_status** — whether they may promote a generated draft into the
      vetted corpus. Set by `protocol-users promote`. A client that could send
      this would make the certification check read the caller's own claim,
      which is the hole this whole feature closes.
    """
    name: str = ""
    email: str = ""
    #: Empty means "leave whatever is stored alone" — see store.upsert_user.
    #: The form does not resend every field, and a default here would overwrite
    #: what is already there.
    scope_level: Literal["", "EMT-B", "AEMT", "Paramedic"] = ""
    years_experience: Optional[int] = None


class StartIn(BaseModel):
    #: No user_id: the call belongs to whoever holds the token. A field here
    #: would let any signed-in EMT practice into somebody else's history.
    scenario_id: Optional[str] = None
    level: str = "intermediate"
    mode: str = "vetted"
    environment: dict = Field(default_factory=dict)
    seed: Optional[int] = None
    #: Instructor override — force a smoke day, a heatwave, a flu peak.
    #: Absent, season comes from the date and nothing touches the network.
    conditions: dict = Field(default_factory=dict)
    #: The LLM layer: Claude voices the dispatcher, scene and patient, and
    #: writes the narrative around the debrief. On by default — a call reads as
    #: a conversation rather than a recitation, and that is the product.
    #:
    #: Both stay real parameters rather than becoming hardcoded truths, because
    #: turning the model off is how you get a run that is reproducible, free,
    #: and diagnosable. Every failure path degrades to the deterministic text
    #: (`persona.safe_speak`, `_finish`), so no API key still plays a full call.
    personas: bool = True
    narrative_debrief: bool = True


class ReviewIn(BaseModel):
    """A certified EMT's verdict on a generated draft, taken after the call.

    Deliberately no `user_id`: the reviewer is whoever owned the session, read
    from the database. A field here would be a spoofable claim, and it would
    make the certification check examine the caller's own input.
    """
    decision: Literal["approve", "reject", "skip"]
    comment: str = ""
    realism_rating: Optional[int] = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def _a_rejection_needs_a_critique(self) -> "ReviewIn":
        # 422 here rather than letting review.reject's ValueError become a 500.
        # The critique is the only thing a rejection produces.
        if self.decision == "reject" and not self.comment.strip():
            raise ValueError("a rejection needs a comment saying what is wrong")
        return self


class TurnIn(BaseModel):
    utterance: str


class SpeakIn(BaseModel):
    """The /api/tts contract, fixed now so ServerVoice can be written against it."""
    text: str
    persona: str = "narrator"
    rate: float = 1.0
    pitch: float = 1.0


# ── helpers ──────────────────────────────────────────────────────────────────

def _event(event) -> dict:
    return {
        "phase": event.phase,
        "speaker": event.speaker,
        "text": event.text,
        "awaiting_input": event.awaiting_input,
    }


def _environment(data: dict, conditions: Conditions, seed: Optional[int]) -> Environment:
    """What the call looks like: derived from today, overridden by what's asked.

    An explicit field from the client wins — that is the instructor forcing a
    night call. Everything they leave out comes from the conditions, which is
    why a smoke day now renders as one without anybody selecting it.
    """
    fields = Environment.__dataclass_fields__
    supplied = {k: v for k, v in data.items() if k in fields}
    derived = patterns.environment_for(conditions, rng=random.Random(seed))
    # Asking for a night call at 20:00 must not leave the clock saying dusk:
    # the renderer trusts `hour` over the bucket, so a contradicted hour would
    # quietly win. Whoever names the time owns it.
    if "time_of_day" in supplied and "hour" not in supplied:
        supplied["hour"] = None
    return replace(derived, **supplied)


def _conditions(data: dict) -> Conditions:
    """Instructor override if given, else today's season (offline)."""
    fields = Conditions.__dataclass_fields__
    supplied = {k: v for k, v in data.items() if k in fields}
    if supplied:
        base = Conditions.for_date()
        return Conditions(**{**{"season": base.season}, **supplied})
    return fetch_live()   # no-ops to the date unless EMS_LIVE_ENV=1


def _pick_scenario(
    scenario_id: Optional[str],
    level: str,
    seed: Optional[int],
    conditions: Optional[Conditions] = None,
    recent: tuple[str, ...] = (),
    mode: str = "vetted",
) -> Path:
    if mode == "generated":
        if scenario_id:
            path = generated_dir() / f"{scenario_id}.md"
            if not path.exists():
                raise HTTPException(404, f"No generated draft {scenario_id!r}")
            return path
        pool = list_generated()
        if not pool:
            raise HTTPException(404, "No generated drafts are awaiting review")
        return random.Random(seed).choice(pool)

    if scenario_id:
        path = scenarios_dir() / f"{scenario_id}.md"
        if path in set(list_approved()):
            # Asked for by name, so say why rather than silently dealing it: a
            # scenario with no patient plays as a broken call, not a hard one.
            why = unplayable(*read_page(path))
            if why:
                raise HTTPException(
                    422, f"{scenario_id} cannot be played as a call: {'; '.join(why)}"
                )
            return path

        # Not an id, so it is a topic — "hypoxia", "chest pain". Only playable
        # cases are searched, so a topic can never deal the broken call that the
        # 422 above exists to refuse.
        pool = playable_cases()
        matches = topic.match(scenario_id, pool)
        if not matches:
            near = topic.suggest(scenario_id, pool)
            hint = f" Did you mean: {', '.join(near)}?" if near else ""
            raise HTTPException(
                404, f"No scenario or topic matching {scenario_id!r}.{hint}"
            )
        # Difficulty narrows a topic rather than overriding it: asking for an
        # expert hypoxia call and getting a basic one ignores half of what was
        # asked, but so does refusing when the topic exists at no other level.
        at_level = [p for p in matches if read_page(p)[0].get("difficulty") == level]
        pool = at_level or matches
        rng = random.Random(seed)
        return select.select(pool, conditions, recent=recent, rng=rng) or rng.choice(pool)

    if level not in DIFFICULTY_LEVELS:
        raise HTTPException(400, f"level must be one of {list(DIFFICULTY_LEVELS)}")
    pool = playable_cases(difficulty=level)
    if not pool:
        raise HTTPException(404, f"No playable scenarios at difficulty {level!r}")
    chosen = select.select(pool, conditions, recent=recent, rng=random.Random(seed))
    return chosen or random.Random(seed).choice(pool)


def _drive(session: Session, utterance: Optional[str] = None) -> list[dict]:
    """Run the machine forward until the EMT is needed again, or the call ends.

    Silent phases are dropped: a phase with nothing to say still advances the
    machine, but sending it would render as an empty line in the transcript.
    """
    events = [_event(session.step(utterance))] if utterance is not None else []
    while not session.done and not session.awaiting_input:
        events.append(_event(session.step()))
    return [e for e in events if e["text"] or e["awaiting_input"]]


def _drive_to_end(session: Session) -> list[dict]:
    """Close the call out from wherever it is, as if the EMT kept saying so.

    One "end of call" is not always enough: said at `SIZE_UP` it is recorded as
    the size-up (a blank one, scored as such) and the machine moves on, so the
    next interactive phase has to hear it too.
    """
    events: list[dict] = []
    for _ in range(len(("SIZE_UP", "TURN")) + 1):
        if session.done:
            break
        events += _drive(session, "end of call" if session.awaiting_input else None)
    return events


def _public_scene(spec) -> dict:
    """The scene minus the numbers the EMT has not earned.

    `rr` stays: a fast-breathing patient is visibly fast-breathing, and it drives
    the chest-rise animation. `hr` and `spo2` are monitor readings — they arrive
    through `known_vitals` once the EMT actually measures them.
    """
    scene = spec.to_dict()
    if scene["patient"]:
        scene["patient"]["hr"] = None
        scene["patient"]["spo2"] = None
    return scene


def _state(session: Session, events: list[dict]) -> dict:
    emt = session.emt_turns()
    return {
        "phase": session.phase,
        "awaiting_input": session.awaiting_input,
        "done": session.done,
        "events": events,
        # What the monitor may display, and what the last utterance was read as.
        "vitals": session.known_vitals(),
        # Which of those the simulator invented, so the UI can tag them. Sent
        # for every displayed vital, not just the ones asked about.
        "vitals_generated": sorted(session.generated_vitals & set(session.known_vitals())),
        "intents": list(emt[-1].intents) if emt else [],
        # A category-level nudge, never the rubric's own words. Present only
        # when it is the EMT's move; the client decides whether to show it.
        "hint": hint_for_session(session) if session.awaiting_input else None,
    }


# ── the app ──────────────────────────────────────────────────────────────────

def create_app(db: Optional[Path] = None) -> FastAPI:
    app = FastAPI(title="EMT Ride-Along Simulator", version="0.1.0")
    app.state.db = store.connect(db)
    app.state.live: dict[str, Session] = {}
    #: session_id → whether to write an LLM narrative at the end.
    app.state.narrative: dict[str, bool] = {}

    def live(session_id: str) -> Session:
        session = app.state.live.get(session_id)
        if session is None:
            if store.get_session(app.state.db, session_id):
                raise HTTPException(409, "That session is no longer in progress")
            raise HTTPException(404, f"No session {session_id!r}")
        return session

    def current_user(authorization: str = Header(default="")) -> dict:
        """The signed-in EMT, from `Authorization: Bearer <token>`.

        401 rather than 403 for a bad token: the client turns a 401 into "your
        session ended, sign in again", which is the true thing to say about an
        expired token and the least useful thing to say to a stranger.
        """
        scheme, _, token = authorization.partition(" ")
        user = (
            store.user_for_token(app.state.db, token.strip())
            if scheme.lower() == "bearer" else None
        )
        if user is None:
            raise HTTPException(401, "Sign in to continue")
        return user

    def owned_session(session_id: str, user: dict) -> dict:
        """One of this user's own calls, or 404.

        404 and not 403 on somebody else's session: a 403 would confirm the id
        exists, which turns the endpoint into a way to count other people's
        practice.
        """
        session = store.get_session(app.state.db, session_id)
        if session is None or session["user_id"] != user["id"]:
            raise HTTPException(404, f"No session {session_id!r}")
        return session

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/corpus")
    def corpus() -> dict:
        """Counts describing the library, for the Features page.

        **Unauthenticated, deliberately** — the second and last route that is,
        alongside `/api/health`. What it returns is the *shape* of the corpus:
        how many pages and vetted calls exist, how they are distributed across
        topics and sources, and which model does which job. It carries no user,
        session or turn data, and no page or scenario text, so nothing here
        could reconstruct a call. It is the same information anyone reading the
        repository already has, and it is public so the page can be linked from
        the landing page later without a second code path.

        If a field derived from `ems.db` is ever added here, this route stops
        being safe to leave open. Add it behind `current_user` instead.

        Memoized for the process lifetime, so this is O(1) after the first
        request — a smaller load lever than the uncached ~325-file re-parse
        `_pick_scenario` already does on every authenticated session start.
        """
        return cached_stats()

    # ── signing in ───────────────────────────────────────────────────────────
    # There is deliberately no sign-up and no password-change route. Accounts
    # come from `protocol-users`, which is what lets the server trust the
    # `training_status` on a profile it hands out.

    @app.post("/api/login")
    def login(body: LoginIn) -> dict:
        user = store.authenticate(app.state.db, body.username.strip(), body.password)
        if user is None:
            # One message for both halves. Saying "no such user" would let
            # anyone enumerate who has an account.
            raise HTTPException(401, "That username and password do not match")
        return {
            "token": store.issue_token(app.state.db, user["id"]),
            "user": store.public_user(user),
        }

    @app.post("/api/logout")
    def logout(authorization: str = Header(default="")) -> dict:
        """Revoke this token. Unauthenticated on purpose — logging out with a
        token the server has already forgotten is a success, not an error."""
        _, _, token = authorization.partition(" ")
        store.revoke_token(app.state.db, token.strip())
        return {"status": "ok"}

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)) -> dict:
        """Rehydrate a stored token into a profile, so a refresh stays signed in."""
        return store.public_user(user)

    # ── voice: contract fixed, implementation deferred ───────────────────────
    # Project 7 ships browser speech (`BrowserVoice`), which needs no server.
    # These two exist so `ServerVoice` — local Whisper for STT, Piper for TTS —
    # is a one-line swap in the client rather than an API negotiation later.
    # 501 is the honest status: the route is real, the capability is not here yet.

    @app.post("/api/stt", status_code=501)
    async def speech_to_text(audio: UploadFile) -> dict:
        """Audio in, `{"text": ...}` out. Not implemented — use BrowserVoice."""
        raise HTTPException(
            501,
            "Server-side speech-to-text is not wired up. The client uses the "
            "browser's Web Speech API; point ServerVoice here once Whisper is "
            "running. Expected: multipart 'audio' file in, {'text': str} out.",
        )

    @app.post("/api/tts", status_code=501)
    def text_to_speech(body: SpeakIn) -> dict:
        """Text in, audio/wav out. Not implemented — use BrowserVoice."""
        raise HTTPException(
            501,
            "Server-side text-to-speech is not wired up. The client uses the "
            "browser's Web Speech API; point ServerVoice here once Piper is "
            "running. Expected: {text, persona, rate, pitch} in, audio/wav out.",
        )

    @app.post("/api/profile")
    def edit_profile(body: ProfileIn, user: dict = Depends(current_user)) -> dict:
        """Edit your own profile. Not a sign-in and not a way to create one.

        Renaming is allowed — `upsert_user` is keyed on (corp_slug, name), so a
        new name would make a second profile rather than rename this one, and
        the UPDATE below is what keeps the practice history attached.
        """
        name = body.name.strip() or user["name"]
        app.state.db.execute(
            """UPDATE users SET
                   name             = ?,
                   email            = COALESCE(?, email),
                   scope_level      = COALESCE(?, scope_level),
                   years_experience = COALESCE(?, years_experience)
               WHERE id = ?""",
            (name, body.email or None, body.scope_level or None,
             body.years_experience, user["id"]),
        )
        app.state.db.commit()
        return store.public_user(store.get_user(app.state.db, user["id"]))

    @app.get("/api/profile")
    def read_profile(user: dict = Depends(current_user)) -> dict:
        """Your own profile. There is no route that reads somebody else's."""
        return store.public_user(user)

    @app.post("/api/session/start")
    def start(body: StartIn, user: dict = Depends(current_user)) -> dict:
        """Open a call: returns the tone-out through the size-up prompt, plus the scene."""
        if body.mode not in MODES:
            raise HTTPException(400, f"mode must be one of {list(MODES)}")

        conditions = _conditions(body.conditions)
        recent = tuple(
            s["scenario_id"]
            for s in store.list_sessions(app.state.db, user["id"], limit=8)
        )
        path = _pick_scenario(body.scenario_id, body.level, body.seed, conditions,
                              recent, mode=body.mode)
        health = persona.LlmHealth() if body.personas else None
        session = Session.from_path(
            path, persona=persona.tracked_speak(health) if health else None
        )
        session.llm_health = health
        environment = _environment(body.environment, conditions, body.seed)

        session_id = store.start_session(
            app.state.db,
            user_id=user["id"],
            scenario_id=session.scenario_id,
            mode=body.mode,
            difficulty=session.difficulty,
            environment=asdict(environment),
            personas=body.personas,
        )
        app.state.live[session_id] = session
        app.state.narrative[session_id] = body.narrative_debrief

        events = _drive(session)
        store.record_turns(app.state.db, session_id, session.turns)
        return {
            "session_id": session_id,
            # The UI needs this, with the user's training status, to decide
            # whether to offer a review panel on the debrief.
            "mode": body.mode,
            "scenario_id": session.scenario_id,
            "difficulty": session.difficulty,
            "conditions": asdict(conditions),
            "scene": _public_scene(
                derive_scene(session.frontmatter, session.body, environment)
            ),
            **_state(session, events),
        }

    @app.post("/api/session/{session_id}/turn")
    def turn(session_id: str, body: TurnIn, user: dict = Depends(current_user)) -> dict:
        """Submit what the EMT said and get back everything the sim says in reply."""
        owned_session(session_id, user)
        session = live(session_id)
        if not session.awaiting_input:
            raise HTTPException(409, f"{session.phase} is not waiting for the EMT")

        events = _drive(session, body.utterance)
        store.record_turns(app.state.db, session_id, session.turns)

        payload = _state(session, events)
        if session.done:
            payload["grade"] = _finish(session_id, session)
        return payload

    @app.post("/api/session/{session_id}/end")
    def end(session_id: str, user: dict = Depends(current_user)) -> dict:
        """End the call early — the same as saying "end of call"."""
        owned_session(session_id, user)
        session = live(session_id)
        events = _drive_to_end(session)
        store.record_turns(app.state.db, session_id, session.turns)
        if not session.done:
            raise HTTPException(500, f"Session would not close out; stuck at {session.phase}")
        return {**_state(session, events), "grade": _finish(session_id, session)}

    @app.post("/api/session/{session_id}/review")
    def review_scenario(
        session_id: str, body: ReviewIn, reviewer: dict = Depends(current_user)
    ) -> dict:
        """A certified EMT's verdict on the generated draft they just played.

        Approve promotes it into the vetted corpus; reject keeps it in
        quarantine and turns the comment into a line in
        `system/generation-lessons.md`, which is read by every later draft.

        **On the certification check.** `training_status` is set by
        `protocol-users promote` and never by anything a client can send, and
        the reviewer here is the holder of the token rather than a name in the
        body — so this is a boundary the server can stand behind, not the
        guardrail it used to be when any caller could call themselves certified.
        Promotion stays attributable and reversible on top of that: `labeled_by`
        records who claimed it, `reviewed_after_session` records the call it
        came out of, and the promotion itself is a file move visible in git.
        """
        # From SQLite, never `app.state.live`: `_finish` pops the live session
        # the moment a call ends, so by review time that lookup is always a miss.
        session = owned_session(session_id, reviewer)
        if session["ended_at"] is None:
            raise HTTPException(409, "Finish the call before reviewing it")
        if session["mode"] != "generated":
            raise HTTPException(409, "Only a generated draft can be reviewed")

        # Skip settles nothing and writes nothing to the corpus, so it is not
        # gated: an apprentice browsing drafts should still be able to move on.
        if body.decision != "skip" and not store.may_review(reviewer):
            raise HTTPException(
                403,
                "Approving a case into the shared library is for certified EMTs. "
                "You can still practice it.",
            )

        scenario_id = session["scenario_id"]
        path = review_lib.find_generated(scenario_id)
        if path is None:
            # Already promoted, or gone. Without this a double-click reads a
            # file that has moved and 500s.
            raise HTTPException(409, f"{scenario_id} is no longer awaiting review")

        if body.decision == "approve":
            review_lib.approve(
                path,
                labeled_by=reviewer["name"],
                realism_rating=body.realism_rating,
                realism_note=body.comment,
                dest=scenarios_dir(),
                session_id=session_id,
            )
            return {
                "decision": "approve", "scenario_id": scenario_id,
                "status": "approved", "location": "vetted", "lesson_recorded": False,
            }

        if body.decision == "skip":
            review_lib.defer(path, session_id=session_id, note=body.comment)
            remaining = [
                other for other in list_generated()
                if other.stem != scenario_id
            ]
            return {
                "decision": "skip", "scenario_id": scenario_id,
                "status": "pending", "location": "generated",
                "lesson_recorded": False,
                # What the UI needs to say something true about what happens
                # next, rather than implying another draft is waiting.
                "drafts_remaining": len(remaining),
            }

        review_lib.reject(
            path,
            labeled_by=reviewer["name"],
            critique=body.comment,
            realism_rating=body.realism_rating,
        )
        return {
            "decision": "reject", "scenario_id": scenario_id,
            "status": "rejected", "location": "generated", "lesson_recorded": True,
        }

    def _finish(session_id: str, session: Session) -> dict:
        grade = session.grade()
        store.finish_session(
            app.state.db, session_id, grade,
            llm=session.llm_health.to_dict() if session.llm_health else None,
        )
        payload = grade.to_dict()

        if app.state.narrative.pop(session_id, False):
            # The deterministic grade is already stored above. If the narrative
            # call fails — no credentials, a rate limit — the trainee still gets
            # their score; they just don't get the prose.
            try:
                payload["narrative"] = grade_llm(
                    grade, session.frontmatter, session.body
                ).to_dict()
                # Onto the stored grade as well, or the downloaded transcript
                # never sees it: the export reads SQLite, not this response.
                store.attach_narrative(
                    app.state.db, session_id, payload["narrative"]
                )
            except Exception as error:
                payload["narrative_error"] = str(error)

        app.state.live.pop(session_id, None)
        return payload

    @app.get("/api/history")
    def history(limit: int = 50, user: dict = Depends(current_user)) -> dict:
        """Your own past calls. There is no way to ask for anyone else's."""
        return {"sessions": store.list_sessions(app.state.db, user["id"], limit)}

    @app.get("/api/history/{session_id}")
    def session_detail(session_id: str, user: dict = Depends(current_user)) -> dict:
        session = owned_session(session_id, user)
        return {**session, "turns": store.get_turns(app.state.db, session_id)}

    @app.get("/api/session/{session_id}/transcript")
    def session_transcript(
        session_id: str, user: dict = Depends(current_user)
    ) -> Response:
        """The call as markdown, for marking up which lines earned their place.

        Works mid-call as well as after: turns are written on every request, so
        whatever has been said so far is already in the database.
        """
        owned_session(session_id, user)
        session, turns = transcript.load(app.state.db, session_id)
        return Response(
            content=transcript.render(session, turns),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{transcript.filename(session)}"'
            },
        )

    return app
