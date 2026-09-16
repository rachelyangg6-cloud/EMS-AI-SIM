"""What a scenario is about, and why it is allowed to have no source.

A generated draft is grounded in wiki pages and belongs to no source. Demanding
`source_index` meant every draft became schema-invalid the moment it was promoted —
which is how two approved scenarios ended up in the corpus failing the checks.
Tags are what place a scenario now.
"""
import json
from pathlib import Path

import pytest

from ems.tags import (SOURCE_TAGS, CONDITION_TAGS, UntaggableScenario,
                      tags_for, valid_tags)

ROOT = Path(__file__).resolve().parent.parent


# ── the tables and the vocabulary agree ──────────────────────────────────────

def test_every_tag_the_tables_emit_is_in_the_vocabulary():
    """Otherwise new scenarios get tags the schema check then rejects."""
    emitted = {t for tags in CONDITION_TAGS.values() for t in tags}
    emitted |= {t for tags in SOURCE_TAGS.values() for t in tags}
    assert not emitted - valid_tags()


def test_no_tag_in_the_vocabulary_is_unreachable():
    """A topic nothing maps to is a filter that always returns nothing."""
    emitted = {t for tags in CONDITION_TAGS.values() for t in tags}
    emitted |= {t for tags in SOURCE_TAGS.values() for t in tags}
    assert not valid_tags() - emitted


def test_every_condition_slug_maps_to_a_tag():
    """A new condition added to the vocabulary without a tag would silently
    produce scenarios placed by source alone."""
    vocabulary = json.loads(
        (ROOT / "system" / "source-vocabulary.json").read_text(encoding="utf-8")
    )
    assert not set(vocabulary["conditions"]) - set(CONDITION_TAGS)


# ── deriving ─────────────────────────────────────────────────────────────────

def test_conditions_alone_are_enough():
    """The generated-draft case: pages, no source."""
    assert tags_for({"conditions": ["anaphylaxis"]}) == ["allergic reaction"]


def test_a_source_alone_is_enough():
    """112 scenarios name no condition — the foundational sources, where the
    subject is a skill rather than a disease."""
    assert tags_for({"source_index": 12}) == ["patient assessment"]


def test_both_contribute_rather_than_one_winning():
    """A vital signs scenario about an airway patient is both, and someone
    filtering for assessment practice should still find it."""
    assert tags_for({"source_index": 13, "conditions": ["hypoxia"]}) == [
        "airway and breathing", "patient assessment"
    ]


def test_tags_are_sorted_and_deduplicated():
    """Two conditions on the same topic must not produce it twice."""
    assert tags_for({"conditions": ["shock", "hemorrhagic-shock"]}) == ["bleeding and shock"]


def test_a_slug_can_carry_two_topics():
    """A GI bleed is an abdominal complaint and a bleeding patient."""
    assert tags_for({"conditions": ["gi-bleed"]}) == [
        "abdominal emergency", "bleeding and shock"
    ]


def test_an_unknown_condition_does_not_silently_vanish():
    """It contributes nothing, but the source still places the scenario."""
    assert tags_for({"source_index": 19, "conditions": ["not-a-real-slug"]}) == [
        "respiratory emergency"
    ]


# ── refusing to guess ────────────────────────────────────────────────────────

def test_a_source_with_no_entry_raises_rather_than_returning_nothing():
    """Source 31 onward are not ingested. When one lands, this is what tells
    whoever adds it that the table needs a line."""
    with pytest.raises(UntaggableScenario, match="SOURCE_TAGS"):
        tags_for({"source_index": 99})


def test_nothing_to_go_on_raises():
    """An empty tag list is a scenario no filter ever returns — the exact thing
    this field exists to prevent."""
    with pytest.raises(UntaggableScenario):
        tags_for({})


def test_an_unmappable_condition_with_no_source_raises():
    with pytest.raises(UntaggableScenario):
        tags_for({"conditions": ["not-a-real-slug"]})
