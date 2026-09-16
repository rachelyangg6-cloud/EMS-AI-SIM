"""The credentials CLI — the only way an account comes into existence.

There is no sign-up endpoint, so if this is wrong nobody can log in; and if it
is wrong in the other direction, a password ends up recoverable from the
database, which is the failure that matters.
"""
import sqlite3
import sys

import pytest

from ems.cli import users as cli
from ems.sim import store


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    """Point the CLI at a throwaway database, not the real var/ems.db."""
    path = tmp_path / "cli.db"
    monkeypatch.setenv("EMS_DB_PATH", str(path))
    return path


def run(*argv) -> int:
    monkey = ["protocol-users", *argv]
    old, sys.argv = sys.argv, monkey
    try:
        return cli.main()
    finally:
        sys.argv = old


def credentials(out: str) -> tuple[str, str]:
    """Pull the pair back out of what the command printed."""
    lines = dict(
        (part.strip() for part in line.split(":", 1))
        for line in out.splitlines() if line.strip().startswith(("username:", "password:"))
    )
    return lines["username"], lines["password"]


def test_add_creates_an_account_that_can_log_in(capsys, db):
    assert run("add", "--corp", "westchester-vac", "--name", "Jane Roe",
               "--email", "jane@example.org", "--years", "3") == 0
    username, password = credentials(capsys.readouterr().out)
    assert username == "jroe-wvac"

    conn = store.connect(db)
    user = store.authenticate(conn, username, password)
    assert user and user["name"] == "Jane Roe"
    assert user["email"] == "jane@example.org"
    assert user["years_experience"] == 3


def test_the_password_is_not_in_the_database(capsys, db):
    run("add", "--corp", "vac", "--name", "Jane Roe")
    _, password = credentials(capsys.readouterr().out)
    assert password not in (db).read_bytes().decode("utf-8", errors="ignore")


def test_a_new_account_is_an_apprentice(capsys, db):
    """Fail closed: the right to write to the corpus is granted, never assumed."""
    run("add", "--corp", "vac", "--name", "Jane Roe")
    username, _ = credentials(capsys.readouterr().out)
    conn = store.connect(db)
    assert not store.may_review(store.find_by_username(conn, username))


def test_promote_grants_the_reviewer_right_and_revoke_takes_it_back(capsys, db):
    run("add", "--corp", "vac", "--name", "Jane Roe")
    username, _ = credentials(capsys.readouterr().out)

    assert run("promote", username) == 0
    conn = store.connect(db)
    assert store.may_review(store.find_by_username(conn, username))

    assert run("promote", username, "--revoke") == 0
    assert not store.may_review(store.find_by_username(store.connect(db), username))


def test_adding_the_same_person_twice_refuses_rather_than_duplicating(capsys, db):
    run("add", "--corp", "vac", "--name", "Jane Roe")
    capsys.readouterr()
    assert run("add", "--corp", "vac", "--name", "Jane Roe") == 1
    assert "already has a profile" in capsys.readouterr().err
    conn = store.connect(db)
    assert len(store.list_users(conn, "vac")) == 1


def test_a_username_collision_is_reported_not_silently_shared(capsys, db):
    """Two different people whose names generate the same username. The second
    must not end up sharing the first one's login."""
    run("add", "--corp", "vac", "--name", "Jane Roe")
    capsys.readouterr()
    assert run("add", "--corp", "vac", "--name", "Jack Roe") == 1
    assert "is taken" in capsys.readouterr().err
    assert run("add", "--corp", "vac", "--name", "Jack Roe",
               "--username", "jackroe-vac") == 1  # profile exists from the first try
    # …and the documented fix works on a person who does not have a profile yet:
    assert run("add", "--corp", "vac", "--name", "Jill Roe",
               "--username", "jillroe-vac") == 0
    username, password = credentials(capsys.readouterr().out)
    assert store.authenticate(store.connect(db), "jillroe-vac", password)


def test_reset_password_replaces_the_old_one(capsys, db):
    run("add", "--corp", "vac", "--name", "Jane Roe")
    username, first = credentials(capsys.readouterr().out)

    assert run("reset-password", username) == 0
    _, second = credentials(capsys.readouterr().out)
    assert first != second

    conn = store.connect(db)
    assert store.authenticate(conn, username, first) is None
    assert store.authenticate(conn, username, second)


def test_reset_password_signs_out_a_live_session(capsys, db):
    """A reset is what you do when the password may be in the wrong hands."""
    run("add", "--corp", "vac", "--name", "Jane Roe")
    username, _ = credentials(capsys.readouterr().out)
    conn = store.connect(db)
    token = store.issue_token(conn, store.find_by_username(conn, username)["id"])

    run("reset-password", username)
    assert store.user_for_token(store.connect(db), token) is None


def test_reset_password_for_nobody_says_so(capsys, db):
    assert run("reset-password", "ghost-vac") == 1
    assert "No account" in capsys.readouterr().err


def test_list_shows_the_roster_and_an_empty_one_says_so(capsys, db):
    assert run("list") == 0
    assert "No accounts" in capsys.readouterr().out

    run("add", "--corp", "vac", "--name", "Jane Roe", "--email", "j@x.org")
    capsys.readouterr()
    assert run("list", "--corp", "vac") == 0
    out = capsys.readouterr().out
    assert "jroe-vac" in out and "Jane Roe" in out and "j@x.org" in out
    assert "apprentice" in out


def test_a_profile_made_before_logins_existed_lists_without_one(capsys, db):
    conn = store.connect(db)
    store.upsert_user(conn, "vac", "Old Hand")     # no username, as the web form made them
    conn.close()
    assert run("list", "--corp", "vac") == 0
    assert "no login" in capsys.readouterr().out


# ── set-password: a login for a profile that predates logins ────────────────
#
# `add` cannot serve this case. It refuses a name that already has a profile,
# and were it to succeed it would write a *second* row — sessions key on
# `user_id`, so every call the original account had run would stay behind on a
# row nobody could sign in to. The real account this was written for had twenty.


def test_set_password_gives_a_login_to_a_profile_that_had_none(capsys, db):
    conn = store.connect(db)
    store.upsert_user(conn, "westchester-vac", "Old Hand")
    conn.close()

    assert run("set-password", "--corp", "westchester-vac", "--name", "Old Hand") == 0
    username, password = credentials(capsys.readouterr().out)

    conn = store.connect(db)
    user = store.authenticate(conn, username, password)
    assert user and user["name"] == "Old Hand"


def test_set_password_keeps_the_history_the_profile_already_owned(capsys, db):
    """The whole point: same row, so the sessions come with it."""
    conn = store.connect(db)
    before = store.upsert_user(conn, "westchester-vac", "Old Hand")
    conn.close()

    assert run("set-password", "--corp", "westchester-vac", "--name", "Old Hand") == 0
    username, _ = credentials(capsys.readouterr().out)

    conn = store.connect(db)
    assert store.find_by_username(conn, username)["id"] == before["id"]


def test_set_password_refuses_an_account_that_can_already_sign_in(capsys, db):
    """"Set" must not quietly mean "reset" — that would sign someone out."""
    assert run("add", "--corp", "westchester-vac", "--name", "Jane Roe") == 0
    username, password = credentials(capsys.readouterr().out)

    assert run("set-password", "--corp", "westchester-vac", "--name", "Jane Roe") == 1
    assert "reset-password" in capsys.readouterr().err

    conn = store.connect(db)
    assert store.authenticate(conn, username, password), "the old password still works"


def test_set_password_for_a_profile_that_does_not_exist_says_so(capsys, db):
    assert run("set-password", "--corp", "westchester-vac", "--name", "Nobody") == 1
    assert "No profile" in capsys.readouterr().err


def test_set_password_reports_a_username_collision(capsys, db):
    assert run("add", "--corp", "westchester-vac", "--name", "Jane Roe") == 0
    capsys.readouterr()
    conn = store.connect(db)
    store.upsert_user(conn, "westchester-vac", "Jane Roe II")
    conn.close()

    assert run("set-password", "--corp", "westchester-vac", "--name", "Jane Roe II",
               "--username", "jroe-wvac") == 1
    assert "taken" in capsys.readouterr().err
