"""
Tests for scenario generation and labeling (Task D/E).
Fully offline — the LLM is injected/mocked.
"""
import json

import pytest

from ems.markdown import extract_wikilinks, get_section
from ems.scenarios import generate_scenarios, list_pending, save_label


VOCAB = {
    "conditions": ["anaphylaxis", "shock"],
    "procedures": ["epinephrine-auto-injector", "iv-access"],
    "medications": ["epinephrine"],
    "scope_levels": ["EMT-B", "AEMT", "Paramedic"],
}

SCENARIOS_JSON = json.dumps({
    "scenarios": [
        {
            "dispatch": "30 y/o male, difficulty breathing after a bee sting.",
            "presentation": "Hives, audible wheeze, anxious.",
            "vitals": "HR 120, BP 90/60, SpO2 91%.",
            "correct_action_sequence": [
                "Assess airway and breathing",
                "Administer epinephrine 0.3 mg IM via auto-injector",
                "High-flow oxygen; rapid transport",
            ],
            "scope_level": "EMT-B",
            "rationale": "Anaphylaxis with airway compromise needs IM epinephrine now.",
            "red_flags": ["Stridor", "Hypotension"],
            "citations": ["[SRC-1:p42]"],
            "conditions": ["anaphylaxis", "not-a-real-condition"],
            "procedures": ["epinephrine-auto-injector"],
            "medications": ["epinephrine"],
        }
    ]
})


def fake_llm(prompt, system="", model=None):
    return SCENARIOS_JSON


@pytest.fixture
def scen_dir(tmp_path):
    d = tmp_path / "scenarios"
    d.mkdir()
    return d


class TestGenerate:
    def test_writes_file_with_frontmatter(self, scen_dir):
        paths = generate_scenarios(1, "source text [p.42]", VOCAB, n=1, llm=fake_llm, dest_dir=scen_dir)
        assert len(paths) == 1
        p = paths[0]
        assert p.name == "src1-s01.md"

        from ems.frontmatter import read_page
        fm, body = read_page(p)
        assert fm["type"] == "scenario"
        assert fm["status"] == "pending"
        assert fm["scope_level"] == "EMT-B"
        # bogus slug filtered against vocabulary
        assert fm["conditions"] == ["anaphylaxis"]
        assert fm["citations"] == ["[SRC-1:p42]"]
        assert "0.3 mg IM" in get_section(body, "Correct actions")

    def test_cross_links_related_pages(self, scen_dir):
        p = generate_scenarios(1, "text", VOCAB, n=1, llm=fake_llm, dest_dir=scen_dir)[0]
        from ems.frontmatter import read_page
        _fm, body = read_page(p)
        links = extract_wikilinks(body)
        assert "anaphylaxis" in links
        assert "epinephrine" in links

    def test_reruns_do_not_clobber(self, scen_dir):
        first = generate_scenarios(1, "t", VOCAB, n=1, llm=fake_llm, dest_dir=scen_dir)[0]
        second = generate_scenarios(1, "t", VOCAB, n=1, llm=fake_llm, dest_dir=scen_dir)[0]
        assert first.name == "src1-s01.md"
        assert second.name == "src1-s02.md"


class TestSaveScenario:
    def test_save_scenario_writes_pending(self, scen_dir):
        from ems.models import Scenario
        from ems.scenarios import save_scenario
        from ems.frontmatter import read_page

        s = Scenario(
            dispatch="d", presentation="p", vitals="v",
            correct_action_sequence=("act one",),
            scope_level="AEMT", rationale="because",
            citations=("[SRC-2:p10]",), conditions=("shock",),
        )
        path = save_scenario(2, s, dest_dir=scen_dir)
        assert path.name == "src2-s01.md"
        fm, _ = read_page(path)
        assert fm["status"] == "pending"
        assert fm["scope_level"] == "AEMT"
        assert fm["source_index"] == 2
        assert fm["kind"] == "patient-care"  # default category

    def test_save_scenario_records_kind(self, scen_dir):
        from ems.models import Scenario
        from ems.scenarios import save_scenario
        from ems.frontmatter import read_page
        s = Scenario(dispatch="d", presentation="p", vitals="N/A",
                     correct_action_sequence=("don gloves",), scope_level="EMT-B",
                     rationale="standard precautions")
        path = save_scenario(2, s, kind="provider-safety", dest_dir=scen_dir)
        assert read_page(path)[0]["kind"] == "provider-safety"

    def test_age_group_defaults_to_adult(self, scen_dir):
        from ems.models import Scenario
        from ems.scenarios import save_scenario
        from ems.frontmatter import read_page
        s = Scenario(dispatch="d", presentation="p", vitals="v",
                     correct_action_sequence=("a",), scope_level="EMT-B", rationale="r")
        path = save_scenario(2, s, dest_dir=scen_dir)
        assert read_page(path)[0]["age_group"] == "adult"

    def test_age_group_pediatric_round_trips(self, scen_dir):
        from ems.models import Scenario
        from ems.scenarios import save_scenario
        from ems.frontmatter import read_page
        s = Scenario(dispatch="d", presentation="p", vitals="v",
                     correct_action_sequence=("a",), scope_level="EMT-B",
                     rationale="r", age_group="pediatric")
        path = save_scenario(2, s, dest_dir=scen_dir)
        assert read_page(path)[0]["age_group"] == "pediatric"

    def test_invalid_age_group_clamps_to_adult(self, scen_dir):
        from ems.models import Scenario
        from ems.scenarios import save_scenario
        from ems.frontmatter import read_page
        s = Scenario(dispatch="d", presentation="p", vitals="v",
                     correct_action_sequence=("a",), scope_level="EMT-B",
                     rationale="r", age_group="toddlerish")
        path = save_scenario(2, s, dest_dir=scen_dir)
        assert read_page(path)[0]["age_group"] == "adult"


class TestLabeling:
    def test_list_pending(self, scen_dir):
        generate_scenarios(1, "t", VOCAB, n=1, llm=fake_llm, dest_dir=scen_dir)
        pending = list_pending(scen_dir)
        assert len(pending) == 1

    def test_list_pending_by_source(self, scen_dir):
        from ems.models import Scenario
        from ems.scenarios import save_scenario
        s = Scenario(dispatch="d", presentation="p", vitals="v",
                     correct_action_sequence=("a",), scope_level="EMT-B", rationale="r")
        save_scenario(1, s, dest_dir=scen_dir)
        save_scenario(2, s, dest_dir=scen_dir)
        assert len(list_pending(scen_dir, source_index=1)) == 1
        assert len(list_pending(scen_dir, source_index=2)) == 1
        assert len(list_pending(scen_dir)) == 2

    def test_save_label_approve(self, scen_dir):
        p = generate_scenarios(1, "t", VOCAB, n=1, llm=fake_llm, dest_dir=scen_dir)[0]
        save_label(p, status="approved", labeled_by="rachel")

        from ems.frontmatter import read_page
        fm, _ = read_page(p)
        assert fm["status"] == "approved"
        assert fm["labeled_by"] == "rachel"
        assert list_pending(scen_dir) == []  # no longer pending

    def test_save_label_correction_preserves_and_edits_body(self, scen_dir):
        p = generate_scenarios(1, "t", VOCAB, n=1, llm=fake_llm, dest_dir=scen_dir)[0]
        save_label(
            p, status="approved", labeled_by="rachel",
            corrected=True, correction_note="fixed dose route",
            new_body="\n## Dispatch\nCorrected.\n",
        )
        from ems.frontmatter import read_page
        fm, body = read_page(p)
        assert fm["corrected"] is True
        assert fm["correction_note"] == "fixed dose route"
        assert "Corrected." in body

    def test_save_label_records_difficulty_override(self, scen_dir):
        from ems.frontmatter import read_page
        p = generate_scenarios(1, "t", VOCAB, n=1, llm=fake_llm, dest_dir=scen_dir)[0]
        save_label(p, status="approved", labeled_by="rachel", difficulty="expert")
        assert read_page(p)[0]["difficulty"] == "expert"

    def test_save_label_rejects_bogus_difficulty(self, scen_dir):
        p = generate_scenarios(1, "t", VOCAB, n=1, llm=fake_llm, dest_dir=scen_dir)[0]
        with pytest.raises(ValueError):
            save_label(p, status="approved", labeled_by="rachel", difficulty="very-hard")


# ── ems/sim: difficulty derivation and approved-scenario access ─────────────

def _approve(path, labeled_by="rachel", **kw):
    save_label(path, status="approved", labeled_by=labeled_by, **kw)
    return path


def _make(scen_dir, source_index=1, **kw):
    """Write one pending scenario, overriding any Scenario field."""
    from ems.models import Scenario
    from ems.scenarios import save_scenario
    fields = dict(
        dispatch="d", presentation="p", vitals="v",
        correct_action_sequence=("assess airway",),
        scope_level="EMT-B", rationale="r",
    )
    kind = kw.pop("kind", "patient-care")
    fields.update(kw)
    return save_scenario(source_index, Scenario(**fields), kind=kind, dest_dir=scen_dir)


class TestDifficulty:
    def test_short_uncomplicated_call_is_basic(self, scen_dir):
        from ems.frontmatter import read_page
        from ems.sim.difficulty import derive_difficulty
        p = _make(scen_dir, correct_action_sequence=("obtain consent", "document refusal"),
                  rationale="competent adult may refuse")
        fm, body = read_page(p)
        assert derive_difficulty(fm, body) == "basic"

    def test_long_call_with_meds_and_deterioration_is_expert(self, scen_dir):
        from ems.frontmatter import read_page
        from ems.sim.difficulty import derive_difficulty
        p = _make(
            scen_dir,
            correct_action_sequence=tuple(f"step {i}" for i in range(1, 8)),
            red_flags=("stridor", "hypotension", "altered mental status"),
            medications=("epinephrine",),
            procedures=("epinephrine-auto-injector",),
            rationale="Patient deteriorates; request ALS intercept and ventilate with a BVM.",
        )
        fm, body = read_page(p)
        assert derive_difficulty(fm, body) == "expert"

    def test_score_rises_with_complexity(self, scen_dir):
        from ems.frontmatter import read_page
        from ems.sim.difficulty import difficulty_score
        simple = _make(scen_dir, correct_action_sequence=("look",), rationale="r")
        complex_ = _make(
            scen_dir,
            correct_action_sequence=tuple(f"step {i}" for i in range(1, 7)),
            red_flags=("a", "b", "c"), medications=("oxygen",),
            rationale="deteriorating; call ALS",
        )
        assert difficulty_score(*read_page(complex_)) > difficulty_score(*read_page(simple))

    def test_derived_level_is_always_valid(self, scen_dir):
        from ems.frontmatter import read_page
        from ems.sim.difficulty import DIFFICULTY_LEVELS, derive_difficulty
        p = _make(scen_dir)
        assert derive_difficulty(*read_page(p)) in DIFFICULTY_LEVELS


class TestListApproved:
    def test_only_returns_approved_with_reviewer(self, scen_dir):
        from ems.scenarios import list_approved
        _approve(_make(scen_dir, source_index=1))
        _make(scen_dir, source_index=1)                                  # still pending
        save_label(_make(scen_dir, source_index=1), status="rejected", labeled_by="rachel")
        assert [p.name for p in list_approved(scen_dir)] == ["src1-s01.md"]

    def test_unreviewed_approval_is_not_a_fact(self, scen_dir):
        """status: approved without labeled_by is not expertise-marked."""
        from ems.scenarios import list_approved
        save_label(_make(scen_dir), status="approved", labeled_by="")
        assert list_approved(scen_dir) == []

    def test_filters_are_composable(self, scen_dir):
        from ems.scenarios import list_approved
        _approve(_make(scen_dir, source_index=1, conditions=("shock",)), difficulty="basic")
        _approve(_make(scen_dir, source_index=2, conditions=("anaphylaxis",)), difficulty="expert")
        _approve(_make(scen_dir, source_index=2, kind="operational"), difficulty="basic")

        assert len(list_approved(scen_dir, source_index=2)) == 2
        assert len(list_approved(scen_dir, difficulty="basic")) == 2
        assert len(list_approved(scen_dir, kind="operational")) == 1
        assert len(list_approved(scen_dir, conditions=["shock"])) == 1
        assert len(list_approved(scen_dir, source_index=2, difficulty="basic")) == 1
        assert len(list_approved(scen_dir, scope_level="Paramedic")) == 0

    def test_skips_template(self, scen_dir):
        from ems.scenarios import list_approved
        (scen_dir / "_template.md").write_text(
            "---\ntype: scenario\nstatus: approved\nlabeled_by: x\n---\n", encoding="utf-8"
        )
        assert list_approved(scen_dir) == []
