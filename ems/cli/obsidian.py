"""Export the wiki as an Obsidian vault.

Metadata to stderr, per the project's CLI discipline — never the page content.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from ems.obsidian_export import export
from ems.paths import get_wiki_root, wiki_dir


def _obsidian_running() -> bool:
    """Best-effort, and deliberately fail-open: a false negative only costs a
    re-run, while refusing to write on a bad guess would be worse."""
    if not shutil.which("pgrep"):
        return False
    try:
        return subprocess.run(["pgrep", "-x", "Obsidian"], capture_output=True).returncode == 0
    except OSError:
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-obsidian",
        description="Write wiki/ to obsidian_wiki/ as a vault shaped for Obsidian.",
    )
    parser.add_argument("command", choices=["export"], help="Only one thing to do, so far.")
    parser.add_argument("--source", type=Path, default=None, help="Defaults to wiki/.")
    parser.add_argument("--dest", type=Path, default=None, help="Defaults to obsidian_wiki/.")
    parser.add_argument(
        "--reset-graph",
        action="store_true",
        help="Overwrite the graph-view settings with the tuned defaults, keeping a "
             ".bak. Close Obsidian first — it rewrites this file from memory.",
    )
    args = parser.parse_args(argv)

    source = args.source or wiki_dir()
    dest = args.dest or get_wiki_root() / "obsidian_wiki"

    # The one safety rule: never write over the corpus. Everything downstream
    # assumes wiki/ is untouched, and this command rewrites frontmatter into a
    # shape the application would reject.
    if dest.resolve() == source.resolve():
        print("refusing to export onto the source wiki", file=sys.stderr)
        return 2

    # Obsidian keeps graph settings in memory and writes them back when they
    # change, so a forced write while it is open is usually undone without
    # anything saying so. Warn rather than refuse: the detection is a guess.
    if args.reset_graph and _obsidian_running():
        print(
            "warning: Obsidian is running. It may overwrite these settings from "
            "memory — quit it and re-run if they do not appear.",
            file=sys.stderr,
        )

    result = export(source, dest, reset_graph=args.reset_graph)
    parts = ", ".join(f"{n} {d}" for d, n in result["by_dir"].items())
    print(f"{result['written']} notes ({parts})", file=sys.stderr)
    print(f"{result['dashboards']} dashboards → {result['dest']}", file=sys.stderr)
    if result["graph"]:
        print("graph view settings written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
