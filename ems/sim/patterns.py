"""Today's conditions → what kind of call you get, and what it looks like.

Season, air quality and heat do two jobs here. They weight the scenario pool, so
on a wildfire-smoke day the trainee gets the asthma exacerbation they are about
to run; and they furnish the scene's weather and time of day, so that call also
*looks* like a smoke day. Both tables live in `system/call-patterns.yaml`,
hand-editable and offline: with `EMS_LIVE_ENV` unset, season derives from the
date and nothing touches the network.

**A rule that matches nothing is the failure mode to guard against.** A weight
key that is not a real condition slug, or is a slug no approved scenario
carries, changes no selection at all while looking like a working rule.
`validate` reports both; `protocol-patterns --check` fails the build on the
first and warns on the second.

**Weather is guessed only where it cannot be known.** Smoke and heat are read
off the AQI and heat index directly, and live NWS observations override
everything when enabled. The seasonal table is the fallback for an offline
station with no instruments — a national average, and wrong everywhere in
particular.
"""

import os
import random
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Optional

import yaml

from ems.frontmatter import read_page
from ems.paths import system_dir
from ems.scenarios import list_approved
from ems.sim.scene import WEATHER_STATES, Environment
from ems.vocabulary import load_vocabulary

SEASONS = ("winter", "spring", "summer", "fall")

#: Air quality at which the sky is visibly hazy, not merely measurably worse.
SMOKE_AQI = 150
#: Heat index at which the heat is the story of the call.
HOT_HEAT_INDEX = 95


def patterns_path():
    return system_dir() / "call-patterns.yaml"


@dataclass(frozen=True)
class Conditions:
    """What today is like. Everything optional — absent means "no opinion"."""
    season: str = ""
    aqi: Optional[int] = None
    heat_index: Optional[int] = None
    flu_season_peak: bool = False
    region: str = ""
    #: An observed weather state, when something actually measured it. Empty
    #: means nobody knows, and the seasonal table gets to guess.
    weather: str = ""

    @classmethod
    def for_date(cls, when: Optional[date] = None, **overrides) -> "Conditions":
        """Offline default: season from the calendar, nothing else claimed."""
        return cls(season=season_for(when or date.today()), **overrides)


def season_for(when: date) -> str:
    """Meteorological seasons, northern hemisphere."""
    return {12: "winter", 1: "winter", 2: "winter",
            3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer",
            9: "fall", 10: "fall", 11: "fall"}[when.month]


def load_patterns(path=None) -> dict:
    text = (path or patterns_path()).read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    return {
        "seasons": data.get("seasons") or {},
        "conditions": data.get("conditions") or {},
        "weather": data.get("weather") or {},
    }


def weights(conditions: Conditions, patterns: Optional[dict] = None) -> dict[str, float]:
    """Condition slug → multiplier for today. Multipliers compound."""
    patterns = patterns or load_patterns()
    result: dict[str, float] = {}

    def apply(rule: Optional[dict]) -> None:
        for slug, factor in (rule or {}).items():
            result[slug] = result.get(slug, 1.0) * float(factor)

    apply(patterns["seasons"].get(conditions.season))

    # AQI bands are tiers, not layers: the >300 rule replaces the >150 one
    # rather than stacking with it. Stacking read asthma as 2.2 × 3.0 = 6.6×
    # on a smoke day, which is not what a table listing 3.0 at >300 means.
    if conditions.aqi is not None:
        if conditions.aqi > 300:
            apply(patterns["conditions"].get("aqi_gt_300"))
        elif conditions.aqi > 150:
            apply(patterns["conditions"].get("aqi_gt_150"))
    if conditions.heat_index is not None and conditions.heat_index > 95:
        apply(patterns["conditions"].get("heat_index_gt_95"))
    if conditions.flu_season_peak:
        apply(patterns["conditions"].get("flu_season_peak"))

    return result


# ── today's conditions → what the scene looks like ───────────────────────────

def time_of_day_for(hour: int) -> str:
    """Clock hour → one of the renderer's four sky buckets."""
    if hour < 5 or hour >= 21:
        return "night"
    if hour < 8:
        return "dawn"
    if hour >= 18:
        return "dusk"
    return "day"


def draw_weather(season: str, patterns: Optional[dict] = None, rng=None) -> str:
    """One weighted pick from the season's table. `clear` when it has nothing."""
    patterns = patterns or load_patterns()
    shares = (patterns["weather"].get(season) or {})
    states = [s for s, share in shares.items() if float(share) > 0]
    if not states:
        return "clear"
    generator = rng or random.Random()
    return generator.choices(states, weights=[float(shares[s]) for s in states], k=1)[0]


def environment_for(
    conditions: Conditions,
    patterns: Optional[dict] = None,
    rng=None,
    now: Optional[datetime] = None,
) -> Environment:
    """What the call looks like, given what today is like.

    Weather precedence runs from most-known to least: an actual observation,
    then the two states the instruments imply outright, then a guess from the
    seasonal table. Guessing is the last resort, never the first.
    """
    moment = now or datetime.now()

    if conditions.weather:
        weather = conditions.weather
    elif conditions.aqi is not None and conditions.aqi > SMOKE_AQI:
        weather = "smoke"
    elif conditions.heat_index is not None and conditions.heat_index > HOT_HEAT_INDEX:
        weather = "heat"
    else:
        weather = draw_weather(conditions.season, patterns, rng)

    return Environment(
        time_of_day=time_of_day_for(moment.hour),
        weather=weather,
        season=conditions.season,
        region=conditions.region,
        hour=moment.hour,
    )


# ── keeping the table honest ─────────────────────────────────────────────────

@dataclass(frozen=True)
class Validation:
    #: Keys that are not condition slugs at all — a typo or a missing vocabulary entry.
    unknown: tuple[str, ...] = ()
    #: Real slugs that no approved scenario carries — the rule cannot fire.
    unreachable: tuple[str, ...] = ()
    #: Weather values the renderer has no way to draw.
    undrawable: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.unknown and not self.undrawable


def validate(patterns: Optional[dict] = None) -> Validation:
    patterns = patterns or load_patterns()
    vocabulary = set(load_vocabulary().get("conditions", []))
    tagged = set()
    for path in list_approved():
        frontmatter, _ = read_page(path)
        tagged.update(frontmatter.get("conditions") or ())

    keys = {
        slug
        for group in (patterns["seasons"], patterns["conditions"])
        for rule in group.values()
        for slug in (rule or {})
    }
    drawn = {
        state
        for shares in patterns["weather"].values()
        for state in (shares or {})
    }
    return Validation(
        unknown=tuple(sorted(keys - vocabulary)),
        unreachable=tuple(sorted((keys & vocabulary) - tagged)),
        undrawable=tuple(sorted(drawn - set(WEATHER_STATES))),
    )


# ── optional live enrichment ─────────────────────────────────────────────────
#
# Two independent lookups, both optional and both allowed to fail: AirNow for
# air quality, NWS for what the sky is doing. The simulator must run in a
# station with no internet, so every one of these is an enhancement layered on
# top of a complete offline answer — never a dependency, never a blocker.

#: NWS rejects requests without one. Identifies the caller, per their API terms.
_NWS_USER_AGENT = "ems-ai-simulator (github.com/neoromance/EMS-AI-SIM)"

#: NWS `textDescription` is free-ish text. Ordered most-specific first, because
#: "Light Snow and Fog" is a snow call before it is a fog call.
_NWS_WEATHER = (
    ("snow", ("snow", "sleet", "ice pellets", "freezing rain", "blizzard", "wintry")),
    ("rain", ("rain", "drizzle", "shower", "thunderstorm", "squall")),
    ("smoke", ("smoke", "haze", "ash", "dust")),
    ("fog", ("fog", "mist")),
)


def live_enabled() -> bool:
    return os.environ.get("EMS_LIVE_ENV") == "1"


def _get_json(url: str, timeout: int = 5):
    import json
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": _NWS_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def nws_weather(lat: str, lon: str) -> tuple[str, Optional[int]]:
    """Observed weather state and heat index (°F) from the nearest NWS station.

    Three chained calls — point to office grid, grid to station list, station to
    its latest observation. No API key; NWS asks only for a User-Agent.
    Returns ("", None) for anything it cannot answer.
    """
    point = _get_json(f"https://api.weather.gov/points/{lat},{lon}")
    stations = _get_json(point["properties"]["observationStations"])
    station = stations["features"][0]["properties"]["stationIdentifier"]
    observed = _get_json(
        f"https://api.weather.gov/stations/{station}/observations/latest"
    )["properties"]

    description = (observed.get("textDescription") or "").lower()
    weather = next(
        (state for state, terms in _NWS_WEATHER if any(t in description for t in terms)),
        "",
    )

    celsius = (observed.get("heatIndex") or {}).get("value")
    heat_index = None if celsius is None else round(celsius * 9 / 5 + 32)
    return weather, heat_index


def fetch_live(zip_code: str = "", when: Optional[date] = None) -> Conditions:
    """Today's air quality and weather. No-ops unless EMS_LIVE_ENV=1.

    Each source is tried on its own and swallowed on failure, so a rate-limited
    AirNow key does not cost you the weather, and neither costs you the call.
    """
    conditions = Conditions.for_date(when)
    if not live_enabled():
        return conditions

    key = os.environ.get("AIRNOW_API_KEY", "")
    zip_code = zip_code or os.environ.get("EMS_ZIP", "")
    if key and zip_code:
        try:
            observations = _get_json(
                "https://www.airnowapi.org/aq/observation/zipCode/current/"
                f"?format=application/json&zipCode={zip_code}&distance=25&API_KEY={key}"
            )
            aqi = max(
                (int(o["AQI"]) for o in observations if o.get("AQI") is not None),
                default=None,
            )
            conditions = replace(conditions, aqi=aqi, region=zip_code)
        except Exception:
            pass  # offline, rate-limited, malformed — the call still runs

    lat, lon = os.environ.get("EMS_LAT", ""), os.environ.get("EMS_LON", "")
    if lat and lon:
        try:
            weather, heat_index = nws_weather(lat, lon)
            conditions = replace(conditions, weather=weather, heat_index=heat_index)
        except Exception:
            pass  # same deal: a guessed sky beats no call at all

    return conditions
