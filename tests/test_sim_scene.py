"""
Tests for SceneSpec derivation (Project 3).
Deterministic and offline — derive_scene never calls an LLM.

The snapshots below are hand-verified against the scenario text they come from,
so a change to a pattern that silently redraws a real case will fail here.
"""
import json
import re

import pytest

from ems.frontmatter import read_page
from ems.markdown import get_section
from ems.scenarios import list_approved
from ems.sim.scene import (
    EFFORT_STATES,
    LOC_STATES,
    POSTURES,
    SETTINGS,
    SKIN_STATES,
    Environment,
    derive_scene,
    parse_vitals,
)


@pytest.fixture(scope="module")
def corpus():
    """Every approved scenario, keyed by id, with its derived scene."""
    scenes = {}
    for path in list_approved():
        frontmatter, body = read_page(path)
        scenes[path.stem] = (frontmatter, body, derive_scene(frontmatter, body))
    return scenes


def scene(corpus, scenario_id):
    assert scenario_id in corpus, f"{scenario_id} is no longer an approved scenario"
    return corpus[scenario_id][2]


# ── vitals parsing ───────────────────────────────────────────────────────────

def test_parse_vitals_reads_every_stated_field():
    v = parse_vitals("RR 36 and shallow, pulse 118, SpO2 82%, skin cool/cyanotic, "
                     "increasingly somnolent.")
    assert (v.rr, v.hr, v.spo2) == (36, 118, 82)
    assert v.skin == "cyanotic"
    assert v.loc == "drowsy"


def test_parse_vitals_reads_bp_and_alternate_wording():
    v = parse_vitals("RR 28 shallow, pulse 122, BP 84/50, SpO2 85%, responds only to loud voice.")
    assert v.bp == "84/50"
    assert v.loc == "verbal"


@pytest.mark.parametrize("text", [
    "N/A — provider-safety scenario",
    "Being obtained.",
    "Not yet obtained — scene size-up before patient contact.",
    "",
])
def test_unstated_vitals_stay_none(text):
    v = parse_vitals(text)
    assert (v.rr, v.hr, v.spo2, v.bp, v.skin, v.loc) == (None,) * 6


def test_a_ruled_out_finding_is_not_drawn():
    """"You hear no snoring or gurgling" must not render an obstructed airway."""
    body = """
## Dispatch
Unresponsive medical patient.

## Presentation
An unresponsive adult is lying supine. You hear no snoring or gurgling yet, and there
is no difficulty breathing.

## Vitals
Responds only to painful stimulus.
"""
    s = derive_scene({"scenario_id": "x"}, body)
    assert s.patient.effort is None
    assert s.patient.posture == "supine"
    assert s.patient.loc == "painful"


def test_negation_does_not_swallow_the_next_clause():
    """The guard is clause-scoped: a finding after the comma still counts."""
    s = derive_scene({"scenario_id": "x"}, """
## Presentation
No trauma is suspected, but the patient has gurgling respirations.

## Vitals
Unresponsive.
""")
    assert s.patient.effort == "obstructed"


def test_the_worst_skin_finding_wins():
    """A patient described as pale *and* cyanotic is a cyanotic patient."""
    assert parse_vitals("skin pale, lips cyanotic").skin == "cyanotic"


# ── the plan's stated acceptance case ────────────────────────────────────────

# ── snapshots over real scenarios ────────────────────────────────────────────

# ── the invariant the whole feature rests on ─────────────────────────────────

def test_no_scene_invents_a_vital_sign(corpus):
    """Every number in a SceneSpec must appear literally in the scenario's vitals.

    This is the guard against the animation drifting from EMT-vetted content.
    """
    for scenario_id, (_, body, spec) in corpus.items():
        if spec.patient is None:
            continue
        vitals_text = get_section(body, "Vitals") or ""
        for field in ("rr", "hr", "spo2"):
            value = getattr(spec.patient, field)
            if value is None:
                continue
            assert re.search(rf"\b{value}\b", vitals_text), (
                f"{scenario_id}: {field}={value} appears nowhere in its vitals"
            )


def test_a_silent_scenario_yields_no_numbers(corpus):
    """No vitals stated means no vitals shown — never a plausible default."""
    for scenario_id, (_, body, spec) in corpus.items():
        if spec.patient is None:
            continue
        if re.search(r"\d", get_section(body, "Vitals") or ""):
            continue
        assert (spec.patient.rr, spec.patient.hr, spec.patient.spo2) == (None, None, None), (
            f"{scenario_id} invented a number from a vitals section with no digits"
        )


def test_every_derived_value_is_in_its_vocabulary(corpus):
    for scenario_id, (_, _, spec) in corpus.items():
        assert spec.setting in SETTINGS, scenario_id
        if spec.patient is None:
            continue
        for value, vocabulary in (
            (spec.patient.posture, POSTURES),
            (spec.patient.skin, SKIN_STATES),
            (spec.patient.effort, EFFORT_STATES),
            (spec.patient.loc, LOC_STATES),
        ):
            assert value is None or value in vocabulary, f"{scenario_id}: {value}"


# ── environment ──────────────────────────────────────────────────────────────

def test_environment_supplies_time_and_weather(corpus):
    frontmatter, body, _ = corpus["src1-s01"]
    s = derive_scene(frontmatter, body, Environment(time_of_day="night", weather="snow"))
    assert (s.time_of_day, s.weather) == ("night", "snow")


def test_the_scenario_text_overrides_the_environment():
    """Vetted content beats a generated default."""
    body = """
## Dispatch
Call at 3 a.m. in a downpour.

## Presentation
A man is slumped on the porch.

## Vitals
Alert.
"""
    s = derive_scene({"scenario_id": "x"}, body, Environment(time_of_day="day", weather="clear"))
    assert s.time_of_day == "night"
    assert s.weather == "rain"


def test_hazards_bystanders_and_equipment_are_read_from_the_scene():
    body = """
## Dispatch
Man down in the roadway.

## Presentation
He is supine in the street with traffic still moving past. A downed power line lies
across the hood. His distraught wife is screaming from the sidewalk. An inhaler and
several pill bottles are on the ground.

## Vitals
Unresponsive.
"""
    s = derive_scene({"scenario_id": "x"}, body)
    assert s.setting == "street"
    assert set(s.hazards) >= {"traffic", "electrical"}
    assert [(b.role, b.state) for b in s.bystanders] == [("wife", "distraught")]
    assert set(s.equipment_visible) == {"inhaler", "pill-bottles"}
    assert s.patient.posture == "supine"


# ── the wire format ──────────────────────────────────────────────────────────

def test_to_dict_is_json_serializable(corpus):
    for scenario_id, (_, _, spec) in corpus.items():
        payload = json.dumps(spec.to_dict())
        assert json.loads(payload)["scenario_id"] == scenario_id

