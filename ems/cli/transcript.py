"""protocol-transcript — export a practice call for review.

    protocol-transcript                      # the most recent call
    protocol-transcript --session <id>
    protocol-transcript --scenario src19-s02  # every run of one scenario
    protocol-transcript --all --limit 20     # a batch after a testing session
    protocol-transcript --stdout             # print instead of writing

Files land in `var/transcripts/`, which is outside version control. Mark them up
in free text — write a note on the line below anything worth commenting on — and
hand the file back.

The web UI has the same export behind the ⬇ button, and both go through
`ems.sim.transcript`, so a file exported either way is identical.
"""
import argparse
import sys
from pathlib import Path

from ems.paths import db_path
from ems.sim import store, transcript


def _sessions(conn, args) -> list[dict]:
    if args.session:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (args.session,)).fetchone()
        return [dict(row)] if row else []
    if args.scenario:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE scenario_id = ? ORDER BY started_at DESC LIMIT ?",
            (args.scenario, args.limit),
        )
    elif args.all:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (args.limit,)
        )
    else:
        rows = conn.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1")
    return [dict(r) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-transcript",
        description="Export a practice call as markdown for review.",
    )
    parser.add_argument("--session", help="A specific session id")
    parser.add_argument("--scenario", help="Every run of one scenario, e.g. src19-s02")
    parser.add_argument("--all", action="store_true", help="The most recent calls")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--stdout", action="store_true", help="Print instead of writing")
    parser.add_argument("--db", help=f"SQLite file (default: {db_path()})")
    args = parser.parse_args()

    conn = store.connect(args.db)
    sessions = _sessions(conn, args)
    if not sessions:
        print("No matching sessions. Play a call first.", file=sys.stderr)
        return 1

    # Beside the database they came from, so an --db override keeps them together.
    out = (Path(args.db) if args.db else db_path()).parent / "transcripts"
    if not args.stdout:
        out.mkdir(parents=True, exist_ok=True)

    for session in sessions:
        _, turns = transcript.load(conn, session["id"])
        text = transcript.render(session, turns)
        if args.stdout:
            print(text)
            continue
        path = out / transcript.filename(session)
        path.write_text(text, encoding="utf-8")
        print(path)

    if not args.stdout:
        print(f"\n{len(sessions)} transcript(s) in {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
