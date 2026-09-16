from pathlib import Path

import yaml


def read_page(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text) for a wiki markdown file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm = yaml.safe_load(parts[1]) or {}
    return fm, parts[2]


def read_frontmatter(path: Path) -> dict:
    """Return the frontmatter dict for a wiki markdown file."""
    fm, _ = read_page(path)
    return fm


def read_body(path: Path) -> str:
    """Return the body text (everything after the frontmatter block)."""
    _, body = read_page(path)
    return body


def write_frontmatter(path: Path, data: dict) -> None:
    """Overwrite the frontmatter block, preserving the body exactly."""
    _, body = read_page(path)
    fm_text = yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    # Add a newline after the closing fence only when the body does not bring
    # one. Never remove one: the corpus separates the fence from the first
    # heading with a blank line, and normalizing that away would rewrite 291
    # files the first time each was touched for an unrelated reason.
    #
    # The old code assumed the body always started with a newline, which is
    # true only when it came back from `read_page` splitting a file that *had*
    # frontmatter. Writing to a file with none — as `save_draft` does, body
    # first and frontmatter second — glued the fence to the first heading as
    # `---## Dispatch`. Every section parser then saw a file with no sections
    # at all, and two scenarios were approved that way before anyone noticed,
    # because the file still looks right to a human reading it.
    separator = "" if body.startswith("\n") else "\n"
    path.write_text(f"---\n{fm_text}---{separator}{body}", encoding="utf-8")
