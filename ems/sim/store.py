"""SQLite persistence for practice sessions — profiles, turns, and debriefs.

Deliberately plain `sqlite3`: the repo has no ORM and this schema is five tables
that Project 11 will back up by copying one file.

Nothing clinical lives here. The wiki and the scenario corpus remain the only
source of truth; this database records only *who practiced what, and how it
went*. Department SOG documents get their own table in Project 10.
"""

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from ems.paths import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    corp_slug    TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    region       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    corp_slug        TEXT NOT NULL REFERENCES departments(corp_slug),
    name             TEXT NOT NULL,
    scope_level      TEXT NOT NULL DEFAULT 'EMT-B',
    training_status  TEXT NOT NULL DEFAULT 'apprentice',
    years_experience INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    -- Issued by ems/cli/users.py, never by the web client. The username is the
    -- stable handle a person logs in with and does not change; everything else
    -- on the profile can be edited.
    username         TEXT,
    email            TEXT NOT NULL DEFAULT '',
    password_hash    TEXT,
    password_salt    TEXT,
    UNIQUE (corp_slug, name)
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id               TEXT PRIMARY KEY,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    scenario_id      TEXT NOT NULL,
    mode             TEXT NOT NULL,
    difficulty       TEXT NOT NULL DEFAULT '',
    environment_json TEXT NOT NULL DEFAULT '{}',
    started_at       TEXT NOT NULL,
    ended_at         TEXT,
    score            INTEGER,
    grade_json       TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES sessions(id),
    seq          INTEGER NOT NULL,
    phase        TEXT NOT NULL,
    speaker      TEXT NOT NULL,
    utterance    TEXT NOT NULL,
    intents_json TEXT NOT NULL DEFAULT '[]',
    -- Written from Project 6 onward; this build has no physiology model, so a
    -- turn cannot change the vitals and the column stays NULL.
    vitals_json  TEXT,
    at           TEXT NOT NULL,
    UNIQUE (session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, seq);
"""

#: Where an EMT is in their training, as opposed to `scope_level`, which is what
#: they may do to a patient. This one decides whether the platform takes their
#: word for a scenario — see `may_review`.
TRAINING_STATUSES = ("apprentice", "certified")

#: Columns added after a database may already exist in the wild.
#:
#: `connect` only ever runs CREATE TABLE IF NOT EXISTS, so adding a column to
#: SCHEMA does nothing to a database that has already been created — the next
#: INSERT then fails with "table users has no column named ...". Every entry here
#: is applied to an existing file as well, and SCHEMA carries the same column so
#: a fresh database and a migrated one end up identical. A test pins that.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("users", "training_status", "TEXT NOT NULL DEFAULT 'apprentice'"),
    # Login. Nullable on purpose: a profile created before credentials existed
    # keeps working for everything except signing in, and `ems.cli.users add`
    # is what gives it a username.
    ("users", "username", "TEXT"),
    ("users", "email", "TEXT NOT NULL DEFAULT ''"),
    ("users", "password_hash", "TEXT"),
    ("users", "password_salt", "TEXT"),
    # Whether Claude voiced this call. Recorded because a call that fell back to
    # the deterministic text — no key, a rate limit — is nearly indistinguishable
    # from one that never asked for a persona, and the difference is the first
    # thing anyone reviewing a transcript needs to know. Older rows default to 0,
    # which is what they were: the LLM was opt-in and off.
    ("sessions", "personas", "INTEGER NOT NULL DEFAULT 0"),
    # The score stopped being a percentage. `score` now holds raw points earned
    # on this scenario and `points_possible` says out of what; `passed` is the
    # verdict, which a critical error decides on its own.
    #
    # Both are NULL on rows written before the change, and that is the point: a
    # legacy 71 was a percentage and a new 19 is nineteen points out of
    # twenty-seven. `points_possible IS NULL` is how the two are told apart, so
    # old calls are never redrawn on a scale they were not measured with.
    # What Claude actually did on this call: attempted, answered, failed, and
    # the first error. `personas` records only that voices were *asked* for, and
    # every LLM failure falls back to exactly the deterministic text, so without
    # this a revoked key is indistinguishable from a model that answered dully.
    ("sessions", "llm_json", "TEXT"),
    ("sessions", "points_possible", "INTEGER"),
    ("sessions", "passed", "INTEGER"),
)


#: Indexes over columns that `_migrate` may have only just added.
#:
#: These cannot live in SCHEMA. SCHEMA runs first, against a database that may
#: predate the column, and CREATE INDEX on a column that is not there yet fails
#: the whole script. So they run after the migration instead.
_POST_MIGRATION_INDEXES = """
-- A separate index rather than UNIQUE on the column: SQLite cannot ALTER TABLE
-- ADD COLUMN with a UNIQUE constraint, and this has to reach databases that
-- already exist. NULLs stay distinct, so profiles created before login existed
-- are left alone rather than colliding with each other.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Add any column an older database is missing. Safe to run every time.

    SQLite has no ADD COLUMN IF NOT EXISTS, so the name check is the guard.
    Catching OperationalError on "duplicate column name" would work too, and
    would also swallow the errors worth seeing.

    Existing rows are backfilled by SQLite from the DEFAULT in the DDL — which
    is also why NOT NULL is allowed here at all.
    """
    for table, column, ddl in _ADDED_COLUMNS:
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def may_review(user: dict) -> bool:
    """Whether this EMT may promote a generated draft into the vetted corpus.

    `training_status` is set by `ems.cli.users`, never by the web client, and
    the endpoints resolve the user from a login token rather than from a name
    in the request body. So this is now a claim the server can actually stand
    behind, which it could not when any caller could name themselves certified.
    """
    return user.get("training_status") == "certified"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open (and if needed create) the practice database."""
    target = Path(path) if path else db_path()
    if target != Path(":memory:"):
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.executescript(_POST_MIGRATION_INDEXES)
    conn.commit()
    return conn


# ── profiles ─────────────────────────────────────────────────────────────────

def upsert_department(
    conn: sqlite3.Connection, corp_slug: str, display_name: str = "", region: str = ""
) -> None:
    """Departments are shared: a second member of a corp does not re-create it."""
    conn.execute(
        """INSERT INTO departments (corp_slug, display_name, region, created_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(corp_slug) DO UPDATE SET
               display_name = CASE WHEN excluded.display_name != ''
                                   THEN excluded.display_name ELSE display_name END,
               region       = CASE WHEN excluded.region != ''
                                   THEN excluded.region ELSE region END""",
        (corp_slug, display_name, region, _now()),
    )
    conn.commit()


def upsert_user(
    conn: sqlite3.Connection,
    corp_slug: str,
    name: str,
    scope_level: str = "",
    years_experience: int = 0,
    display_name: str = "",
    region: str = "",
    training_status: str = "",
    email: str = "",
) -> dict:
    """Create or update one EMT's profile, keyed by (corp_slug, name).

    An omitted field leaves the stored value alone, the same way
    `upsert_department` treats display_name and region.

    This used to overwrite `scope_level` unconditionally, and the web client
    does not send it (frontend/src/api.ts), so every browser sign-in quietly
    reset a Paramedic to EMT-B. `training_status` would have inherited the same
    bug in a worse form: a certified EMT demoted to apprentice each time they
    signed in, losing the right to promote a scenario without ever being told.
    """
    upsert_department(conn, corp_slug, display_name, region)
    # Named parameters, because each of these has to be read twice — once to
    # decide the value for a new row and once to decide whether to touch an
    # existing one. `excluded` cannot do that job: it holds the row *after* the
    # INSERT expressions have run, so a default applied there would look
    # identical to a value the caller actually supplied.
    conn.execute(
        """INSERT INTO users (corp_slug, name, scope_level, training_status,
                              years_experience, email, created_at)
           VALUES (:corp_slug, :name,
                   COALESCE(:scope_level, 'EMT-B'),
                   COALESCE(:training_status, 'apprentice'),
                   :years_experience, COALESCE(:email, ''), :created_at)
           ON CONFLICT(corp_slug, name) DO UPDATE SET
               scope_level      = COALESCE(:scope_level, scope_level),
               training_status  = COALESCE(:training_status, training_status),
               years_experience = :years_experience,
               email            = COALESCE(:email, email)""",
        {
            "corp_slug": corp_slug,
            "name": name,
            # NULL means "not supplied"; '' from a form field means the same.
            "scope_level": scope_level or None,
            "training_status": training_status or None,
            "email": email or None,
            "years_experience": years_experience,
            "created_at": _now(),
        },
    )
    conn.commit()
    return find_user(conn, corp_slug, name)


def find_user(conn: sqlite3.Connection, corp_slug: str, name: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM users WHERE corp_slug = ? AND name = ?", (corp_slug, name)
    ).fetchone()
    return dict(row) if row else None


def list_users(conn: sqlite3.Connection, corp_slug: str = "") -> list[dict]:
    """Every profile, or every profile in one department, oldest first."""
    if corp_slug:
        rows = conn.execute(
            "SELECT * FROM users WHERE corp_slug = ? ORDER BY id", (corp_slug,)
        )
    else:
        rows = conn.execute("SELECT * FROM users ORDER BY corp_slug, id")
    return [dict(row) for row in rows]


def get_user(conn: sqlite3.Connection, user_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


# ── credentials ──────────────────────────────────────────────────────────────
#
# Issued by `ems.cli.users` and checked here. Deliberately stdlib-only: the
# frontend carries no dependencies beyond React and the backend should not
# acquire a password library to hash four fields.

#: scrypt parameters. n=2**14 keeps a login around a tenth of a second on a
#: laptop, which is slow enough to matter to someone guessing and fast enough
#: not to be felt by someone signing in.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}

#: Words for generated passwords. Short, unambiguous, and free of the letter
#: pairs people mistype when reading a password off a screen.
_WORDS = (
    "amber anchor autumn beacon bramble cedar cinder cobalt copper cove crimson"
    " delta ember fathom flint garnet gully harbor hazel indigo ivory juniper"
    " kestrel lantern marble meadow mesa nickel oak onyx opal pebble pine quarry"
    " quill ridge rowan saffron slate spruce summit thistle timber umber vale"
    " walnut willow yarrow zephyr"
).split()

#: How long a login lasts. Long enough to practice a shift, short enough that a
#: token left in a shared browser expires on its own.
TOKEN_TTL_HOURS = 12


def generate_password() -> str:
    """A readable one-time password: three words and four digits."""
    words = "-".join(secrets.choice(_WORDS) for _ in range(3))
    return f"{words}-{secrets.randbelow(9000) + 1000}"


def generate_username(name: str, corp_slug: str) -> str:
    """First initial, surname, department initials — e.g. Jane Roe → jroe-wvac.

    Collisions are possible and are the caller's problem: the unique index on
    users.username rejects a duplicate rather than quietly making a second
    account for a different person with the same name.
    """
    parts = [p for p in re.split(r"[^A-Za-z]+", name) if p]
    stem = (parts[0][0] + parts[-1]).lower() if len(parts) > 1 else (parts[0].lower() if parts else "emt")
    # The last word of the slug stays whole — it is usually the corps type
    # ("vac", "fd", "ems") and initializing it away leaves nothing readable.
    words = [w for w in corp_slug.split("-") if w]
    suffix = ("".join(w[0] for w in words[:-1]) + words[-1]).lower() if words else ""
    return f"{stem}-{suffix}" if suffix else stem


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Return (hash, salt), both hex. A fresh salt is generated if none is given."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    if not password_hash or not salt:
        return False
    candidate, _ = hash_password(password, salt)
    # Constant time: a short-circuiting comparison leaks how much of the hash
    # matched, which is enough to reconstruct it one byte at a time.
    return hmac.compare_digest(candidate, password_hash)


def set_password(conn: sqlite3.Connection, user_id: int, password: str) -> None:
    """Store a new password and revoke every existing login for that user."""
    digest, salt = hash_password(password)
    conn.execute(
        "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
        (digest, salt, user_id),
    )
    conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
    conn.commit()


def set_username(conn: sqlite3.Connection, user_id: int, username: str) -> None:
    conn.execute("UPDATE users SET username = ? WHERE id = ?", (username, user_id))
    conn.commit()


def find_by_username(conn: sqlite3.Connection, username: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> Optional[dict]:
    """The user, or None. Never says which half was wrong."""
    user = find_by_username(conn, username)
    if not user:
        # Hash anyway, so a missing username and a wrong password take the same
        # time. Otherwise the response time enumerates who has an account.
        hash_password(password)
        return None
    if not verify_password(password, user.get("password_hash") or "", user.get("password_salt") or ""):
        return None
    return user


def issue_token(conn: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO auth_tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (
            token,
            user_id,
            now.isoformat(timespec="seconds"),
            (now + timedelta(hours=TOKEN_TTL_HOURS)).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return token


def user_for_token(conn: sqlite3.Connection, token: str) -> Optional[dict]:
    """The user this token belongs to, or None if it is unknown or expired."""
    if not token:
        return None
    row = conn.execute(
        """SELECT u.* FROM auth_tokens t
           JOIN users u ON u.id = t.user_id
           WHERE t.token = ? AND t.expires_at > ?""",
        (token, _now()),
    ).fetchone()
    return dict(row) if row else None


def revoke_token(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
    conn.commit()


def public_user(user: dict) -> dict:
    """A profile safe to send to the browser — no hash, no salt."""
    return {k: v for k, v in user.items() if k not in ("password_hash", "password_salt")}


# ── sessions ─────────────────────────────────────────────────────────────────

def start_session(
    conn: sqlite3.Connection,
    user_id: int,
    scenario_id: str,
    mode: str = "vetted",
    difficulty: str = "",
    environment: Optional[dict] = None,
    personas: bool = False,
) -> str:
    session_id = uuid.uuid4().hex
    conn.execute(
        """INSERT INTO sessions
               (id, user_id, scenario_id, mode, difficulty, environment_json,
                started_at, personas)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, user_id, scenario_id, mode, difficulty,
         json.dumps(environment or {}), _now(), int(personas)),
    )
    conn.commit()
    return session_id


def record_turns(conn: sqlite3.Connection, session_id: str, turns) -> None:
    """Persist the transcript so far. Idempotent — replaying costs nothing."""
    conn.executemany(
        """INSERT OR IGNORE INTO turns
               (session_id, seq, phase, speaker, utterance, intents_json, at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (session_id, t.seq, t.phase, t.speaker, t.utterance,
             json.dumps(list(t.intents)), t.at)
            for t in turns
        ],
    )
    conn.commit()


def finish_session(conn: sqlite3.Connection, session_id: str, grade: Any,
                   llm: Optional[dict] = None) -> None:
    """Store the debrief. ``grade`` is a `Grade` dataclass.

    ``llm`` is `LlmHealth.to_dict()` when personas were asked for, and None when
    they were not — which is the difference between "Claude was never invited"
    and "Claude was invited and never came".
    """
    conn.execute(
        "UPDATE sessions SET ended_at = ?, score = ?, points_possible = ?, "
        "passed = ?, grade_json = ?, llm_json = ? WHERE id = ?",
        (_now(), grade.points, grade.points_possible, int(grade.passed),
         json.dumps(grade.to_dict()),
         json.dumps(llm) if llm is not None else None, session_id),
    )
    conn.commit()


def attach_narrative(conn: sqlite3.Connection, session_id: str, narrative: dict) -> None:
    """Merge the model's debrief into the grade already stored for this session.

    A second write rather than a parameter to `finish_session`, so the ordering
    guarantee holds: the deterministic score is on disk before the network is
    touched, and a narrative that never arrives costs the trainee nothing. The
    narrative used to live only in the HTTP response, which meant the downloaded
    transcript — the one artifact anybody keeps — never had it.
    """
    row = conn.execute(
        "SELECT grade_json FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None or not row["grade_json"]:
        return
    grade = json.loads(row["grade_json"])
    grade["narrative"] = narrative
    conn.execute(
        "UPDATE sessions SET grade_json = ? WHERE id = ?",
        (json.dumps(grade), session_id),
    )
    conn.commit()


def get_session(conn: sqlite3.Connection, session_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_dict(row) if row else None


def list_sessions(conn: sqlite3.Connection, user_id: int, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? ORDER BY started_at DESC, rowid DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [_session_dict(r) for r in rows]


def get_turns(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM turns WHERE session_id = ? ORDER BY seq", (session_id,)
    ).fetchall()
    turns = []
    for row in rows:
        turn = dict(row)
        turn["intents"] = json.loads(turn.pop("intents_json"))
        turns.append(turn)
    return turns


def _session_dict(row: sqlite3.Row) -> dict:
    session = dict(row)
    session["environment"] = json.loads(session.pop("environment_json") or "{}")
    grade = session.pop("grade_json")
    session["grade"] = json.loads(grade) if grade else None
    return session
