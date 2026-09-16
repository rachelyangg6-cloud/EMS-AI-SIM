from datetime import date

from ems.frontmatter import read_page
from ems.page_updater import iter_page_paths
from ems.paths import wiki_dir


def log_path():
    return wiki_dir() / "log.md"


def index_path():
    return wiki_dir() / "index.md"


def append_log(entry: str) -> None:
    """Append a timestamped line to the append-only ingest log."""
    path = log_path()
    header = "" if path.exists() else "# Ingest Log\n\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{header}- {date.today().isoformat()} — {entry}\n")


def regenerate_index() -> None:
    """Rebuild wiki/index.md: pages grouped by type, superseded ones flagged."""
    by_type: dict[str, list[str]] = {}
    for path in sorted(iter_page_paths()):
        fm, _ = read_page(path)
        ptype = fm.get("type", "unknown")
        title = fm.get("title") or path.stem
        status = fm.get("status", "")
        label = f"[[{path.stem}]] — {title}"
        if status == "superseded":
            label += "  *(superseded)*"
        by_type.setdefault(ptype, []).append(label)

    lines = ["# Wiki Index", ""]
    for ptype in sorted(by_type):
        lines.append(f"## {ptype.capitalize()}s")
        lines.extend(f"- {item}" for item in by_type[ptype])
        lines.append("")

    index_path().write_text("\n".join(lines), encoding="utf-8")
