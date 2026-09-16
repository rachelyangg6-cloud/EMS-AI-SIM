"""
Unit tests for Phase 2 ingest pipeline.
Fully offline — the LLM is always mocked/injected, no Ollama or network.
"""
import json
import shutil
from pathlib import Path

import pytest

from ems import paths
from ems.json_utils import parse_llm_json


# ── shared wiki-in-tmp fixture ───────────────────────────────────────────────

@pytest.fixture
def wiki_env(tmp_path, monkeypatch):
    """A throwaway wiki rooted at tmp_path (PROD env), seeded with the real
    page templates and a minimal vocabulary."""
    for sub in ("protocols", "conditions", "medications", "procedures", "lookups"):
        (tmp_path / "wiki" / sub).mkdir(parents=True)
        template = paths.REPO_ROOT / "wiki" / sub / "_template.md"
        if template.exists():
            shutil.copy(template, tmp_path / "wiki" / sub / "_template.md")
    (tmp_path / "raw").mkdir()
    (tmp_path / "system").mkdir()

    vocab = {
        "conditions": ["anaphylaxis", "crush-syndrome"],
        "medications": ["epinephrine", "sodium-bicarbonate"],
        "procedures": ["iv-access"],
        "scope_levels": ["EMT-B", "AEMT", "Paramedic"],
        "body_systems": ["cardiac"],
        "agencies": [],
    }
    (tmp_path / "system" / "source-vocabulary.json").write_text(
        json.dumps(vocab), encoding="utf-8"
    )

    monkeypatch.setenv("EMS_WIKI_ENV", "PROD")
    monkeypatch.setenv("EMS_WIKI_PROD_PATH", str(tmp_path))
    return tmp_path


SUMMARY_JSON = json.dumps({
    "clinical_summary": "Field management of anaphylaxis with epinephrine.",
    "conditions_addressed": ["anaphylaxis", "not-a-real-condition"],
    "red_flags_mentioned": ["stridor", "hypotension"],
    "medications_referenced": ["epinephrine"],
    "scope_level": "Paramedic",
    "sop_id": "SOP-TEST-01",
    "effective_date": "2025-01-01",
})

ROUTE_JSON = json.dumps({
    "target_pages": ["anaphylaxis-protocol", "anaphylaxis-protocol"],
    "sections": ["Steps", "Not A Real Section"],
    "reason": "Source is an anaphylaxis SOP.",
})

SECTION_TEXT = "## Steps\nAdminister [[epinephrine]] 0.3 mg IM. [SOP-TEST-01:Steps]"


def smart_llm(prompt: str, system: str = "", model=None) -> str:
    """Route vs. patch dispatcher for tests."""
    if "routing an EMS source document" in prompt:
        return ROUTE_JSON
    if "updating a section" in prompt:
        return SECTION_TEXT
    return SUMMARY_JSON


# ── json_utils ───────────────────────────────────────────────────────────────

class TestJsonUtils:
    def test_plain_json(self):
        assert parse_llm_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_embedded_json(self):
        assert parse_llm_json('Here you go:\n{"a": 1}\nThanks') == {"a": 1}

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            parse_llm_json("no object here")


# ── extraction ───────────────────────────────────────────────────────────────

class TestExtraction:
    def test_text_file_read(self, tmp_path):
        from ems.extraction import extract_source_text
        p = tmp_path / "sop.md"
        p.write_text("Anaphylaxis protocol body.", encoding="utf-8")
        assert extract_source_text(p) == "Anaphylaxis protocol body."

    def test_max_chars_cap(self, tmp_path):
        from ems.extraction import extract_source_text
        p = tmp_path / "big.txt"
        p.write_text("x" * 100, encoding="utf-8")
        assert len(extract_source_text(p, max_chars=10)) == 10


# ── source_creator ───────────────────────────────────────────────────────────

class TestSourceCreator:
    def test_creates_raw_note_status_new(self, wiki_env):
        from ems.source_creator import create_source
        src = wiki_env / "input.txt"
        src.write_text("Give epinephrine for anaphylaxis.", encoding="utf-8")

        meta = create_source(src, sop_id="SOP-TEST-01", effective_date="2025-01-01")
        assert meta.status == "new"

        from ems.frontmatter import read_page
        fm, body = read_page(meta.path)
        assert fm["status"] == "new"
        assert fm["sop_id"] == "SOP-TEST-01"
        assert fm["filename"] == "input.txt"
        assert "epinephrine" in body

    def test_slugify(self):
        from ems.source_creator import slugify
        assert slugify("SOP 2024 CR_01.pdf") == "sop-2024-cr-01-pdf"
        assert slugify("!!!") == "source"


# ── summarizer ───────────────────────────────────────────────────────────────

class TestSummarizer:
    def test_parses_and_filters_slugs(self, wiki_env, monkeypatch):
        import ems.source_summarizer as mod
        monkeypatch.setattr(mod, "call_llm", lambda *a, **k: SUMMARY_JSON)
        from ems.vocabulary import load_vocabulary

        summary = mod.summarize("body", load_vocabulary())
        assert summary.conditions_addressed == ("anaphylaxis",)  # bogus slug dropped
        assert summary.medications_referenced == ("epinephrine",)
        assert summary.scope_level == "Paramedic"
        assert summary.sop_id == "SOP-TEST-01"

    def test_invalid_scope_defaults_emtb(self, wiki_env, monkeypatch):
        import ems.source_summarizer as mod
        bad = json.dumps({"clinical_summary": "x", "scope_level": "Wizard"})
        monkeypatch.setattr(mod, "call_llm", lambda *a, **k: bad)
        from ems.vocabulary import load_vocabulary
        assert mod.summarize("body", load_vocabulary()).scope_level == "EMT-B"


# ── router ───────────────────────────────────────────────────────────────────

class TestRouter:
    def test_drops_invalid_sections(self, wiki_env):
        from ems.page_router import route
        from ems.models import SourceSummary
        from ems.vocabulary import load_vocabulary

        summary = SourceSummary(
            clinical_summary="x",
            conditions_addressed=("anaphylaxis",),
            red_flags_mentioned=(),
            medications_referenced=("epinephrine",),
            scope_level="Paramedic",
            sop_id="SOP-TEST-01",
        )
        result = route(summary, load_vocabulary(), llm=smart_llm)
        assert result.target_pages == ("anaphylaxis-protocol",)  # invalid pair dropped
        assert result.sections == ("Steps",)
        assert len(result.target_pages) == len(result.sections)


# ── page_updater ─────────────────────────────────────────────────────────────

class TestPageUpdater:
    def test_strip_h2(self):
        from ems.page_updater import strip_h2
        assert strip_h2("## Steps\nDo the thing.") == "Do the thing."

    def test_populate_relationships_protocol(self):
        from ems.page_updater import populate_relationships
        from ems.models import SourceSummary
        fm = {"treats_conditions": [], "medications": ["epinephrine"]}
        summary = SourceSummary(
            clinical_summary="x",
            conditions_addressed=("anaphylaxis",),
            red_flags_mentioned=(),
            medications_referenced=("epinephrine",),  # already present, no dup
            scope_level="Paramedic",
        )
        populate_relationships(fm, "protocol", summary)
        assert fm["treats_conditions"] == ["anaphylaxis"]
        assert fm["medications"] == ["epinephrine"]

    def test_create_page_from_template(self, wiki_env):
        from ems.page_updater import create_page_from_template
        from ems.frontmatter import read_page
        path = create_page_from_template("anaphylaxis-protocol", "protocol")
        fm, _ = read_page(path)
        assert fm["type"] == "protocol"
        assert fm["title"] == "Anaphylaxis Protocol"

    def test_update_page_end_to_end(self, wiki_env):
        from ems.page_updater import update_page
        from ems.frontmatter import read_page
        from ems.markdown import get_section
        from ems.models import SourceSummary
        from ems.vocabulary import load_vocabulary

        summary = SourceSummary(
            clinical_summary="Anaphylaxis mgmt.",
            conditions_addressed=("anaphylaxis",),
            red_flags_mentioned=("stridor",),
            medications_referenced=("epinephrine",),
            scope_level="Paramedic",
            sop_id="SOP-TEST-01",
            effective_date="2025-01-01",
        )
        path = update_page(
            "anaphylaxis-protocol", ["Steps"], summary, "source text",
            load_vocabulary(), llm=smart_llm,
        )
        fm, body = read_page(path)
        assert fm["treats_conditions"] == ["anaphylaxis"]
        assert fm["medications"] == ["epinephrine"]
        assert fm["scope_level"] == "Paramedic"
        assert fm["effective_date"] == "2025-01-01"
        assert fm["status"] == "active"
        assert "epinephrine" in fm["linked_pages"]
        assert "0.3 mg IM" in get_section(body, "Steps")
        assert "## " not in get_section(body, "Steps")  # H2 stripped

    def test_apply_agent_update_no_llm(self, wiki_env):
        # Skill path: agent-written section content, no LLM involved.
        from ems.page_updater import apply_agent_update, find_page
        from ems.frontmatter import read_page
        from ems.markdown import get_section, extract_wikilinks
        from ems.models import SourceSummary
        from ems.vocabulary import load_vocabulary

        summary = SourceSummary(
            clinical_summary="Anaphylaxis recognition and management.",
            conditions_addressed=("anaphylaxis",),
            red_flags_mentioned=("stridor",),
            medications_referenced=("epinephrine",),
            scope_level="EMT-B",
        )
        path = apply_agent_update(
            "anaphylaxis",
            {"Recognition": "Hives + wheeze after exposure. [SRC-1:p42] See [[epinephrine]]."},
            summary,
            load_vocabulary(),
            source_kind="resource",
            source_index=1,
        )
        assert path is not None
        fm, body = read_page(path)
        assert fm["type"] == "condition"
        assert fm["scope_level"] == "EMT-B"
        assert fm["status"] == "active"
        assert "stridor" in fm["red_flags"]
        assert "epinephrine" in fm["linked_pages"]
        assert "SRC-1:p42" in get_section(body, "Recognition")

    def test_apply_agent_update_skips_protocol_for_resource(self, wiki_env):
        from ems.page_updater import apply_agent_update
        from ems.models import SourceSummary
        from ems.vocabulary import load_vocabulary
        summary = SourceSummary(
            clinical_summary="x", conditions_addressed=(), red_flags_mentioned=(),
            medications_referenced=(), scope_level="EMT-B",
        )
        result = apply_agent_update(
            "anaphylaxis-protocol", {"Steps": "..."}, summary,
            load_vocabulary(), source_kind="resource", source_index=1,
        )
        assert result is None

    def test_supersede_prior_versions(self, wiki_env):
        from ems.page_updater import create_page_from_template, supersede_prior_versions
        from ems.frontmatter import read_page, write_frontmatter

        old = create_page_from_template("anaphylaxis-protocol-v1", "protocol")
        fm, _ = read_page(old)
        fm["sop_id"], fm["status"] = "SOP-TEST-01", "active"
        write_frontmatter(old, fm)

        new = create_page_from_template("anaphylaxis-protocol-v2", "protocol")
        fm, _ = read_page(new)
        fm["sop_id"], fm["status"] = "SOP-TEST-01", "active"
        write_frontmatter(new, fm)

        superseded = supersede_prior_versions(new, "SOP-TEST-01")
        assert superseded == ["anaphylaxis-protocol-v1"]
        assert read_page(old)[0]["status"] == "superseded"
        assert read_page(new)[0]["supersedes"] == "SOP-TEST-01"


# ── index_log ────────────────────────────────────────────────────────────────

class TestIndexLog:
    def test_append_log_and_regenerate_index(self, wiki_env):
        from ems.page_updater import create_page_from_template
        from ems.index_log import append_log, regenerate_index, log_path, index_path

        create_page_from_template("anaphylaxis-protocol", "protocol")
        append_log("anaphylaxis-protocol → updated")
        regenerate_index()

        assert "anaphylaxis-protocol" in log_path().read_text()
        index = index_path().read_text()
        assert "# Wiki Index" in index
        assert "anaphylaxis-protocol" in index


# ── ingest orchestration (the plan's two critical assertions) ────────────────

class TestIngest:
    def _make_source(self, wiki_env):
        from ems.source_creator import create_source
        src = wiki_env / "anaphylaxis-sop.txt"
        src.write_text("Anaphylaxis: give epinephrine.", encoding="utf-8")
        create_source(src, sop_id="SOP-TEST-01", effective_date="2025-01-01")

    def test_full_ingest_populates_relationships_and_scope(self, wiki_env, monkeypatch):
        import ems.source_summarizer as summ
        monkeypatch.setattr(summ, "call_llm", lambda *a, **k: SUMMARY_JSON)
        self._make_source(wiki_env)

        from ems.ingest import ingest
        results = ingest(llm=smart_llm)

        assert len(results) == 1
        assert results[0].status == "ingested"

        from ems.page_updater import find_page
        from ems.frontmatter import read_page
        page = find_page("anaphylaxis-protocol")
        assert page is not None
        fm, _ = read_page(page)
        # (a) frontmatter treats_conditions populated after ingest
        assert "anaphylaxis" in fm["treats_conditions"]
        # (b) every ingested page has a valid scope_level
        from ems.config import SCOPE_LEVELS
        assert fm["scope_level"] in SCOPE_LEVELS

        # source flipped to ingested; log + index written
        raw_fm, _ = read_page(wiki_env / "raw" / "anaphylaxis-sop.md")
        assert raw_fm["status"] == "ingested"
        assert (wiki_env / "wiki" / "log.md").exists()
        assert (wiki_env / "wiki" / "index.md").exists()

    def test_dry_run_writes_nothing(self, wiki_env, monkeypatch):
        import ems.source_summarizer as summ
        monkeypatch.setattr(summ, "call_llm", lambda *a, **k: SUMMARY_JSON)
        self._make_source(wiki_env)

        from ems.ingest import ingest
        results = ingest(dry_run=True, llm=smart_llm)
        assert results[0].routed_pages == ("anaphylaxis-protocol",)

        from ems.page_updater import find_page
        from ems.frontmatter import read_page
        assert find_page("anaphylaxis-protocol") is None  # no page written
        raw_fm, _ = read_page(wiki_env / "raw" / "anaphylaxis-sop.md")
        assert raw_fm["status"] == "new"  # source not flipped
