"""Tests for the corpus counts behind the Features page.

Two halves, deliberately.

**Exact numbers are asserted against a fixture corpus only.** Asserting 553 or
325 against the real wiki would turn every `process-source` run into a red
suite, which trains people to edit the assertion rather than read it.

**The real corpus is checked for invariants** — sums that must agree, tags that
must be in the vocabulary. Those survive the corpus growing and are what
actually catches a broken counter.
"""
import subprocess
import sys
import textwrap

import pytest

from ems import corpus_stats as cs
from ems.scenarios import list_approved
from ems.tags import valid_tags


def _page(path, body="Text with [SRC-1:p10].", **fm):
    fields = "\n".join(f"{k}: {v}" for k, v in fm.items())
    path.write_text(f"---\n{fields}\n---\n\n{body}\n", encoding="utf-8")


@pytest.fixture
def corpus(tmp_path):
    """A small wiki with one of everything the counters distinguish."""
    wiki = tmp_path / "wiki"
    for sub in ("conditions", "procedures", "medications", "protocols", "scenarios"):
        (wiki / sub).mkdir(parents=True)
    (wiki / "scenarios" / "generated").mkdir()

    # A template must never be counted, in any directory.
    _page(wiki / "conditions" / "_template.md", type="condition")
    _page(wiki / "conditions" / "asthma.md", "See [SRC-1:p10] and [SRC-1:p10].",
          type="condition", age_group="[adult]")
    _page(wiki / "conditions" / "shock.md", "See [SRC-2:p20].",
          type="condition", age_group="[adult, pediatric]")
    _page(wiki / "procedures" / "bvm.md", "No reference here.", type="procedure")
    _page(wiki / "medications" / "oxygen.md", "See [SRC-2:p20].", type="medication")

    cases = wiki / "scenarios"
    _page(cases / "_template.md", type="scenario")
    _page(cases / "src1-s01.md", type="scenario", status="approved", labeled_by="ry",
          kind="patient-care", source_index=1, age_group="adult", corrected="true",
          tags="[airway and breathing]", citations="['[SRC-1:p10]']")
    _page(cases / "src1-s02.md", type="scenario", status="approved", labeled_by="ry",
          kind="provider-safety", source_index=1, age_group="adult",
          tags="[EMT well-being]", citations="['[SRC-3:p30]']")
    _page(cases / "src2-s01.md", type="scenario", status="rejected", labeled_by="ry",
          kind="patient-care", source_index=2)
    _page(cases / "src2-s02.md", type="scenario", status="pending", labeled_by="",
          kind="patient-care", source_index=2)
    # Approved but unsigned: the case the `labeled_by` half of the rule exists for.
    _page(cases / "src2-s03.md", type="scenario", status="approved", labeled_by="",
          kind="patient-care", source_index=2)
    _page(cases / "generated" / "gen-01.md", type="scenario", status="pending", labeled_by="")

    system = tmp_path / "system"
    system.mkdir()
    (system / "generation-lessons.md").write_text(
        textwrap.dedent("""\
            # Lessons

            - First lesson.
            - Second lesson.
            """),
        encoding="utf-8",
    )
    return tmp_path


# ── against the fixture: exact numbers ───────────────────────────────────────

def test_counts_pages_by_type_and_skips_templates(corpus):
    pages = cs.corpus_stats(corpus / "wiki", corpus / "system")["pages"]
    assert pages["by_type"] == {
        "condition": 2, "medication": 1, "procedure": 1, "protocol": 0,
    }
    assert pages["total"] == 4


def test_an_empty_page_type_reports_zero_rather_than_vanishing(corpus):
    """`wiki/protocols/` is template-only today; the slot should still show."""
    pages = cs.corpus_stats(corpus / "wiki", corpus / "system")["pages"]
    assert pages["by_type"]["protocol"] == 0


def test_only_approved_and_signed_counts_as_expertise_marked(corpus):
    cases = cs.corpus_stats(corpus / "wiki", corpus / "system")["scenarios"]
    # src2-s03 is `status: approved` with an empty `labeled_by`.
    assert cases["by_status"]["approved"] == 3
    assert cases["expertise_marked"] == 2


def test_reviewed_counts_every_ruling_including_the_rejections(corpus):
    """Review that never rejects is a formality; the count must show both."""
    cases = cs.corpus_stats(corpus / "wiki", corpus / "system")["scenarios"]
    # src1-s01, src1-s02, src2-s01 (rejected) and src2-s03 (approved, unsigned has
    # no labeled_by so is not reviewed) — three carry a reviewer's name.
    assert cases["reviewed"] == 3
    assert cases["expertise_marked"] == 2


def test_drafts_in_quarantine_are_counted_but_never_approved(corpus):
    cases = cs.corpus_stats(corpus / "wiki", corpus / "system")["scenarios"]
    assert cases["total"] == 6
    assert cases["by_status"]["pending"] == 2


def test_histograms_describe_the_vetted_corpus_only(corpus):
    """A rejected case must not appear in the topic or kind charts."""
    stats = cs.corpus_stats(corpus / "wiki", corpus / "system")
    assert stats["scenarios"]["by_kind"] == {"patient-care": 1, "provider-safety": 1}
    assert stats["topics"]["by_topic"] == {"airway and breathing": 1, "EMT well-being": 1}
    assert stats["sources"]["by_source"] == {"1": 2}


def test_distinct_citations_are_not_occurrences(corpus):
    """asthma.md cites the same page twice; that is one reference, seen twice."""
    cites = cs.corpus_stats(corpus / "wiki", corpus / "system")["citations"]
    assert cites["occurrences"] == 4          # p10 twice, p20 in two pages
    assert cites["pages_distinct"] == 2       # p10, p20
    assert cites["scenarios_distinct"] == 2   # p10, p30
    assert cites["distinct"] == 3             # the union: p10, p20, p30
    assert cites["sources_cited"] == 3


def test_uncited_pages_lower_the_cited_share(corpus):
    cites = cs.corpus_stats(corpus / "wiki", corpus / "system")["citations"]
    assert cites["pages_total"] == 4
    assert cites["pages_cited"] == 3          # bvm.md cites nothing


def test_lessons_are_counted_by_bullet(corpus):
    assert cs.corpus_stats(corpus / "wiki", corpus / "system")["lessons"] == 2


def test_difficulty_is_deliberately_absent(corpus):
    """171 approved scenarios carry no difficulty, so a histogram would lie.

    This test exists to be read when someone adds one back: fix the gap first.
    """
    assert "difficulty" not in repr(cs.corpus_stats(corpus / "wiki", corpus / "system"))


# ── against the real corpus: invariants only ─────────────────────────────────

@pytest.fixture(scope="module")
def real():
    return cs.corpus_stats()


def test_status_counts_account_for_every_scenario(real):
    assert sum(real["scenarios"]["by_status"].values()) == real["scenarios"]["total"]


def test_kind_histogram_covers_every_vetted_scenario(real):
    assert sum(real["scenarios"]["by_kind"].values()) == real["scenarios"]["expertise_marked"]


def test_expertise_marked_matches_what_the_simulator_deals(real):
    """The definition of record lives in `list_approved()`; this must not drift."""
    assert real["scenarios"]["expertise_marked"] == len(list_approved())


def test_every_topic_is_in_the_controlled_vocabulary(real):
    assert set(real["topics"]["by_topic"]) <= valid_tags()
    assert real["topics"]["used"] <= real["topics"]["vocabulary"]


def test_file_total_is_the_sum_of_its_parts(real):
    assert real["files"] == real["pages"]["total"] + real["scenarios"]["total"]
    assert real["pages"]["total"] == sum(real["pages"]["by_type"].values())


# ── guards ───────────────────────────────────────────────────────────────────

def test_cached_stats_is_memoized():
    cs.cached_stats.cache_clear()
    assert cs.cached_stats() is cs.cached_stats()
    cs.cached_stats.cache_clear()


def test_module_does_not_reach_the_authoring_stack():
    """The test that keeps the served app free of the authoring stack.

    A server install is `.[web]` with no embedding index, so an import of
    `ems.query`, `ems.embeddings` or `ems.graph` from here is either a crash on
    that server or PyTorch smuggled into an install built to avoid it. Run in a
    subprocess because the rest of the suite has already imported half of these.
    """
    banned = ("ems.query", "ems.embeddings", "ems.graph", "sentence_transformers", "torch")
    code = (
        "import sys; import ems.corpus_stats; "
        f"print([m for m in {banned!r} if m in sys.modules])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]", f"corpus_stats pulled in {out.stdout.strip()}"
