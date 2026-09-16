"""protocol-users — issue and manage the credentials people log in with.

    protocol-users add --corp westchester-vac --name "Jane Roe" \
                       --email jane@example.org --years 3 --status apprentice
    protocol-users set-password --corp westchester-vac --name "Jane Roe"
    protocol-users reset-password jroe-wvac
    protocol-users list --corp westchester-vac
    protocol-users promote jroe-wvac        # apprentice → certified

There is no self-service sign-up and no self-service password change. Accounts
exist because whoever runs this command made one, which is what lets the server
believe `training_status` — the flag deciding whether an EMT may promote a
generated draft into the vetted corpus.

A password is shown once, at the moment it is generated, and is never
recoverable afterward: only its scrypt hash is stored. Someone who has lost
theirs needs `reset-password`, which also signs out every live session for that
account.

`set-password` is for the other case: a profile that predates logins and has no
username at all. `add` will not serve, because it refuses a name that already
has a profile — and even if it did not, it would make a *second* row, orphaning
every session the first one owns. So this attaches a credential to the profile
that is already there, and the practice history comes with it.
"""
import argparse
import sqlite3
import sys

from ems.sim import store


def _issued(username: str, password: str) -> None:
    """Print a credential exactly once, and say so."""
    print()
    print("  username:", username)
    print("  password:", password)
    print()
    print("Write the password down now. It is stored only as a hash and cannot")
    print("be read back — a lost one has to be reset, not recovered.")


def _row(user: dict) -> str:
    flag = "certified" if store.may_review(user) else "apprentice"
    login = user.get("username") or "— no login —"
    return (f"  {login:<20} {user['name']:<22} {user['scope_level']:<10} "
            f"{flag:<11} {user.get('email') or ''}")


def _add(conn: sqlite3.Connection, args) -> int:
    if store.find_user(conn, args.corp, args.name):
        print(f"{args.name} already has a profile in {args.corp}.", file=sys.stderr)
        print("Use `reset-password` to give them a new password.", file=sys.stderr)
        return 1

    user = store.upsert_user(
        conn,
        corp_slug=args.corp,
        name=args.name,
        scope_level=args.scope,
        years_experience=args.years,
        training_status=args.status,
        email=args.email,
    )
    username = args.username or store.generate_username(args.name, args.corp)
    try:
        store.set_username(conn, user["id"], username)
    except sqlite3.IntegrityError:
        # The failed UPDATE leaves a write transaction open, and it would hold
        # the lock until the process exits — long enough to block whatever runs
        # next in the same session.
        conn.rollback()
        # The profile is made but has no login. Say which half worked, so the
        # fix is a second command and not a puzzle.
        print(f"The username {username!r} is taken.", file=sys.stderr)
        print(f"{args.name}'s profile was created; re-run with --username to "
              f"give them a different one.", file=sys.stderr)
        return 1

    password = store.generate_password()
    store.set_password(conn, user["id"], password)
    _issued(username, password)
    return 0


def _set_password(conn: sqlite3.Connection, args) -> int:
    """Give a login to a profile that has none, keeping everything it owns.

    Accounts made before logins existed are EMT records with no username and no
    hash, and there was no way to promote one. `add` refuses the name and would
    otherwise create a second row; sessions key on `user_id`, so the original's
    practice history would stay behind on a row nobody could sign in to.
    """
    user = store.find_user(conn, args.corp, args.name)
    if not user:
        print(f"No profile for {args.name!r} in {args.corp}.", file=sys.stderr)
        print("`protocol-users list` shows what exists; `add` makes one.",
              file=sys.stderr)
        return 1
    if user.get("username"):
        # Never silently reset: this command is for accounts with no login, and
        # quietly signing someone out is not what "set" should mean.
        print(f"{args.name} already signs in as {user['username']!r}.",
              file=sys.stderr)
        print("Use `reset-password` to issue a new password for that account.",
              file=sys.stderr)
        return 1

    username = args.username or store.generate_username(args.name, args.corp)
    try:
        store.set_username(conn, user["id"], username)
    except sqlite3.IntegrityError:
        conn.rollback()
        print(f"The username {username!r} is taken.", file=sys.stderr)
        print("Re-run with --username to choose a different one.", file=sys.stderr)
        return 1

    password = store.generate_password()
    store.set_password(conn, user["id"], password)
    print(f"{user['name']} can now sign in, and keeps everything already "
          f"recorded against this profile.")
    _issued(username, password)
    return 0


def _reset(conn: sqlite3.Connection, args) -> int:
    user = store.find_by_username(conn, args.username)
    if not user:
        print(f"No account with the username {args.username!r}.", file=sys.stderr)
        return 1
    password = store.generate_password()
    store.set_password(conn, user["id"], password)   # also revokes live tokens
    print(f"Reset for {user['name']}. Any session still signed in is now signed out.")
    _issued(args.username, password)
    return 0


def _list(conn: sqlite3.Connection, args) -> int:
    users = store.list_users(conn, args.corp)
    if not users:
        where = f" in {args.corp}" if args.corp else ""
        print(f"No accounts{where} yet. `protocol-users add` makes one.")
        return 0
    print(f"\n  {'LOGIN':<20} {'NAME':<22} {'SCOPE':<10} {'STATUS':<11} EMAIL")
    print(f"  {'─' * 78}")
    for user in users:
        print(_row(user))
    print()
    return 0


def _promote(conn: sqlite3.Connection, args) -> int:
    """Grant the right to promote a generated draft into the vetted corpus."""
    user = store.find_by_username(conn, args.username)
    if not user:
        print(f"No account with the username {args.username!r}.", file=sys.stderr)
        return 1
    status = "apprentice" if args.revoke else "certified"
    store.upsert_user(conn, user["corp_slug"], user["name"], training_status=status)
    print(f"{user['name']} is now {status}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-users",
        description="Issue and manage login credentials.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Create an account and print its credentials")
    add.add_argument("--corp", required=True, help="Department slug, e.g. westchester-vac")
    add.add_argument("--name", required=True, help="The EMT's name, e.g. \"Jane Roe\"")
    add.add_argument("--email", default="", help="Contact address (optional)")
    add.add_argument("--years", type=int, default=0, help="Years of experience")
    add.add_argument("--scope", default="EMT-B", help="EMT-B, AEMT or Paramedic")
    add.add_argument("--status", default="apprentice", choices=store.TRAINING_STATUSES,
                     help="Whether they may promote generated drafts")
    add.add_argument("--username", default="",
                     help="Override the generated username, e.g. after a collision")
    add.set_defaults(handler=_add)

    setpw = subparsers.add_parser(
        "set-password",
        help="Give a login to a profile that has none, keeping its history")
    setpw.add_argument("--corp", required=True, help="Department slug, e.g. westchester-vac")
    setpw.add_argument("--name", required=True, help="The EMT's name, as `list` shows it")
    setpw.add_argument("--username", default="",
                       help="Override the generated username, e.g. after a collision")
    setpw.set_defaults(handler=_set_password)

    reset = subparsers.add_parser("reset-password",
                                  help="Issue a new password and sign the account out")
    reset.add_argument("username")
    reset.set_defaults(handler=_reset)

    listing = subparsers.add_parser("list", help="Show the accounts that exist")
    listing.add_argument("--corp", default="", help="Limit to one department")
    listing.set_defaults(handler=_list)

    promote = subparsers.add_parser("promote", help="Make an account a certified reviewer")
    promote.add_argument("username")
    promote.add_argument("--revoke", action="store_true", help="Back to apprentice instead")
    promote.set_defaults(handler=_promote)

    args = parser.parse_args()
    conn = store.connect()
    try:
        return args.handler(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
