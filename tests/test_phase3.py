"""
Unit tests for Phase 3: embeddings, knowledge graph, and query.
Fully offline — the LLM and the embedding model are always mocked/injected.
"""
import json
import shutil

import pytest

from ems import paths


@pytest.fixture
def wiki_env(tmp_path, monkeypatch):
    """Throwaway wiki (PROD env) seeded with page templates and a vocabulary."""
    for sub in ("protocols", "conditions", "medications", "procedures", "lookups"):
        (tmp_path / "wiki" / sub).mkdir(parents=True)
        template = paths.REPO_ROOT / "wiki" / sub / "_template.md"
        if template.exists():
            shutil.copy(template, tmp_path / "wiki" / sub / "_template.md")
    (tmp_path / "raw").mkdir()
    (tmp_path / "system").mkdir()

    vocab = {
        "conditions": ["anaphylaxis"],
        "medications": ["epinephrine"],
        "procedures": ["iv-access", "spinal-motion-restriction"],
        "scope_levels": ["EMT-B", "AEMT", "Paramedic"],
        "body_systems": ["cardiac"],
        "agencies": [],
    }
    (tmp_path / "system" / "source-vocabulary.json").write_text(json.dumps(vocab))

    monkeypatch.setenv("EMS_WIKI_ENV", "PROD")
    monkeypatch.setenv("EMS_WIKI_PROD_PATH", str(tmp_path))
    return tmp_path


def _summary(scope="EMT-B", **kw):
    from ems.models import SourceSummary
    base = dict(
        clinical_summary="x", conditions_addressed=(), red_flags_mentioned=(),
        medications_referenced=(), scope_level=scope,
    )
    base.update(kw)
    return SourceSummary(**base)


def _make_page(vocab_load, slug, sections, scope="EMT-B",
               conditions=(), source_kind="resource", source_index=3):
    from ems.page_updater import apply_agent_update
    return apply_agent_update(
        slug, sections,
        _summary(scope=scope, conditions_addressed=conditions),
        vocab_load, source_kind=source_kind, source_index=source_index,
    )


# ── keyword search + scope filter ────────────────────────────────────────────

class TestKeywordAndScope:
    def test_keyword_ranks_title_matches(self, wiki_env):
        from ems.vocabulary import load_vocabulary
        from ems.query import load_pages, keyword_search
        _make_page(load_vocabulary(), "iv-access",
                   {"Steps": "Insert the catheter. [SRC-3:p10]"})
        hits = keyword_search("iv access", load_pages())
        assert hits and hits[0][0].slug == "iv-access"
        assert hits[0][1] >= 3.0  # title hit weighted 3x

    def test_scope_filter_withholds_above_scope(self, wiki_env):
        from ems.vocabulary import load_vocabulary
        from ems.query import load_pages, scope_filter
        _make_page(load_vocabulary(), "iv-access",
                   {"Steps": "Advanced airway. [SRC-3:p10]"}, scope="Paramedic")
        emtb = scope_filter(load_pages(), "EMT-B")
        assert all(p.scope_level != "Paramedic" for p in emtb)
        assert "iv-access" not in {p.slug for p in emtb}
        # a Paramedic sees it
        assert "iv-access" in {p.slug for p in scope_filter(load_pages(), "Paramedic")}

    def test_age_group_metadata_outranks_body_mention(self):
        """An age_group tag (2x metadata tier) beats a body-only mention (1x)."""
        from ems.query import Page, keyword_search
        tagged = Page(slug="a", type="condition", title="", scope_level="EMT-B",
                      status="active", body="dosing guidance",
                      frontmatter={"age_group": ["pediatric"]})
        body_only = Page(slug="b", type="condition", title="", scope_level="EMT-B",
                         status="active", body="pediatric dosing guidance",
                         frontmatter={})
        hits = keyword_search("pediatric", [tagged, body_only])
        assert hits[0][0].slug == "a"


# ── citation verification ────────────────────────────────────────────────────

class TestCitationVerification:
    def test_rejects_fabricated_citation(self):
        from ems.query import verify_citations
        context = "Restrict the spine. [SRC-3:p73]"
        answer = "Apply a collar. [SRC-3:p73] Then sedate. [SRC-9:p99]"
        _, unverified = verify_citations(answer, context)
        assert unverified == ["SRC-9:p99"]

    def test_scope_tags_are_not_citations(self):
        from ems.query import verify_citations
        _, unverified = verify_citations(
            "Do X. [SRC-3:p73] [OUT OF SCOPE for EMT-B] [Paramedic only]",
            "Do X. [SRC-3:p73]",
        )
        assert unverified == []


# ── answer_query end-to-end (LLM mocked) ─────────────────────────────────────

class TestAnswerQuery:
    def _raising_embed(self, *a, **k):
        raise AssertionError("vector search must not run at small corpus")

    def test_answer_uses_keyword_only_at_small_corpus(self, wiki_env):
        from ems.vocabulary import load_vocabulary
        from ems.query import answer_query
        _make_page(load_vocabulary(), "spinal-motion-restriction",
                   {"When to use": "Suspected spine injury. [SRC-3:p73]"})

        called = {}
        def fake_llm(prompt, system="", model=None):
            called["ctx"] = prompt
            return "Restrict spinal motion. [SRC-3:p73]"

        result = answer_query(
            "spinal motion restriction", scope_level="EMT-B",
            llm=fake_llm, embed=self._raising_embed,  # would raise if vector ran
        )
        assert result.mode == "keyword"
        assert result.pages_used == ("spinal-motion-restriction",)
        assert result.unverified_citations == ()
        assert "SRC-3:p73" in result.answer

    def test_out_of_corpus_refuses_without_llm(self, wiki_env):
        from ems.vocabulary import load_vocabulary
        from ems.query import answer_query
        _make_page(load_vocabulary(), "spinal-motion-restriction",
                   {"When to use": "Suspected spine injury. [SRC-3:p73]"})

        def boom_llm(*a, **k):
            raise AssertionError("LLM must not be called on a refused query")

        result = answer_query("epinephrine cardiac arrest dose",
                              scope_level="EMT-B", llm=boom_llm,
                              embed=self._raising_embed)
        assert result.mode == "refused"
        assert result.answer == "NOT IN PROVIDED PROTOCOLS"

    def test_save_writes_lookup(self, wiki_env):
        from ems.vocabulary import load_vocabulary
        from ems.query import answer_query, lookups_dir
        _make_page(load_vocabulary(), "iv-access",
                   {"Steps": "Insert catheter. [SRC-3:p10]"})
        answer_query("iv access", scope_level="EMT-B",
                     llm=lambda *a, **k: "Insert. [SRC-3:p10]",
                     embed=self._raising_embed, save=True)
        saved = list(lookups_dir().glob("*.md"))
        assert len(saved) == 1
        assert "iv access" in saved[0].read_text()


# ── embeddings (embed fn injected — no real model load) ──────────────────────

class TestEmbeddings:
    def _fake_embed(self, text):
        # deterministic toy vector: counts of a few marker words
        t = text.lower()
        return [float(t.count("spine")), float(t.count("airway")), 1.0]

    def test_build_and_vector_search(self, wiki_env):
        from ems.vocabulary import load_vocabulary
        from ems import embeddings
        _make_page(load_vocabulary(), "spinal-motion-restriction",
                   {"When to use": "Protect the spine spine spine. [SRC-3:p73]"})
        _make_page(load_vocabulary(), "iv-access",
                   {"Steps": "Manage the airway airway. [SRC-3:p10]"})

        assert not embeddings.index_exists()
        index = embeddings.build_embedding_index(force=True, embed=self._fake_embed)
        assert embeddings.index_exists()
        assert len(index["sections"]) == 2

        hits = embeddings.vector_search("spine", embed=self._fake_embed)
        assert hits[0][1] == "spinal-motion-restriction"

    def test_embed_sections_noop_without_index(self, wiki_env):
        from ems.vocabulary import load_vocabulary
        from ems import embeddings
        path = _make_page(load_vocabulary(), "iv-access",
                          {"Steps": "Insert. [SRC-3:p10]"})
        # no index built yet → incremental embed is a no-op (keeps ingest offline)
        embeddings.embed_sections(path, embed=self._fake_embed)
        assert not embeddings.index_exists()


# ── graph ────────────────────────────────────────────────────────────────────

class TestGraph:
    def test_build_graph_edges_from_frontmatter(self, wiki_env):
        from ems.vocabulary import load_vocabulary
        from ems import graph
        # a condition page that links to a procedure via wikilink
        _make_page(load_vocabulary(), "anaphylaxis",
                   {"Field management": "See [[iv-access]]. [SRC-3:p5]"},
                   conditions=("anaphylaxis",))
        _make_page(load_vocabulary(), "iv-access",
                   {"Steps": "Insert catheter. [SRC-3:p10]"})

        g = graph.build_graph()
        assert graph.graph_path().exists()
        assert graph.graph_stats(g)["nodes"] == 2
        assert "iv-access" in graph.get_related(g, "anaphylaxis")

    def test_get_or_build_graph_loads_existing(self, wiki_env):
        from ems.vocabulary import load_vocabulary
        from ems import graph
        _make_page(load_vocabulary(), "iv-access",
                   {"Steps": "Insert. [SRC-3:p10]"})
        graph.build_graph()
        assert graph.get_or_build_graph()["nodes"] == {"iv-access": "procedure"}
