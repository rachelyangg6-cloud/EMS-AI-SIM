"""The closing `---` and the newline that has to follow it.

`write_frontmatter` assumed the body it was given already began with a newline.
That holds when the body came back from `read_page` splitting a file that *had*
frontmatter, and not when the file had none — which is exactly what `save_draft`
does, writing the body first and the frontmatter second.

The result was `---## Dispatch`. YAML still parsed, the file still looked right
to anyone reading it, and every section parser saw a document with no sections.
Two scenarios were approved into the corpus that way.
"""
from pathlib import Path

import pytest

from ems.frontmatter import read_page, write_frontmatter

CORPUS_FILE = Path(__file__).resolve().parent.parent / "wiki" / "scenarios" / "src1-s01.md"


def test_frontmatter_over_a_file_that_has_none(tmp_path):
    """The save_draft order: body first, frontmatter second."""
    path = tmp_path / "draft.md"
    path.write_text("## Dispatch\nA 62-year-old man.\n", encoding="utf-8")
    write_frontmatter(path, {"type": "scenario"})

    assert "---## Dispatch" not in path.read_text(encoding="utf-8")
    _, body = read_page(path)
    assert "## Dispatch" in body.splitlines()


def test_the_sections_survive_the_round_trip(tmp_path):
    """The real symptom: not a missing newline, a file with no sections."""
    path = tmp_path / "draft.md"
    path.write_text("## Dispatch\nA man.\n\n## Vitals\nRR 24.\n", encoding="utf-8")
    write_frontmatter(path, {"type": "scenario"})

    _, body = read_page(path)
    assert [l for l in body.splitlines() if l.startswith("## ")] == ["## Dispatch", "## Vitals"]


def test_an_existing_corpus_file_round_trips_byte_for_byte(tmp_path):
    """The corpus separates the fence from the first heading with a blank line.
    Normalizing that away would rewrite 291 files the first time each was
    touched for an unrelated reason, so the fix only ever *adds* a newline."""
    path = tmp_path / "copy.md"
    path.write_bytes(CORPUS_FILE.read_bytes())
    before = path.read_bytes()

    frontmatter, _ = read_page(path)
    write_frontmatter(path, frontmatter)

    assert path.read_bytes() == before


def test_writing_twice_does_not_accumulate_newlines(tmp_path):
    path = tmp_path / "draft.md"
    path.write_text("## Dispatch\nA man.\n", encoding="utf-8")
    write_frontmatter(path, {"type": "scenario"})
    once = path.read_text(encoding="utf-8")
    write_frontmatter(path, {"type": "scenario"})
    assert path.read_text(encoding="utf-8") == once
