"""Logging in: what the password check must do, and what it must refuse.

Credentials are issued by `ems.cli.users` and never by the web client, which is
what makes the certified-reviewer gate mean anything. These are the tests for
the half of that which lives in the store.
"""
import sqlite3

import pytest

from ems.sim import store


@pytest.fixture
def account(tmp_path):
    """A user with a username and a password, as `ems.cli.users add` leaves them."""
    conn = store.connect(tmp_path / "t.db")
    user = store.upsert_user(conn, "westchester-vac", "Jane Roe", years_experience=3)
    store.set_username(conn, user["id"], "jroe-wvac")
    store.set_password(conn, user["id"], "amber-cedar-copper-1234")
    return conn, user


def test_the_right_password_is_accepted(account):
    conn, user = account
    assert store.authenticate(conn, "jroe-wvac", "amber-cedar-copper-1234")["id"] == user["id"]


def test_a_wrong_password_is_refused(account):
    conn, _ = account
    assert store.authenticate(conn, "jroe-wvac", "amber-cedar-copper-1235") is None


def test_an_unknown_username_is_refused(account):
    conn, _ = account
    assert store.authenticate(conn, "nobody-wvac", "amber-cedar-copper-1234") is None


def test_the_password_itself_is_never_stored(account):
    """Only the hash and the salt. If the file leaks, the passwords do not."""
    conn, user = account
    row = store.find_by_username(conn, "jroe-wvac")
    assert "amber-cedar-copper-1234" not in "".join(str(v) for v in row.values())
    assert row["password_hash"] and row["password_salt"]


def test_the_same_password_hashes_differently_for_two_people(tmp_path):
    """A per-user salt. Otherwise identical hashes announce identical passwords."""
    conn = store.connect(tmp_path / "t.db")
    for name, username in (("A One", "aone-vac"), ("B Two", "btwo-vac")):
        user = store.upsert_user(conn, "vac", name)
        store.set_username(conn, user["id"], username)
        store.set_password(conn, user["id"], "same-password-here-1111")
    a = store.find_by_username(conn, "aone-vac")
    b = store.find_by_username(conn, "btwo-vac")
    assert a["password_hash"] != b["password_hash"]


# ── tokens ───────────────────────────────────────────────────────────────────

def test_a_token_resolves_to_its_user(account):
    conn, user = account
    token = store.issue_token(conn, user["id"])
    assert store.user_for_token(conn, token)["name"] == "Jane Roe"


def test_a_revoked_token_resolves_to_nobody(account):
    conn, user = account
    token = store.issue_token(conn, user["id"])
    store.revoke_token(conn, token)
    assert store.user_for_token(conn, token) is None


def test_an_expired_token_resolves_to_nobody(account):
    conn, user = account
    token = store.issue_token(conn, user["id"])
    conn.execute("UPDATE auth_tokens SET expires_at = '2020-01-01T00:00:00+00:00'")
    conn.commit()
    assert store.user_for_token(conn, token) is None


def test_a_garbage_token_resolves_to_nobody(account):
    conn, _ = account
    assert store.user_for_token(conn, "not-a-token") is None
    assert store.user_for_token(conn, "") is None


def test_resetting_the_password_logs_the_old_session_out(account):
    """A reset is what you do when the password may be in someone else's hands,
    so leaving a live token behind would defeat the point of resetting it."""
    conn, user = account
    token = store.issue_token(conn, user["id"])
    store.set_password(conn, user["id"], "a-new-password-here-2222")
    assert store.user_for_token(conn, token) is None
    assert store.authenticate(conn, "jroe-wvac", "amber-cedar-copper-1234") is None
    assert store.authenticate(conn, "jroe-wvac", "a-new-password-here-2222")


# ── the constraints ──────────────────────────────────────────────────────────

def test_two_people_cannot_share_a_username(tmp_path):
    """The unique index, not the caller, is what stops a second account being
    made for a different person with the same name."""
    conn = store.connect(tmp_path / "t.db")
    first = store.upsert_user(conn, "vac", "Jane Roe")
    second = store.upsert_user(conn, "vac", "John Roe")
    store.set_username(conn, first["id"], "jroe-vac")
    with pytest.raises(sqlite3.IntegrityError):
        store.set_username(conn, second["id"], "jroe-vac")


def test_profiles_without_a_username_do_not_collide(tmp_path):
    """Every profile made before login existed has username NULL, and NULLs stay
    distinct in a SQLite unique index. They must keep working."""
    conn = store.connect(tmp_path / "t.db")
    store.upsert_user(conn, "vac", "One")
    store.upsert_user(conn, "vac", "Two")
    assert len(conn.execute("SELECT id FROM users WHERE username IS NULL").fetchall()) == 2


def test_public_user_carries_no_secret(account):
    conn, _ = account
    public = store.public_user(store.find_by_username(conn, "jroe-wvac"))
    assert "password_hash" not in public and "password_salt" not in public
    assert public["name"] == "Jane Roe"


def test_the_generated_username_and_password_are_the_shape_we_promise():
    assert store.generate_username("Jane Roe", "westchester-vac") == "jroe-wvac"
    assert store.generate_username("Cher", "vac") == "cher-vac"
    password = store.generate_password()
    assert len(password.split("-")) == 4 and password.rsplit("-", 1)[1].isdigit()
