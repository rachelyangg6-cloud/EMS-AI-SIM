"""
Schema compliance tests for all wiki pages.
Validates frontmatter fields, required sections, and scope_level values.
Only active pages are checked for required field completeness.
Templates (_template.md) are skipped entirely.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

WIKI_ROOT = Path(__file__).parent.parent / "wiki"

VALID_SCOPE_LEVELS = {"EMT-B", "AEMT", "Paramedic"}
VALID_STATUSES = {"active", "superseded", "draft"}

# Required frontmatter keys per page type (all pages, including draft)
REQUIRED_KEYS = {
    "protocol":  {"type", "title", "sop_id", "scope_level", "effective_date", "treats_conditions", "medications", "linked_pages", "status"},
    "condition": {"type", "title", "scope_level", "protocols", "red_flags", "linked_pages", "status"},
    "medication": {"type", "title", "scope_level", "effective_date", "used_in_protocols", "contraindicated_conditions", "linked_pages", "status"},
    "procedure": {"type", "title", "scope_level", "conditions", "linked_pages", "status"},
}

# Fields that must be non-empty strings on active pages
REQUIRED_NONEMPTY_ACTIVE = {
    "protocol":  {"title", "sop_id", "scope_level", "effective_date", "status"},
    "condition": {"title", "scope_level", "status"},
    "medication": {"title", "scope_level", "effective_date", "status"},
    "procedure": {"title", "scope_level", "status"},
}

# Required ## sections per page type (exact heading text)
REQUIRED_SECTIONS = {
    "protocol": {
        "When it applies",
        "Steps",
        "Medications & doses",
        "Scope boundaries",
        "Red flags",
        "Transport decision",
    },
    "condition": {
        "Recognition",
        "Differentials",
        "Assessment",
        "Field management",
        "When to escalate (ALS)",
    },
    "medication": {
        "Indications",
        "Adult dose",
        "Pediatric dose",
        "Route",
        "Contraindications",
        "Scope boundary",
    },
    "procedure": {
        "When to use",
        "Steps",
        "Common errors",
        "Documentation",
    },
}

# Map wiki subdirectory to expected page type
DIR_TO_TYPE = {
    "protocols":  "protocol",
    "conditions": "condition",
    "medications": "medication",
    "procedures": "procedure",
}

# ── Scenario schema (wiki/scenarios/) ───────────────────────────────────────
# Scenarios are training cases, not canonical pages: their own statuses, their
# own sections, and the simulator only ever runs approved ones.

#: `source_index` is deliberately absent. A scenario written out of a source has
#: one; a generated draft is grounded in wiki pages and belongs to no source,
#: and demanding the key made every draft unschema-compliant the moment it was
#: promoted. `tags` is what places a scenario now — see test_placeable below.
SCENARIO_REQUIRED_KEYS = {
    "type", "scenario_id", "tags", "kind", "scope_level", "status",
    "labeled_by", "corrected", "correction_note",
    "conditions", "procedures", "medications", "citations",
}

SCENARIO_LIST_FIELDS = ("conditions", "procedures", "medications", "citations")

SCENARIO_VALID_STATUSES = {"pending", "approved", "rejected"}

SCENARIO_VALID_KINDS = {
    "patient-care", "provider-safety", "medical-legal", "operational",
    "documentation-qi", "communication", "public-health", "mci-triage",
}

VALID_DIFFICULTIES = {"basic", "intermediate", "expert"}

VALID_AGE_GROUPS = {"neonate", "pediatric", "adult", "geriatric"}

#: Read from the vocabulary file rather than restated here, so adding a topic is
#: one edit. Restating it would let the two drift and the test would be checking
#: a list nobody maintains.
VALID_SCENARIO_TAGS = frozenset(
    json.loads((WIKI_ROOT.parent / "system" / "source-vocabulary.json").read_text(encoding="utf-8"))[
        "scenario_tags"
    ]
)

SCENARIO_REQUIRED_SECTIONS = {
    "Dispatch", "Presentation", "Vitals", "Correct actions",
    "Rationale", "Red flags", "Related",
}


def _all_scenarios() -> list[Path]:
    return [
        p for p in sorted((WIKI_ROOT / "scenarios").glob("*.md"))
        if p.name != "_template.md"
    ]


def _approved_scenarios() -> list[Path]:
    return [p for p in _all_scenarios() if _parse_page(p)[0].get("status") == "approved"]


def _parse_page(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text) for a wiki markdown file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm = yaml.safe_load(parts[1]) or {}
    body = parts[2]
    return fm, body


def _extract_h2_headings(body: str) -> set[str]:
    """Return the set of ## heading texts found in the body."""
    return {m.group(1).strip() for m in re.finditer(r"^##\s+(.+)$", body, re.MULTILINE)}


def _all_wiki_pages() -> list[Path]:
    """Return all .md files in wiki/ subdirectories, excluding _template.md files."""
    pages = []
    for subdir in DIR_TO_TYPE:
        pages.extend(
            p for p in (WIKI_ROOT / subdir).glob("*.md")
            if p.name != "_template.md"
        )
    return pages


def _collect_active_pages() -> list[Path]:
    return [p for p in _all_wiki_pages() if _parse_page(p)[0].get("status") == "active"]


# ── Parametrized fixtures ────────────────────────────────────────────────────

def pytest_generate_tests(metafunc):
    if "wiki_page" in metafunc.fixturenames:
        metafunc.parametrize("wiki_page", _all_wiki_pages(), ids=lambda p: p.name)
    if "active_page" in metafunc.fixturenames:
        metafunc.parametrize("active_page", _collect_active_pages(), ids=lambda p: p.name)
    if "scenario" in metafunc.fixturenames:
        metafunc.parametrize("scenario", _all_scenarios(), ids=lambda p: p.name)
    if "approved_scenario" in metafunc.fixturenames:
        metafunc.parametrize("approved_scenario", _approved_scenarios(), ids=lambda p: p.name)


# ── Tests that apply to ALL non-template pages ──────────────────────────────

class TestFrontmatterStructure:

    def test_has_valid_type_field(self, wiki_page):
        fm, _ = _parse_page(wiki_page)
        page_type = fm.get("type")
        assert page_type in REQUIRED_KEYS, (
            f"{wiki_page.name}: 'type' must be one of {list(REQUIRED_KEYS)}; got {page_type!r}"
        )

    def test_type_matches_directory(self, wiki_page):
        fm, _ = _parse_page(wiki_page)
        expected_type = DIR_TO_TYPE.get(wiki_page.parent.name)
        actual_type = fm.get("type")
        assert actual_type == expected_type, (
            f"{wiki_page.name}: file is in '{wiki_page.parent.name}/' so type must be "
            f"'{expected_type}'; got {actual_type!r}"
        )

    def test_required_keys_present(self, wiki_page):
        fm, _ = _parse_page(wiki_page)
        page_type = fm.get("type")
        if page_type not in REQUIRED_KEYS:
            pytest.skip("invalid type — covered by test_has_valid_type_field")
        missing = REQUIRED_KEYS[page_type] - set(fm.keys())
        assert not missing, (
            f"{wiki_page.name}: missing frontmatter keys: {sorted(missing)}"
        )

    def test_scope_level_is_valid_enum(self, wiki_page):
        fm, _ = _parse_page(wiki_page)
        scope = fm.get("scope_level")
        if scope:  # empty on draft is allowed; validated separately for active pages
            assert scope in VALID_SCOPE_LEVELS, (
                f"{wiki_page.name}: scope_level must be one of {sorted(VALID_SCOPE_LEVELS)}; got {scope!r}"
            )

    def test_status_is_valid_enum(self, wiki_page):
        fm, _ = _parse_page(wiki_page)
        status = fm.get("status")
        if status:
            assert status in VALID_STATUSES, (
                f"{wiki_page.name}: status must be one of {sorted(VALID_STATUSES)}; got {status!r}"
            )

    def test_auto_list_fields_are_lists(self, wiki_page):
        fm, _ = _parse_page(wiki_page)
        page_type = fm.get("type")
        list_fields_by_type = {
            "protocol":  ["treats_conditions", "medications", "linked_pages"],
            "condition": ["protocols", "red_flags", "linked_pages"],
            "medication": ["used_in_protocols", "contraindicated_conditions", "linked_pages"],
            "procedure": ["conditions", "linked_pages"],
        }
        fields = list_fields_by_type.get(page_type, [])
        for field in fields:
            val = fm.get(field)
            if val is not None:
                assert isinstance(val, list), (
                    f"{wiki_page.name}: '{field}' must be a list; got {type(val).__name__}"
                )


class TestSections:

    def test_required_sections_present(self, wiki_page):
        fm, body = _parse_page(wiki_page)
        page_type = fm.get("type")
        if page_type not in REQUIRED_SECTIONS:
            pytest.skip("invalid type — covered by structure tests")
        required = REQUIRED_SECTIONS[page_type]
        found = _extract_h2_headings(body)
        missing = required - found
        assert not missing, (
            f"{wiki_page.name}: missing required sections: {sorted(missing)}"
        )


# ── Tests that apply only to ACTIVE pages ───────────────────────────────────

class TestActivePageCompleteness:

    def test_required_nonempty_fields(self, active_page):
        fm, _ = _parse_page(active_page)
        page_type = fm.get("type")
        fields = REQUIRED_NONEMPTY_ACTIVE.get(page_type, set())
        empty = [f for f in fields if not fm.get(f)]
        assert not empty, (
            f"{active_page.name} (active): these fields must be non-empty: {sorted(empty)}"
        )

    def test_effective_date_format(self, active_page):
        fm, _ = _parse_page(active_page)
        date = fm.get("effective_date")
        if date:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", str(date)), (
                f"{active_page.name}: effective_date must be YYYY-MM-DD; got {date!r}"
            )

    def test_scope_level_nonempty_on_active(self, active_page):
        fm, _ = _parse_page(active_page)
        scope = fm.get("scope_level")
        assert scope in VALID_SCOPE_LEVELS, (
            f"{active_page.name} (active): scope_level must be set to a valid enum value; got {scope!r}"
        )


# ── Tests for training scenarios (wiki/scenarios/) ──────────────────────────

class TestScenarioSchema:

    def test_type_is_scenario(self, scenario):
        fm, _ = _parse_page(scenario)
        assert fm.get("type") == "scenario", (
            f"{scenario.name}: files in scenarios/ must have type 'scenario'; got {fm.get('type')!r}"
        )

    def test_required_keys_present(self, scenario):
        fm, _ = _parse_page(scenario)
        missing = SCENARIO_REQUIRED_KEYS - set(fm.keys())
        assert not missing, f"{scenario.name}: missing frontmatter keys: {sorted(missing)}"

    def test_tags_are_present_and_from_the_vocabulary(self, scenario):
        """A scenario nobody can find is the thing this field prevents, so an
        empty list fails as surely as a missing one."""
        fm, _ = _parse_page(scenario)
        tags = fm.get("tags") or []
        assert isinstance(tags, list) and tags, (
            f"{scenario.name}: tags must be a non-empty list; got {fm.get('tags')!r}"
        )
        unknown = sorted(set(tags) - VALID_SCENARIO_TAGS)
        assert not unknown, (
            f"{scenario.name}: {unknown} are not in scenario_tags in "
            f"system/source-vocabulary.json — a typo here is a topic nobody finds"
        )

    def test_a_scenario_is_placeable(self, scenario):
        """Every scenario is reachable by source, by topic, or both. Neither
        would mean a case in the corpus that no filter ever returns."""
        fm, _ = _parse_page(scenario)
        assert fm.get("source_index") is not None or fm.get("tags"), (
            f"{scenario.name}: has neither a source nor tags"
        )

    def test_source_index_when_present_matches_the_filename(self, scenario):
        """`source_index` is optional now, but a srcNN- file claiming a different
        source_index is a copy-paste error, not a design choice."""
        fm, _ = _parse_page(scenario)
        if not scenario.stem.startswith("src") or "-s" not in scenario.stem:
            return
        expected = int(scenario.stem[3:].split("-s")[0])
        assert fm.get("source_index") == expected, (
            f"{scenario.name}: filename says source {expected}, frontmatter says "
            f"{fm.get('source_index')!r}"
        )

    def test_scenario_id_matches_filename(self, scenario):
        fm, _ = _parse_page(scenario)
        assert fm.get("scenario_id") == scenario.stem, (
            f"{scenario.name}: scenario_id must match the filename; got {fm.get('scenario_id')!r}"
        )

    def test_status_is_valid_enum(self, scenario):
        fm, _ = _parse_page(scenario)
        assert fm.get("status") in SCENARIO_VALID_STATUSES, (
            f"{scenario.name}: status must be one of {sorted(SCENARIO_VALID_STATUSES)}; "
            f"got {fm.get('status')!r}"
        )

    def test_kind_is_valid_enum(self, scenario):
        fm, _ = _parse_page(scenario)
        assert fm.get("kind") in SCENARIO_VALID_KINDS, (
            f"{scenario.name}: kind must be one of {sorted(SCENARIO_VALID_KINDS)}; "
            f"got {fm.get('kind')!r}"
        )

    def test_scope_level_is_valid_enum(self, scenario):
        fm, _ = _parse_page(scenario)
        assert fm.get("scope_level") in VALID_SCOPE_LEVELS, (
            f"{scenario.name}: scope_level must be one of {sorted(VALID_SCOPE_LEVELS)}; "
            f"got {fm.get('scope_level')!r}"
        )

    def test_optional_enums_are_valid_when_set(self, scenario):
        fm, _ = _parse_page(scenario)
        difficulty, age_group = fm.get("difficulty"), fm.get("age_group")
        if difficulty is not None:
            assert difficulty in VALID_DIFFICULTIES, (
                f"{scenario.name}: difficulty must be one of {sorted(VALID_DIFFICULTIES)}; "
                f"got {difficulty!r}"
            )
        if age_group is not None:
            assert age_group in VALID_AGE_GROUPS, (
                f"{scenario.name}: age_group must be one of {sorted(VALID_AGE_GROUPS)}; "
                f"got {age_group!r}"
            )

    def test_list_fields_are_lists(self, scenario):
        fm, _ = _parse_page(scenario)
        for field in SCENARIO_LIST_FIELDS:
            val = fm.get(field)
            if val is not None:
                assert isinstance(val, list), (
                    f"{scenario.name}: '{field}' must be a list; got {type(val).__name__}"
                )

    def test_required_sections_present(self, scenario):
        _, body = _parse_page(scenario)
        missing = SCENARIO_REQUIRED_SECTIONS - _extract_h2_headings(body)
        assert not missing, f"{scenario.name}: missing required sections: {sorted(missing)}"


class TestApprovedScenarios:
    """An approved scenario is an expertise-marked fact — the simulator's ground
    truth. These are the invariants the runner and grader rely on."""

    def test_labeled_by_is_set(self, approved_scenario):
        fm, _ = _parse_page(approved_scenario)
        assert fm.get("labeled_by"), (
            f"{approved_scenario.name}: an approved scenario must record who reviewed it"
        )

    def test_has_numbered_correct_actions(self, approved_scenario):
        _, body = _parse_page(approved_scenario)
        section = re.search(
            r"^##\s+Correct actions\s*\n(.*?)(?=^##\s|\Z)", body, re.MULTILINE | re.DOTALL
        )
        actions = re.findall(r"^\d+\.\s", section.group(1), re.MULTILINE) if section else []
        assert actions, (
            f"{approved_scenario.name}: 'Correct actions' must be an ordered numbered list — "
            f"it is the grader's answer key"
        )

    def test_has_citations(self, approved_scenario):
        fm, _ = _parse_page(approved_scenario)
        assert fm.get("citations"), (
            f"{approved_scenario.name}: an approved scenario must carry at least one citation"
        )
