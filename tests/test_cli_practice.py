"""The terminal simulator. One smoke test — the API tests carry the behavior.

Hints existed and worked, but were reachable only over HTTP, so a trainee at a
terminal had nothing when they got stuck.
"""
import pytest

from ems.cli import practice
from ems.sim.grade import parse_actions
from ems.frontmatter import read_page
from ems.paths import scenarios_dir


def _play(monkeypatch, capsys, argv, said=("BSI, scene is safe, one patient", "end of call")):
    replies = iter(said)
    monkeypatch.setattr("builtins.input", lambda *a: next(replies, "end of call"))
    monkeypatch.setattr("sys.argv", ["protocol-practice", *argv])
    practice.main()
    return capsys.readouterr().out


def test_hints_appear_when_asked_for(monkeypatch, capsys):
    out = _play(monkeypatch, capsys, ["--scenario", "src1-s02", "--hints"])
    assert "hint:" in out


def test_hints_stay_out_of_the_way_unless_asked(monkeypatch, capsys):
    out = _play(monkeypatch, capsys, ["--scenario", "src1-s02", "--no-hints"])
    assert "hint:" not in out


def test_basic_difficulty_offers_them_without_being_asked(monkeypatch, capsys):
    """The policy hints.py describes: proactive at Basic, on request above it."""
    out = _play(monkeypatch, capsys, ["--scenario", "src1-s02", "--level", "basic"])
    assert "hint:" in out


def test_a_hint_is_never_the_rubric_verbatim(monkeypatch, capsys):
    """A nudge points at a category. Handing over the answer key would make the
    debrief meaningless and the practice worthless."""
    out = _play(monkeypatch, capsys, ["--scenario", "src1-s02", "--hints"])
    hints = [line.split("hint:", 1)[1].strip() for line in out.splitlines() if "hint:" in line]
    assert hints
    rubric = parse_actions(read_page(scenarios_dir() / "src1-s02.md")[1])
    for hint in hints:
        assert not any(hint in action for action in rubric)


def test_a_generated_draft_can_be_played_by_name(monkeypatch, capsys):
    from ems.sim.generate import list_generated

    drafts = list_generated()
    if not drafts:
        pytest.skip("no generated drafts in quarantine to play")
    out = _play(monkeypatch, capsys, ["--scenario", drafts[0].stem])
    assert drafts[0].stem in out
