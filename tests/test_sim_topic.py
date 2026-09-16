"""Finding a call by what it is about.

Runs against the real corpus, because the thing being tested is whether the
vocabulary an EMT would actually type reaches the scenarios that carry it.
"""
import pytest

from ems.frontmatter import read_page
from ems.sim import topic
from ems.sim.playable import playable_cases


@pytest.fixture(scope="module")
def pool():
    return playable_cases()


def conditions_of(path):
    frontmatter, _ = read_page(path)
    return {topic.normalize(str(c)) for c in frontmatter.get("conditions") or ()}


def test_a_typed_phrase_matches_the_kebab_case_slug(pool):
    """Nobody types `chest-pain`."""
    assert topic.match("chest pain", pool) == topic.match("chest-pain", pool)


def test_an_exact_condition_beats_a_scenario_that_merely_mentions_it(pool):
    """Tiering, not scoring: the best kind of match wins outright.

    Without it, asking for a condition deals you calls whose dispatch happens to
    use the word — which is how you ask for a seizure and get a headache.
    """
    matches = topic.match("hypoxia", pool)
    assert all("hypoxia" in conditions_of(p) for p in matches)


def test_a_topic_only_ever_deals_a_playable_call(pool):
    from ems.sim.playable import unplayable

    for path in topic.match("chest pain", pool):
        assert not unplayable(*read_page(path))


def test_a_scenario_id_is_not_a_topic(pool):
    """`src1-s01` is handled by the exact-id path before this is ever reached."""
    assert topic.match("src1-s01", pool) == []


def test_nonsense_matches_nothing_and_suggests_something(pool):
    assert topic.match("zzzzz", pool) == []
    assert "hypoglycemia" in topic.suggest("hypoglicemia", pool)


def test_an_empty_query_is_not_a_match_for_everything(pool):
    assert topic.match("", pool) == []
    assert topic.match("   ", pool) == []

