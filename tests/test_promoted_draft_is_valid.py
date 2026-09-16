"""A promoted draft must be a valid scenario — the guard that was missing.

Drafts were written by `save_draft` and scenarios by `_write_scenario`, and the
two produced different files. Nobody noticed until a draft was approved and
moved into `wiki/scenarios/`, where the stricter scenario schema applies: it
arrived with no `source_index`, no `tags`, no `## Related` section, an empty
`citations` list, and its frontmatter fence glued to the first heading.

Every one of those was a separate omission in the same function. This test
promotes a draft and holds the result to the schema, so the next divergence
fails here instead of in the corpus.
"""
import pytest

import tests.test_sim_generate as gen_tests
from ems.frontmatter import read_page
from ems.sim import generate as gen
from ems.sim import review as review_lib
from tests.test_schema_compliance import (SCENARIO_REQUIRED_KEYS,
                                          SCENARIO_REQUIRED_SECTIONS,
                                          VALID_SCENARIO_TAGS)


@pytest.fixture
def promoted(tmp_path, monkeypatch):
    """A draft, approved, sitting where the corpus lives."""
    quarantine, vetted = tmp_path / "generated", tmp_path / "vetted"
    vetted.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(review_lib, "generated_dir", lambda: quarantine)

    drafted = gen.draft(["asthma"], llm=gen_tests.stub(gen_tests.GOOD),
                        context=gen_tests.CONTEXT, lessons="")
    path = gen.save_draft(drafted, dest=quarantine)
    return review_lib.approve(path, labeled_by="ry", dest=vetted)


def test_it_carries_every_required_key(promoted):
    frontmatter, _ = read_page(promoted)
    missing = SCENARIO_REQUIRED_KEYS - set(frontmatter)
    assert not missing, f"a promoted draft is missing {sorted(missing)}"


def test_it_carries_every_required_section(promoted):
    """The `---## Dispatch` failure showed up here: not a missing newline, a
    file the section parser read as having no sections at all."""
    _, body = read_page(promoted)
    headings = {line[3:].strip() for line in body.splitlines() if line.startswith("## ")}
    missing = SCENARIO_REQUIRED_SECTIONS - headings
    assert not missing, f"a promoted draft is missing sections {sorted(missing)}"


def test_the_fence_is_not_glued_to_the_first_heading(promoted):
    assert "---## " not in promoted.read_text(encoding="utf-8")


def test_it_is_placeable_without_a_source(promoted):
    """The point of tags. A draft is grounded in wiki pages and belongs to no
    source_index, and that must not make it unfindable."""
    frontmatter, _ = read_page(promoted)
    assert frontmatter.get("source_index") is None
    assert frontmatter["tags"]
    assert not set(frontmatter["tags"]) - VALID_SCENARIO_TAGS


def test_an_approved_scenario_is_not_uncited(promoted):
    """The steps always carried citations inline; the frontmatter field was
    left empty, so every tool reading frontmatter saw an uncited case."""
    frontmatter, body = read_page(promoted)
    assert frontmatter["citations"]
    for citation in frontmatter["citations"]:
        assert citation in body
