"""Only calls with a patient reach the simulator.

Driven by three real sessions: src4-s09 had no patient at all, and src18-s01 and
src6-s10 were tagged patient-care but still unplayable.
"""
from ems.frontmatter import read_page
from ems.paths import scenarios_dir
from ems.scenarios import list_approved
from ems.sim.playable import playable_cases, unplayable


def _why(scenario_id: str) -> list[str]:
    return unplayable(*read_page(scenarios_dir() / f"{scenario_id}.md"))


def test_a_good_call_survives_every_check():
    """src1-s02 — a named patient, a complaint, and a scene you walk into."""
    assert _why("src1-s02") == []


def test_the_pool_is_a_subset_of_approved_and_is_not_empty():
    approved, playable = set(list_approved()), playable_cases()
    assert playable, "the simulator would have nothing to deal"
    assert set(playable) <= approved


def test_every_playable_case_is_patient_care():
    for path in playable_cases():
        assert read_page(path)[0].get("kind") == "patient-care"
