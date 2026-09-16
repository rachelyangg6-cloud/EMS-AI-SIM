"""Adding a column to a database that already exists.

`connect` only ever ran CREATE TABLE IF NOT EXISTS, so editing SCHEMA did
nothing to a database already on disk — and `var/ems.db` has one. These are the
tests for the only change in this feature that can damage something real.
"""
import sqlite3

import pytest

from ems.sim import store

#: The `users` table exactly as it was before `training_status`.
_OLD_USERS_DDL = """
CREATE TABLE departments (
    corp_slug    TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    region       TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE TABLE users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    corp_slug        TEXT NOT NULL REFERENCES departments(corp_slug),
    name             TEXT NOT NULL,
    scope_level      TEXT NOT NULL DEFAULT 'EMT-B',
    years_experience INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    UNIQUE (corp_slug, name)
);
"""


@pytest.fixture
def old_db(tmp_path):
    """A database created before the column existed, with a row in it."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_USERS_DDL)
    conn.execute("INSERT INTO departments VALUES ('westchester-vac', '', '', '2026-01-01')")
    conn.execute(
        "INSERT INTO users (corp_slug, name, scope_level, years_experience, created_at)"
        " VALUES ('westchester-vac', 'ry', 'Paramedic', 7, '2026-01-01')"
    )
    conn.commit()
    conn.close()
    return path


def _columns(conn, table="users"):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_an_old_database_gains_the_column_and_keeps_its_rows(old_db):
    conn = store.connect(old_db)
    row = store.find_user(conn, "westchester-vac", "ry")
    assert row["scope_level"] == "Paramedic"      # untouched
    assert row["years_experience"] == 7           # untouched
    assert row["training_status"] == "apprentice"  # backfilled from the DEFAULT


def test_the_backfill_is_apprentice_not_certified(old_db):
    """Fail closed. A row that predates the question never claimed anything, and
    silently granting corpus-write is the wrong direction."""
    conn = store.connect(old_db)
    assert not store.may_review(store.find_user(conn, "westchester-vac", "ry"))


def test_migrating_twice_is_a_no_op(old_db):
    store.connect(old_db).close()
    conn = store.connect(old_db)          # must not raise "duplicate column name"
    assert "training_status" in _columns(conn)


def test_a_fresh_database_and_a_migrated_one_have_the_same_columns(old_db, tmp_path):
    """Catches SCHEMA / _ADDED_COLUMNS drift when the next column is added —
    the failure nobody notices until a fresh install behaves differently."""
    migrated = _columns(store.connect(old_db))
    fresh = _columns(store.connect(tmp_path / "fresh.db"))
    assert migrated == fresh


# ── the clobber that would have undone all of it ─────────────────────────────

def test_an_omitted_training_status_does_not_demote_a_certified_user(tmp_path):
    """The web client does not send this field, so an unconditional overwrite
    would demote a certified EMT on every sign-in."""
    conn = store.connect(tmp_path / "t.db")
    store.upsert_user(conn, "vac", "ry", training_status="certified")
    store.upsert_user(conn, "vac", "ry", years_experience=8)   # a plain re-sign-in
    user = store.find_user(conn, "vac", "ry")
    assert user["training_status"] == "certified"
    assert user["years_experience"] == 8


def test_an_omitted_scope_level_does_not_reset_it(tmp_path):
    """The same bug, already live: api.ts never sends scope_level, so every
    browser sign-in was quietly resetting a Paramedic to EMT-B."""
    conn = store.connect(tmp_path / "t.db")
    store.upsert_user(conn, "vac", "ry", scope_level="Paramedic")
    store.upsert_user(conn, "vac", "ry", years_experience=3)
    assert store.find_user(conn, "vac", "ry")["scope_level"] == "Paramedic"


def test_a_supplied_value_still_wins(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.upsert_user(conn, "vac", "ry", training_status="apprentice")
    store.upsert_user(conn, "vac", "ry", training_status="certified")
    assert store.may_review(store.find_user(conn, "vac", "ry"))


def test_a_new_user_defaults_to_apprentice(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    user = store.upsert_user(conn, "vac", "newcomer")
    assert user["training_status"] == "apprentice" and not store.may_review(user)
