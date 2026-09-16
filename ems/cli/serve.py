"""protocol-serve — run the simulator API locally.

    python -m ems.cli.serve            # → http://127.0.0.1:8000
    python -m ems.cli.serve --host 0.0.0.0   # reachable from an iPad on the LAN
"""
import argparse
from pathlib import Path

from ems.paths import db_path


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-serve", description="Serve the ride-along simulator API."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: loopback)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, help=f"SQLite file (default: {db_path()})")
    parser.add_argument("--reload", action="store_true", help="Restart on code changes")
    args = parser.parse_args()

    import uvicorn

    from ems.web.server import create_app

    uvicorn.run(create_app(args.db), host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
