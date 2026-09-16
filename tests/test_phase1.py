"""
Unit tests for Phase 1 core infrastructure modules.
All tests run fully offline — no Ollama or network required.
LLM functions are tested via mocks.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ems import config
from ems.frontmatter import read_body, read_frontmatter, read_page, write_frontmatter
from ems.markdown import (
    extract_h2_headings,
    extract_wikilinks,
    get_section,
    replace_section,
)
from ems.models import PagePatch, RoutingResult, SourceMeta, SourceSummary
from ems.vocabulary import get_conditions, get_medications, load_vocabulary, save_vocabulary


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_protocol(tmp_path):
    """A valid protocol markdown file in a temp directory."""
    content = """\
---
type: protocol
title: Crush Syndrome Protocol
sop_id: SOP-2024-CR-01
scope_level: Paramedic
effective_date: '2024-03-01'
supersedes: ''
treats_conditions:
- crush-syndrome
medications:
- sodium-bicarbonate
linked_pages: []
status: active
---

## When it applies
Patient trapped for more than 20 minutes.

## Steps
1. Establish IV access.
2. Administer fluids per [[crush-syndrome]] protocol.

## Medications & doses
Sodium bicarbonate 1 mEq/kg IV per [SOP-2024-CR-01:Medications & doses].

## Scope boundaries
IV access and bicarb administration: [Paramedic only].

## Red flags
- Dark or cola-colored urine
- Worsening hyperkalemia signs

## Transport decision
Load and go to trauma center with renal capability.
"""
    p = tmp_path / "crush-syndrome-protocol.md"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def tmp_vocab(tmp_path):
    """A minimal vocabulary JSON file."""
    data = {
        "conditions": ["crush-syndrome", "anaphylaxis"],
        "medications": ["epinephrine", "sodium-bicarbonate"],
        "procedures": ["opqrst"],
        "scope_levels": ["EMT-B", "AEMT", "Paramedic"],
        "body_systems": ["cardiac", "renal"],
        "agencies": [],
    }
    p = tmp_path / "source-vocabulary.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


# ── config ───────────────────────────────────────────────────────────────────

class TestConfig:
    def test_scope_levels_tuple(self):
        assert isinstance(config.SCOPE_LEVELS, tuple)
        assert "EMT-B" in config.SCOPE_LEVELS
        assert "AEMT" in config.SCOPE_LEVELS
        assert "Paramedic" in config.SCOPE_LEVELS

    def test_valid_statuses(self):
        assert "active" in config.VALID_STATUSES
        assert "superseded" in config.VALID_STATUSES
        assert "draft" in config.VALID_STATUSES

    def test_dir_to_type_and_inverse(self):
        for directory, ptype in config.DIR_TO_TYPE.items():
            assert config.TYPE_TO_DIR[ptype] == directory

    def test_sections_by_page_type_covers_all_types(self):
        for ptype in config.DIR_TO_TYPE.values():
            assert ptype in config.SECTIONS_BY_PAGE_TYPE
            assert len(config.SECTIONS_BY_PAGE_TYPE[ptype]) > 0

    def test_relationship_rules_structure(self):
        for rule in config.RELATIONSHIP_RULES:
            assert "source_type" in rule
            assert "field" in rule
            assert "target_type" in rule
            assert "edges" in rule
            assert isinstance(rule["edges"], list)
            assert len(rule["edges"]) == 2


# ── paths ────────────────────────────────────────────────────────────────────

class TestPaths:
    def test_dev_env_returns_repo_root(self, monkeypatch):
        from ems import paths
        monkeypatch.delenv("EMS_WIKI_ENV", raising=False)
        root = paths.get_wiki_root()
        assert root == paths.REPO_ROOT

    def test_prod_env_requires_prod_path(self, monkeypatch):
        from ems import paths
        monkeypatch.setenv("EMS_WIKI_ENV", "PROD")
        monkeypatch.delenv("EMS_WIKI_PROD_PATH", raising=False)
        with pytest.raises(EnvironmentError, match="EMS_WIKI_PROD_PATH"):
            paths.get_wiki_root()

    def test_prod_env_with_path(self, monkeypatch, tmp_path):
        from ems import paths
        monkeypatch.setenv("EMS_WIKI_ENV", "PROD")
        monkeypatch.setenv("EMS_WIKI_PROD_PATH", str(tmp_path))
        assert paths.get_wiki_root() == tmp_path

    def test_wiki_subdir_valid_type(self):
        from ems import paths
        p = paths.wiki_subdir("protocol")
        assert p.name == "protocols"

    def test_wiki_subdir_invalid_type(self):
        from ems import paths
        with pytest.raises(ValueError, match="Unknown page type"):
            paths.wiki_subdir("diagnosis")

    def test_path_helpers_return_paths(self):
        from ems import paths
        assert isinstance(paths.raw_dir(), Path)
        assert isinstance(paths.wiki_dir(), Path)
        assert isinstance(paths.system_dir(), Path)
        assert isinstance(paths.vocabulary_path(), Path)
        assert isinstance(paths.embeddings_path(), Path)
        assert isinstance(paths.graph_path(), Path)


# ── frontmatter ──────────────────────────────────────────────────────────────

class TestFrontmatter:
    def test_read_frontmatter(self, tmp_protocol):
        fm = read_frontmatter(tmp_protocol)
        assert fm["type"] == "protocol"
        assert fm["sop_id"] == "SOP-2024-CR-01"
        assert fm["scope_level"] == "Paramedic"

    def test_read_body_excludes_frontmatter(self, tmp_protocol):
        body = read_body(tmp_protocol)
        assert "---" not in body.split("\n")[0]
        assert "## When it applies" in body

    def test_read_page_returns_tuple(self, tmp_protocol):
        fm, body = read_page(tmp_protocol)
        assert isinstance(fm, dict)
        assert isinstance(body, str)
        assert fm["title"] == "Crush Syndrome Protocol"

    def test_write_frontmatter_preserves_body(self, tmp_protocol):
        fm, body_before = read_page(tmp_protocol)
        fm["status"] = "superseded"
        write_frontmatter(tmp_protocol, fm)
        fm2, body_after = read_page(tmp_protocol)
        assert fm2["status"] == "superseded"
        assert body_after == body_before

    def test_write_frontmatter_round_trip(self, tmp_protocol):
        fm = read_frontmatter(tmp_protocol)
        original_sop_id = fm["sop_id"]
        fm["title"] = "Updated Title"
        write_frontmatter(tmp_protocol, fm)
        fm2 = read_frontmatter(tmp_protocol)
        assert fm2["title"] == "Updated Title"
        assert fm2["sop_id"] == original_sop_id

    def test_read_page_no_frontmatter(self, tmp_path):
        p = tmp_path / "bare.md"
        p.write_text("# Just a heading\n\nSome body.", encoding="utf-8")
        fm, body = read_page(p)
        assert fm == {}
        assert "Just a heading" in body

    def test_read_page_empty_frontmatter(self, tmp_path):
        p = tmp_path / "empty-fm.md"
        p.write_text("---\n---\n\nBody here.", encoding="utf-8")
        fm, body = read_page(p)
        assert fm == {}
        assert "Body here" in body


# ── markdown ─────────────────────────────────────────────────────────────────

class TestMarkdown:
    BODY = """\

## When it applies
Patient trapped > 20 minutes.

## Steps
1. Start IV.
2. Monitor ECG.

## Medications & doses
Bicarb 1 mEq/kg IV.

## Scope boundaries
IV access: [Paramedic only].

## Red flags
- Cola-colored urine.

## Transport decision
Trauma center.
"""

    def test_get_section_found(self):
        content = get_section(self.BODY, "Steps")
        assert "Start IV" in content

    def test_get_section_not_found(self):
        assert get_section(self.BODY, "Nonexistent Section") is None

    def test_get_section_last_section(self):
        content = get_section(self.BODY, "Transport decision")
        assert "Trauma center" in content

    def test_replace_section_updates_content(self):
        new_body = replace_section(self.BODY, "Steps", "1. New step one.\n2. New step two.")
        assert "New step one" in get_section(new_body, "Steps")
        assert "Start IV" not in new_body

    def test_replace_section_preserves_other_sections(self):
        new_body = replace_section(self.BODY, "Steps", "Replaced.")
        assert "Cola-colored urine" in get_section(new_body, "Red flags")
        assert "Trauma center" in get_section(new_body, "Transport decision")

    def test_replace_section_missing_heading_noop(self):
        result = replace_section(self.BODY, "Does Not Exist", "content")
        assert result == self.BODY

    def test_extract_wikilinks(self):
        body = "See [[crush-syndrome]] and [[epinephrine]] for details."
        assert extract_wikilinks(body) == ["crush-syndrome", "epinephrine"]

    def test_extract_wikilinks_none(self):
        assert extract_wikilinks("No links here.") == []

    def test_extract_wikilinks_duplicates_kept(self):
        body = "[[crush-syndrome]] and again [[crush-syndrome]]"
        assert extract_wikilinks(body) == ["crush-syndrome", "crush-syndrome"]

    def test_extract_h2_headings_ordered(self):
        headings = extract_h2_headings(self.BODY)
        assert headings == [
            "When it applies",
            "Steps",
            "Medications & doses",
            "Scope boundaries",
            "Red flags",
            "Transport decision",
        ]

    def test_extract_h2_headings_empty_body(self):
        assert extract_h2_headings("") == []


# ── models ───────────────────────────────────────────────────────────────────

class TestModels:
    def test_source_meta_frozen(self):
        sm = SourceMeta(path=Path("/raw/sop.pdf"), status="new", filename="sop.pdf")
        with pytest.raises(Exception):
            sm.status = "ingested"  # type: ignore[misc]

    def test_source_summary_frozen(self):
        ss = SourceSummary(
            clinical_summary="Crush syndrome management.",
            conditions_addressed=("crush-syndrome",),
            red_flags_mentioned=("dark urine",),
            medications_referenced=("sodium-bicarbonate",),
            scope_level="Paramedic",
            sop_id="SOP-2024-CR-01",
            effective_date="2024-03-01",
        )
        assert ss.scope_level == "Paramedic"
        with pytest.raises(Exception):
            ss.scope_level = "EMT-B"  # type: ignore[misc]

    def test_source_summary_optional_fields_default_none(self):
        ss = SourceSummary(
            clinical_summary="Test",
            conditions_addressed=(),
            red_flags_mentioned=(),
            medications_referenced=(),
            scope_level="EMT-B",
        )
        assert ss.sop_id is None
        assert ss.effective_date is None

    def test_routing_result_frozen(self):
        rr = RoutingResult(
            target_pages=("crush-syndrome-protocol",),
            sections=("Steps",),
            reason="Source is a crush syndrome SOP.",
        )
        assert len(rr.target_pages) == len(rr.sections)
        with pytest.raises(Exception):
            rr.reason = "changed"  # type: ignore[misc]

    def test_page_patch_frozen(self):
        pp = PagePatch(
            page_slug="crush-syndrome-protocol",
            page_type="protocol",
            section_heading="Steps",
            new_content="1. New step.",
        )
        assert pp.page_type == "protocol"
        with pytest.raises(Exception):
            pp.new_content = "mutated"  # type: ignore[misc]


# ── vocabulary ───────────────────────────────────────────────────────────────

class TestVocabulary:
    def test_load_vocabulary(self, tmp_vocab):
        vocab = load_vocabulary(tmp_vocab)
        assert "conditions" in vocab
        assert "medications" in vocab

    def test_get_conditions(self, tmp_vocab):
        conditions = get_conditions(tmp_vocab)
        assert isinstance(conditions, list)
        assert "crush-syndrome" in conditions

    def test_get_medications(self, tmp_vocab):
        medications = get_medications(tmp_vocab)
        assert isinstance(medications, list)
        assert "epinephrine" in medications

    def test_save_vocabulary_round_trip(self, tmp_vocab):
        vocab = load_vocabulary(tmp_vocab)
        vocab["conditions"].append("hypothermia")
        save_vocabulary(vocab, tmp_vocab)
        reloaded = load_vocabulary(tmp_vocab)
        assert "hypothermia" in reloaded["conditions"]

    def test_save_vocabulary_preserves_other_keys(self, tmp_vocab):
        vocab = load_vocabulary(tmp_vocab)
        vocab["medications"].append("ketamine")
        save_vocabulary(vocab, tmp_vocab)
        reloaded = load_vocabulary(tmp_vocab)
        assert "epinephrine" in reloaded["medications"]
        assert "ketamine" in reloaded["medications"]


# ── llm (mocked) ─────────────────────────────────────────────────────────────

def _mock_anthropic(text: str = "test response"):
    """A stand-in for the ems.llm.anthropic module backed by a mock client."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    mock_response = MagicMock()
    mock_response.content = [block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    mock_module = MagicMock()
    mock_module.Anthropic.return_value = mock_client
    mock_module.NOT_GIVEN = None
    return mock_module, mock_client


class TestLLMMocked:
    def test_call_llm_sends_user_message(self):
        mock_module, mock_client = _mock_anthropic("test response")
        with patch("ems.llm.anthropic", mock_module):
            from ems.llm import call_llm
            result = call_llm("What is crush syndrome?")

        assert result == "test response"
        messages = mock_client.messages.create.call_args.kwargs["messages"]
        assert messages[-1]["role"] == "user"
        assert "crush syndrome" in messages[-1]["content"]

    def test_call_llm_includes_system_message(self):
        mock_module, mock_client = _mock_anthropic("ok")
        with patch("ems.llm.anthropic", mock_module):
            from ems.llm import call_llm
            call_llm("prompt", system="You are a medic.")

        kwargs = mock_client.messages.create.call_args.kwargs
        assert "medic" in kwargs["system"]

    def test_call_llm_uses_configured_model(self):
        mock_module, mock_client = _mock_anthropic("ok")
        with patch("ems.llm.anthropic", mock_module):
            from ems.llm import call_llm
            call_llm("prompt")

        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-opus-4-8"
        # Opus 4.8 rejects sampling params — call_llm must not send temperature.
        assert "temperature" not in kwargs
