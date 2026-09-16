"""
Tests for environment-aware selection (Project 8).
Deterministic and offline: seeded RNG, and a guard that no network call happens.
"""
import argparse
import collections
import random
import socket
from datetime import date, datetime

import pytest

from ems.cli import practice
from ems.frontmatter import read_page
from ems.scenarios import list_approved
from ems.vocabulary import load_vocabulary
from ems.sim import patterns
from ems.sim import select as selector
from ems.sim.patterns import Conditions, fetch_live, season_for, validate, weights
from ems.sim.scene import WEATHER_STATES, Environment, derive_scene

SMOKE_DAY = Conditions(season="fall", aqi=400)
CLEAR_DAY = Conditions(season="fall")


@pytest.fixture(scope="module")
def pool():
    return list_approved()


def share_by_condition(pool, conditions, draws=3000, seed=1):
    """What fraction of draws carried each condition slug."""
    choices = selector.weigh(pool, conditions)
    rng = random.Random(seed)
    tags = {p.stem: tuple(read_page(p)[0].get("conditions") or ()) for p in pool}

    counts = collections.Counter()
    for _ in range(draws):
        picked = selector.draw(choices, rng)
        for slug in tags[picked.stem] or ("(untagged)",):
            counts[slug] += 1
    total = sum(counts.values())
    return {slug: count / total for slug, count in counts.items()}


# ── seasons ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("month,season", [
    (1, "winter"), (2, "winter"), (12, "winter"),
    (4, "spring"), (7, "summer"), (10, "fall"),
])
def test_season_comes_from_the_calendar(month, season):
    assert season_for(date(2026, month, 15)) == season


def test_conditions_default_to_the_date_and_claim_nothing_else():
    conditions = Conditions.for_date(date(2026, 1, 15))
    assert conditions.season == "winter"
    assert conditions.aqi is None and conditions.heat_index is None


# ── weights ──────────────────────────────────────────────────────────────────

def test_no_conditions_means_no_multipliers():
    assert weights(Conditions()) == {}


def test_aqi_bands_are_tiers_not_layers():
    """A >300 day gets the >300 weight, not >150 and >300 multiplied together."""
    high = weights(Conditions(aqi=400))
    moderate = weights(Conditions(aqi=200))
    assert high["asthma"] == 3.0
    assert moderate["asthma"] == 2.2


def test_season_and_air_quality_compound():
    """Different rule groups do stack — fall asthma × a smoke day."""
    assert weights(SMOKE_DAY)["asthma"] == pytest.approx(1.3 * 3.0)


def test_a_clean_day_leaves_the_pool_alone():
    assert "hypoxia" not in weights(CLEAR_DAY)


# ── the table has to stay honest ─────────────────────────────────────────────

def test_every_weight_key_is_a_real_condition_slug():
    """A key that is not a slug matches nothing and silently does nothing."""
    result = validate()
    assert result.unknown == (), f"not condition slugs: {result.unknown}"


def test_unreachable_keys_are_reported_not_hidden():
    """A weight key that is a real slug but has no approved scenario is reported.

    Picks the slug at runtime rather than naming one: any slug named here
    eventually gets a scenario and the test then passes for the wrong reason.
    """
    tagged = set()
    for path in list_approved():
        tagged.update(read_page(path)[0].get("conditions") or ())
    untagged = sorted(set(load_vocabulary()["conditions"]) - tagged)
    if not untagged:
        pytest.skip("every condition slug now has an approved scenario")

    slug = untagged[0]
    synthetic = {"seasons": {"fall": {slug: 3.0}}, "conditions": {}, "weather": {}}
    assert slug in validate(synthetic).unreachable


# ── selection ────────────────────────────────────────────────────────────────

def test_weighting_never_empties_the_pool(pool):
    """Scenarios carrying no condition tag must stay reachable when weighting bites.

    Measured against their share of the pool rather than a fixed fraction. The
    absolute number only falls as the corpus grows — every source adds tagged
    scenarios, so the untagged slice shrinks arithmetically whether or not
    weighting is behaving. A constant threshold here fails on corpus growth
    instead of on a regression, which is what it did at 150 scenarios.
    """
    untagged = sum(1 for p in pool if not (read_page(p)[0].get("conditions") or ()))
    if not untagged:
        pytest.skip("every approved scenario now carries a condition tag")
    base_share = untagged / len(pool)

    smoke = share_by_condition(pool, SMOKE_DAY)
    drawn_share = smoke.get("(untagged)", 0)

    # Boosting smoke-related conditions is supposed to cost the untagged pool
    # some of its draw — but never most of it.
    assert drawn_share > base_share * 0.4, (
        f"untagged scenarios are {base_share:.1%} of the pool but take only "
        f"{drawn_share:.1%} of a weighted draw"
    )


def test_an_untagged_scenario_keeps_base_weight():
    weight, matched = selector.scenario_weight({"conditions": []}, {"asthma": 3.0})
    assert weight == 1.0 and matched == ()


def test_a_recently_seen_scenario_is_damped():
    frontmatter = {"scenario_id": "src1-s01", "conditions": ["asthma"]}
    fresh, _ = selector.scenario_weight(frontmatter, {"asthma": 2.0})
    stale, _ = selector.scenario_weight(frontmatter, {"asthma": 2.0}, recent=["src1-s01"])
    assert stale < fresh
    assert stale == pytest.approx(fresh * selector.RECENT_PENALTY)


def test_selection_is_reproducible_with_a_seed(pool):
    first = selector.select(pool, SMOKE_DAY, rng=random.Random(7))
    second = selector.select(pool, SMOKE_DAY, rng=random.Random(7))
    assert first == second


def test_selecting_from_an_empty_pool_is_none():
    assert selector.select([], SMOKE_DAY) is None


# ── offline by default ───────────────────────────────────────────────────────

def test_no_network_call_without_the_flag(monkeypatch):
    """The simulator has to run in a station with no internet."""
    monkeypatch.delenv("EMS_LIVE_ENV", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("opened a socket with EMS_LIVE_ENV unset")

    monkeypatch.setattr(socket, "socket", forbidden)
    conditions = fetch_live(zip_code="10601")
    assert conditions.season in ("winter", "spring", "summer", "fall")
    assert conditions.aqi is None


def test_live_lookup_without_a_key_degrades_quietly(monkeypatch):
    monkeypatch.setenv("EMS_LIVE_ENV", "1")
    monkeypatch.delenv("AIRNOW_API_KEY", raising=False)
    monkeypatch.delenv("EMS_LAT", raising=False)
    monkeypatch.delenv("EMS_LON", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("opened a socket with no API key configured")

    monkeypatch.setattr(socket, "socket", forbidden)
    assert fetch_live(zip_code="10601").aqi is None


# ── today's conditions → what the scene looks like ───────────────────────────

@pytest.mark.parametrize("hour,expected", [
    (0, "night"), (4, "night"), (5, "dawn"), (7, "dawn"),
    (8, "day"), (12, "day"), (17, "day"),
    (18, "dusk"), (20, "dusk"), (21, "night"), (23, "night"),
])
def test_the_clock_decides_the_time_of_day(hour, expected):
    assert patterns.time_of_day_for(hour) == expected


def test_a_night_call_is_derived_not_asked_for():
    """The whole point: nobody selected 'night', the clock did."""
    environment = patterns.environment_for(
        CLEAR_DAY, rng=random.Random(1), now=datetime(2026, 10, 4, 2, 30)
    )
    assert environment.time_of_day == "night"
    assert environment.hour == 2


def test_smoke_is_read_from_the_air_not_guessed():
    for seed in range(20):
        environment = patterns.environment_for(SMOKE_DAY, rng=random.Random(seed))
        assert environment.weather == "smoke"


def test_heat_is_read_from_the_heat_index():
    hot = Conditions(season="summer", heat_index=101)
    assert patterns.environment_for(hot, rng=random.Random(0)).weather == "heat"


def test_an_observation_beats_both_the_instruments_and_the_table():
    """Live NWS saw snow. It is snowing, whatever the AQI implies."""
    observed = Conditions(season="winter", aqi=400, weather="snow")
    assert patterns.environment_for(observed, rng=random.Random(0)).weather == "snow"


def test_the_same_seed_gives_the_same_weather():
    when = datetime(2026, 1, 8, 9)
    first = patterns.environment_for(CLEAR_DAY, rng=random.Random(11), now=when)
    second = patterns.environment_for(CLEAR_DAY, rng=random.Random(11), now=when)
    assert first == second


def test_drawn_weather_follows_the_table():
    table = patterns.load_patterns()
    rng = random.Random(4)
    drawn = collections.Counter(
        patterns.draw_weather("winter", table, rng) for _ in range(4000)
    )
    for state, share in table["weather"]["winter"].items():
        assert abs(drawn[state] / 4000 - share) < 0.04, f"{state} drifted from the table"


def test_a_season_with_no_table_is_clear_not_a_crash():
    assert patterns.draw_weather("", {"weather": {}}, random.Random(0)) == "clear"


def test_every_weather_value_is_one_the_renderer_can_draw():
    assert validate().undrawable == ()


def test_an_undrawable_weather_value_fails_validation():
    bogus = {"seasons": {}, "conditions": {}, "weather": {"winter": {"hail": 1.0}}}
    result = validate(bogus)
    assert result.undrawable == ("hail",)
    assert not result.ok


# ── the clock hour reaches the renderer, but never lies to it ────────────────

def test_the_hour_reaches_the_scene():
    scene = derive_scene(
        {"scenario_id": "t1"},
        "## Presentation\nThe patient is seated on the couch.\n",
        Environment(time_of_day="night", hour=3),
    )
    assert scene.time_of_day == "night"
    assert scene.hour == 3


def test_a_scenario_that_names_the_time_drops_the_clock_hour():
    """"At night" with the wall clock at 14:00 must not draw an afternoon sky."""
    scene = derive_scene(
        {"scenario_id": "t2"},
        "## Presentation\nYou arrive at night to find the patient supine.\n",
        Environment(time_of_day="day", hour=14),
    )
    assert scene.time_of_day == "night"
    assert scene.hour is None


def test_the_hour_serialises_for_the_renderer():
    scene = derive_scene({"scenario_id": "t3"}, "## Presentation\nSeated.\n",
                         Environment(hour=9))
    assert scene.to_dict()["hour"] == 9


# ── live weather ─────────────────────────────────────────────────────────────

def _nws_stub(description, heat_index_c=None):
    payloads = {
        "points": {"properties": {"observationStations": "https://x/stations"}},
        "stations": {"features": [{"properties": {"stationIdentifier": "KBFI"}}]},
        "obs": {"properties": {
            "textDescription": description,
            "heatIndex": {"value": heat_index_c},
        }},
    }

    def fake_get(url, timeout=5):
        if "/points/" in url:
            return payloads["points"]
        if url.endswith("/stations"):
            return payloads["stations"]
        return payloads["obs"]

    return fake_get


@pytest.mark.parametrize("description,expected", [
    ("Light Snow", "snow"),
    ("Heavy Rain", "rain"),
    ("Freezing Rain", "snow"),          # ice, not a rainy day
    ("Smoke", "smoke"),
    ("Haze", "smoke"),
    ("Fog/Mist", "fog"),
    ("Clear", ""),                      # nothing to say; the table may guess
    ("Partly Cloudy", ""),
])
def test_nws_descriptions_map_onto_drawable_weather(monkeypatch, description, expected):
    monkeypatch.setattr(patterns, "_get_json", _nws_stub(description))
    weather, _ = patterns.nws_weather("47.6", "-122.3")
    assert weather == expected
    assert weather == "" or weather in WEATHER_STATES


def test_nws_heat_index_arrives_in_fahrenheit(monkeypatch):
    monkeypatch.setattr(patterns, "_get_json", _nws_stub("Clear", heat_index_c=38.0))
    _, heat_index = patterns.nws_weather("47.6", "-122.3")
    assert heat_index == 100


def test_live_weather_reaches_the_conditions(monkeypatch):
    monkeypatch.setenv("EMS_LIVE_ENV", "1")
    monkeypatch.delenv("AIRNOW_API_KEY", raising=False)
    monkeypatch.setenv("EMS_LAT", "47.6")
    monkeypatch.setenv("EMS_LON", "-122.3")
    monkeypatch.setattr(patterns, "_get_json", _nws_stub("Light Snow"))
    assert fetch_live().weather == "snow"


def test_a_failing_weather_lookup_still_yields_a_usable_call(monkeypatch):
    """Offline, rate-limited, malformed — the call runs anyway."""
    monkeypatch.setenv("EMS_LIVE_ENV", "1")
    monkeypatch.setenv("EMS_LAT", "47.6")
    monkeypatch.setenv("EMS_LON", "-122.3")

    def explode(*args, **kwargs):
        raise OSError("network is down")

    monkeypatch.setattr(patterns, "_get_json", explode)
    conditions = fetch_live()
    assert conditions.weather == ""
    assert conditions.season in ("winter", "spring", "summer", "fall")


# ── the terminal and the browser agree ───────────────────────────────────────

def test_practice_cli_conditions_come_from_the_flags():
    args = argparse.Namespace(
        season="winter", aqi=400, heat_index=None, flu=False,
    )
    conditions = practice._conditions(args)
    assert conditions.season == "winter"
    assert conditions.aqi == 400
