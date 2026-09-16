"""Turn a reviewed generated call into an expertise-marked fact — or into a lesson.

This is the half of the flywheel that carries the EMT's judgement. A generated
draft sits in `wiki/scenarios/generated/` where nothing can deal it. Reviewing it
does one of two things, and both are useful:

**Approved** — the file moves into `wiki/scenarios/` with `status: approved` and
`labeled_by: <emt>`, through the same `save_label` call the source scenarios go
through. From that moment it is indistinguishable from src2–src25 content and is
eligible for the next Vetted Case draw. The corpus grew because someone played a
call and vouched for it.

**Rejected** — the file stays in quarantine with the critique attached, and the
critique is distilled into `system/generation-lessons.md`, which goes into the
prompt for every later generation. The rejection is not a wasted call; it is the
generator getting better at the thing it got wrong.

Nothing here decides whether a call is realistic. It records what an EMT decided.
"""

from datetime import date
from pathlib import Path
from typing import Optional

from ems.frontmatter import read_page, write_frontmatter
from ems.scenarios import save_label
from ems.paths import scenarios_dir
from ems.sim.generate import generated_dir, lessons_path

_LESSONS_HEADER = """# Generation lessons

Realism failures found by EMTs reviewing generated calls, in their words. Every
line here was written because a draft got something wrong badly enough to be
rejected, and every line is fed back into the generation prompt.

Not a style guide. A list of specific mistakes not to repeat.
"""


def find_generated(scenario_id: str, dest: Optional[Path] = None) -> Optional[Path]:
    """The quarantined draft with this id, if it is still there.

    `save_draft` writes `scenario_id` equal to the file stem, so this is the
    convention rather than a guess — and it lives here, next to the code that
    relies on it, so a caller does not have to know the layout.

    Returns None once a draft has been approved and moved, which is what makes a
    double review answerable with a clear error instead of a crash.
    """
    path = (dest or generated_dir()) / f"{scenario_id}.md"
    return path if path.exists() else None


def approve(
    path: Path,
    labeled_by: str,
    realism_rating: Optional[int] = None,
    realism_note: str = "",
    new_body: Optional[str] = None,
    dest: Optional[Path] = None,
    session_id: str = "",
) -> Path:
    """Promote a generated draft into the vetted corpus.

    The file moves. A generated scenario that stayed in quarantine while being
    marked approved would be approved and undealable at the same time, which is
    the kind of state that is discovered months later.
    """
    dest = dest or scenarios_dir()
    save_label(
        path,
        status="approved",
        labeled_by=labeled_by,
        corrected=new_body is not None,
        correction_note=realism_note,
        new_body=new_body,
    )

    frontmatter, body = read_page(path)
    if realism_rating is not None:
        frontmatter["realism_rating"] = realism_rating
    if realism_note:
        frontmatter["realism_note"] = realism_note
    if session_id:
        # Which call this judgement came out of. `labeled_by` records who
        # approved it; this records what they had just played when they did,
        # which is the other half of answering "why is this in the corpus?"
        frontmatter["reviewed_after_session"] = session_id
    write_frontmatter(path, frontmatter)

    dest.mkdir(parents=True, exist_ok=True)
    promoted = dest / path.name
    promoted.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.unlink()
    return promoted


def reject(
    path: Path,
    labeled_by: str,
    critique: str,
    realism_rating: Optional[int] = None,
    lessons: Optional[Path] = None,
) -> Path:
    """Keep the draft in quarantine, and turn the critique into a lesson."""
    if not critique.strip():
        raise ValueError("a rejection needs a critique — it is the only thing it produces")

    save_label(path, status="rejected", labeled_by=labeled_by, correction_note=critique)
    frontmatter, _ = read_page(path)
    if realism_rating is not None:
        frontmatter["realism_rating"] = realism_rating
    frontmatter["realism_note"] = critique
    write_frontmatter(path, frontmatter)

    record_lesson(critique, path.stem, lessons)
    return path


def defer(
    path: Path,
    session_id: str = "",
    note: str = "",
    today: Optional[date] = None,
) -> Path:
    """Set a draft aside, still unjudged, and remember that it was seen.

    Not a third verdict. Approve and reject both settle a draft; this one says
    "not yet" — the reviewer liked it enough not to reject it and not enough to
    put it in front of trainees. `status` stays `pending`, so every gate that
    keeps unreviewed material out of the corpus keeps working untouched.

    What changes is the *order* it comes back in: `deferred_at` moves it behind
    drafts nobody has seen, so a reviewer working through a queue is not handed
    the same call twice before reaching the end. Any half-formed comment is kept
    as `deferred_note`, because the reason for hesitating is the thing most
    likely to be forgotten by the time it comes round again.
    """
    frontmatter, _ = read_page(path)
    frontmatter["deferred_at"] = (today or date.today()).isoformat()
    if session_id:
        frontmatter["deferred_after_session"] = session_id
    if note.strip():
        frontmatter["deferred_note"] = note.strip()
    write_frontmatter(path, frontmatter)
    return path


def record_lesson(
    critique: str,
    scenario_id: str = "",
    path: Optional[Path] = None,
    today: Optional[date] = None,
) -> Path:
    """Append one critique to the lessons file, creating it if needed."""
    path = path or lessons_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_LESSONS_HEADER, encoding="utf-8")

    stamp = (today or date.today()).isoformat()
    trailer = f"  _({scenario_id}, {stamp})_" if scenario_id else f"  _({stamp})_"
    line = f"- {critique.strip()}{trailer}\n"

    existing = path.read_text(encoding="utf-8")
    if critique.strip() in existing:
        return path            # said once is enough
    path.write_text(existing.rstrip("\n") + "\n" + line, encoding="utf-8")
    return path


def load_lessons_text(path: Optional[Path] = None) -> str:
    """The accumulated lessons, for showing a reviewer what rejections taught."""
    from ems.sim.generate import load_lessons
    return load_lessons(path)


def pending(dest: Optional[Path] = None) -> list[Path]:
    """Generated drafts waiting on a review."""
    from ems.sim.generate import list_generated
    return list_generated(dest or generated_dir(), status="pending")
