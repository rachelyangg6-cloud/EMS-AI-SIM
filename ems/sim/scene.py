"""Derive the animated scene from a scenario — deterministically, no LLM.

The `SceneSpec` is the contract between the graded call and the picture the
trainee sees. It is data, not prose, and it is derived by rule so that the
animation can never contradict the clinical facts: the chest-rise rate *is* the
scenario's respiratory rate, the dusky figure *is* its cyanosis.

**Unknown stays unknown.** Most of the corpus does not state a respiratory rate
— 27 of 150 approved scenarios do. Every field here is therefore optional and is
left `None` when the scenario is silent, exactly as the vitals monitor stays
blank until the EMT actually measures something. Nothing is inferred from a
condition slug, because a number on screen that no EMT vetted is a number the
product has no right to show.

**Precedence.** ``## Vitals`` is authoritative for rate, skin, and mental
status. ``## Presentation`` supplies posture, setting, bystanders, equipment and
hazards, and fills in skin/effort/LOC only where the vitals section is silent.
Where the scenario text names the time of day or weather it overrides the
`Environment`, because the scenario is vetted content and the environment is not.

Project 6 may elaborate the *narration* around a scene. It may never change a
field of the `SceneSpec`.
"""

import re
from dataclasses import asdict, dataclass
from typing import Optional

from ems.markdown import get_section

# ── vocabularies (each value is one drawable state in the Project 5 renderer) ─

SETTINGS = ("residence", "street", "public-space", "workplace", "ambulance", "unknown")
POSTURES = ("tripod", "slumped", "seated", "supine", "prone", "ambulatory")
SKIN_STATES = ("cyanotic", "mottled", "diaphoretic", "pale", "flushed", "normal")
EFFORT_STATES = (
    "apneic", "agonal", "obstructed", "accessory-muscle-use", "labored", "shallow", "normal",
)
LOC_STATES = ("unresponsive", "painful", "verbal", "drowsy", "confused", "alert")
TIMES_OF_DAY = ("day", "night", "dawn", "dusk")
WEATHER_STATES = ("clear", "snow", "rain", "fog", "smoke", "heat", "cold")

# Ordered most-severe first: a scenario that says both "pale" and "cyanotic"
# is describing a cyanotic patient.
_SKIN_PATTERNS = (
    ("cyanotic", r"cyanotic|cyanosis|dusky|bluish|blue lips|blue around"),
    ("mottled", r"mottl"),
    ("diaphoretic", r"diaphore|clammy|sweaty|profusely sweating"),
    ("pale", r"\bpale\b|ashen|\bpallor\b|\bwhite\b(?= skin)"),
    ("flushed", r"flushed|\bred\b(?= skin)|hot and dry"),
    ("normal", r"normal skin color|skin (color )?normal|pink and dry|warm and dry"),
)

_EFFORT_PATTERNS = (
    ("apneic", r"apnei|not breathing|no (spontaneous )?respirations|no air movement"),
    ("agonal", r"agonal|gasping"),
    # Airway noise is not effort, but it is the loudest thing in the room and
    # the renderer needs to show it.
    ("obstructed", r"gurgl|snoring respiration|\bstridor\b|noisy respiration|"
                   r"\bsnores\b|audible obstruction"),
    ("accessory-muscle-use", r"accessory muscle|neck and abdominal muscle|retraction|"
                             r"nasal flaring|flaring nostril|see-?saw"),
    ("labored", r"labored|working (hard )?to breathe|struggling to breathe|"
                r"increased work of breathing|tripod|short of breath|dyspnea"),
    ("shallow", r"shallow"),
    ("normal", r"breathing (is )?(adequate|normal|unlabored)|respirations (adequate|normal)"),
)

_LOC_PATTERNS = (
    ("unresponsive", r"unresponsive|unconscious|does not respond|no response to"),
    ("painful", r"responds? (only )?to pain|painful stimul"),
    ("verbal", r"responds? (only )?to (a )?(loud )?(voice|verbal)|verbal stimul"),
    ("drowsy", r"drowsy|somnolen|lethargic|sleepy|obtunded|difficult to (rouse|arouse)"),
    ("confused", r"confus|disorient|altered mental status|\bams\b"),
    ("alert", r"\balert\b|\bawake\b|a&ox|alert and orient"),
)

_POSTURE_PATTERNS = (
    ("tripod", r"tripod|leaning forward on|hands on (his |her |their )?knees"),
    ("slumped", r"slumped|slouched|hunched"),
    ("supine", r"\bsupine\b|lying (flat |face )?(on (his|her|their) back)?|flat on the (floor|ground|bed)"),
    ("prone", r"\bprone\b|face ?down"),
    ("seated", r"\bseated\b|sitting|sits\b|in a (recliner|chair|wheelchair)|on the (couch|sofa)|"
               r"(still )?in the (driver'?s |passenger )?seat"),
    ("ambulatory", r"ambulatory|walking|standing|pacing|walks (up|toward|over)|"
                   r"meets you at the (door|curb)"),
)

_SETTING_PATTERNS = (
    ("ambulance", r"\bambulance\b|\bthe rig\b|\bpatient compartment\b|back of the (unit|truck)"),
    ("street", r"\bstreet\b|roadway|highway|\bcurb\b|sidewalk|intersection|\bmvc\b|"
               r"motor vehicle|\bcrash\b|guardrail|parking lot|driveway"),
    ("workplace", r"\bwarehouse\b|construction|factory|job ?site|\boffice\b|loading dock|"
                  r"\bshop floor\b|\bat work\b|\bjobsite\b"),
    ("public-space", r"\bstore\b|restaurant|\bmall\b|\bschool\b|\bgym\b|\bpark\b|\bstadium\b|"
                     r"\bchurch\b|\bbar\b|\bpool\b|\bbeach\b|\btheater\b|shopping"),
    ("residence", r"\bhome\b|\bhouse\b|residence|apartment|\bkitchen\b|\bbedroom\b|"
                  r"living room|\bbathroom\b|\brecliner\b|\bcouch\b|\bsofa\b|\bporch\b|"
                  r"front door|\bhallway\b|\bstairs? of (his|her|their)\b"),
)

_HAZARD_PATTERNS = (
    ("traffic", r"traffic|oncoming (cars|vehicles)|active roadway|passing cars"),
    ("fire", r"\bfire\b|\bflames\b|\bburning\b"),
    ("smoke", r"\bsmoke\b|\bsmoky\b"),
    ("electrical", r"downed (power )?line|live wire|electrical hazard|energized"),
    ("chemical", r"chemical|hazmat|fumes|\bspill\b|\bleak\b|placard"),
    ("weapon", r"\bweapon\b|\bknife\b|\bgun\b|\bfirearm\b|\barmed\b"),
    ("violence", r"violent|fighting|combative bystander|assault|threaten"),
    ("animal", r"\bdog\b|\bpet\b|growling|animal"),
    ("unstable-vehicle", r"unstable vehicle|vehicle on its (side|roof)|rollover|\brolled over\b"),
    ("stairs", r"narrow stairs|steep stairs|flight of stairs|basement stairs"),
    ("glass", r"broken glass|shattered"),
    ("water", r"\bin the water\b|\bdrowning\b|submerged|\bicy pond\b"),
    ("ice", r"\bicy\b|\bice-covered\b|\bslippery\b"),
    ("crowd", r"\bcrowd\b|gathering bystanders|onlookers"),
    ("confined-space", r"confined space|\btrench\b|\bsilo\b|\bmanhole\b"),
)

_EQUIPMENT_PATTERNS = (
    ("home-oxygen", r"home oxygen|oxygen concentrator|\bo2 tank\b|nasal cannula in place"),
    ("inhaler", r"\binhaler\b|\bmdi\b|\brescue inhaler\b"),
    ("nebulizer", r"nebuliz"),
    ("cpap", r"\bcpap\b|\bbipap\b"),
    ("epinephrine-auto-injector", r"epi-?pen|auto-?injector"),
    ("glucometer", r"glucometer|glucose meter|test strips"),
    ("walker", r"\bwalker\b|\brollator\b"),
    ("cane", r"\bcane\b"),
    ("wheelchair", r"wheelchair"),
    ("pill-bottles", r"pill bottles?|medication bottles?|prescription bottles?|\bpillbox\b"),
    ("alcohol", r"beer cans?|liquor|empty bottles?|\balcohol\b"),
    ("paraphernalia", r"paraphernalia|\bsyringe\b|\bneedle\b(?! decompression)|\bspoon\b"),
)

_BYSTANDER_ROLES = (
    "husband", "wife", "spouse", "mother", "father", "son", "daughter", "sister",
    "brother", "grandmother", "grandfather", "friend", "neighbor", "coworker",
    "teacher", "coach", "manager", "bystander", "caregiver", "nurse",
    "police officer", "firefighter", "parent",
)

_BYSTANDER_STATES = (
    ("distraught", r"distraught|hysterical|screaming|sobbing|crying|panick"),
    ("anxious", r"anxious|worried|frantic|nervous|upset"),
    ("agitated", r"agitated|angry|yelling|hostile|combative|belligerent"),
    ("uncooperative", r"uncooperative|refuses to|won'?t answer|evasive"),
    ("calm", r"\bcalm\b|matter-of-fact|composed"),
)

_TIME_PATTERNS = (
    ("night", r"\bat night\b|\bmidnight\b|\b\d{1,2} ?a\.?m\.?\b|overnight|\bdark\b|"
              r"\bevening\b|after dark"),
    ("dawn", r"\bdawn\b|\bsunrise\b|early morning"),
    ("dusk", r"\bdusk\b|\bsunset\b|\btwilight\b"),
    ("day", r"\bmidday\b|\bafternoon\b|\bnoon\b|broad daylight"),
)

_WEATHER_PATTERNS = (
    ("snow", r"\bsnow|\bblizzard\b|\bsleet\b"),
    ("rain", r"\brain|\bdownpour\b|\bstorm\b|\bwet pavement\b"),
    ("fog", r"\bfog"),
    ("smoke", r"wildfire smoke|smoky (air|sky)|hazy with smoke"),
    ("heat", r"\bheat wave\b|\bscorching\b|\bblistering heat\b|\d{2,3} ?degrees"),
    ("cold", r"\bfreezing\b|\bsub-?zero\b|bitter cold|\bwind ?chill\b"),
)

_NO_VITALS_RE = re.compile(r"^\s*(n/?a\b|none\b|being obtained|not obtained|unknown\b)", re.I)

# A finding is ruled out if a negation precedes it in the same clause.
_NEGATION_RE = re.compile(
    r"\b(no|not|without|denies|denied|free of|absent|negative for)\b[^.,;]{0,30}$", re.I
)


# ── data ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Environment:
    """Conditions the call runs under. Project 8 fills these from season/AQI."""
    time_of_day: str = "day"
    weather: str = "clear"
    season: str = ""
    region: str = ""
    #: Clock hour 0–23, for a sky that shifts through the day rather than
    #: snapping between four fixed gradients. None when only the bucket is known.
    hour: Optional[int] = None


@dataclass(frozen=True)
class Vitals:
    """What ``## Vitals`` actually states. None means the scenario is silent."""
    rr: Optional[int] = None
    hr: Optional[int] = None
    spo2: Optional[int] = None
    bp: Optional[str] = None
    skin: Optional[str] = None
    loc: Optional[str] = None


@dataclass(frozen=True)
class Bystander:
    role: str
    state: str = "present"


@dataclass(frozen=True)
class PatientSpec:
    """The figure to draw. Every field may be None — draw a neutral pose then."""
    posture: Optional[str] = None
    skin: Optional[str] = None
    effort: Optional[str] = None
    loc: Optional[str] = None
    rr: Optional[int] = None
    hr: Optional[int] = None
    spo2: Optional[int] = None

    def is_empty(self) -> bool:
        return all(v is None for v in astuple_safe(self))


@dataclass(frozen=True)
class SceneSpec:
    """Everything the renderer needs, and nothing the renderer may invent."""
    scenario_id: str
    setting: str = "unknown"
    time_of_day: str = "day"
    weather: str = "clear"
    #: Clock hour 0–23 when one is actually known, for a continuously shifting
    #: sky. None whenever the scenario's own words set the time, because "at
    #: night" fixes the bucket and says nothing about which hour of the night.
    hour: Optional[int] = None
    hazards: tuple[str, ...] = ()
    bystanders: tuple[Bystander, ...] = ()
    patient: Optional[PatientSpec] = None
    equipment_visible: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """JSON-ready form, for the Project 4 API and the Project 5 renderer."""
        data = asdict(self)
        data["hazards"] = list(self.hazards)
        data["equipment_visible"] = list(self.equipment_visible)
        data["bystanders"] = [asdict(b) for b in self.bystanders]
        return data


def astuple_safe(obj) -> tuple:
    return tuple(asdict(obj).values())


# ── parsing ──────────────────────────────────────────────────────────────────

def _negated(text: str, start: int) -> bool:
    """Is the match at ``start`` inside a negated clause?

    Scenarios routinely rule findings out — "You hear no snoring or gurgling",
    "no difficulty breathing". Drawing those as present would put a finding on
    screen that the scenario explicitly denies.
    """
    return bool(_NEGATION_RE.search(text[max(0, start - 40):start]))


def _search(pattern: str, text: str) -> bool:
    """True if the pattern occurs somewhere it is not being ruled out."""
    return any(
        not _negated(text, m.start())
        for m in re.finditer(pattern, text, re.IGNORECASE)
    )


def _first_match(patterns, text: str) -> Optional[str]:
    for value, pattern in patterns:
        if _search(pattern, text):
            return value
    return None


def _all_matches(patterns, text: str) -> tuple[str, ...]:
    return tuple(v for v, p in patterns if _search(p, text))


def _number(pattern: str, text: str) -> Optional[int]:
    match = re.search(pattern, text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def parse_vitals(text: str) -> Vitals:
    """Read ``## Vitals``. Anything not stated comes back None."""
    if not text or _NO_VITALS_RE.match(text):
        return Vitals()
    return Vitals(
        rr=_number(r"\b(?:rr|resp(?:iration|iratory)?(?:\s+rate)?)\D{0,4}(\d{1,3})\b", text),
        hr=_number(r"\b(?:hr|pulse|heart rate)\D{0,4}(\d{1,3})\b", text),
        spo2=_number(r"\b(?:spo2|sao2|sat(?:s|uration)?)\D{0,4}(\d{1,3})\s*%?", text),
        bp=(m.group(1) if (m := re.search(r"\b(?:bp|blood pressure)\D{0,4}(\d{2,3}/\d{2,3})", text,
                                          re.IGNORECASE)) else None),
        skin=_first_match(_SKIN_PATTERNS, text),
        loc=_first_match(_LOC_PATTERNS, text),
    )


def _bystanders(text: str) -> tuple[Bystander, ...]:
    """One entry per role named, with a state read from its own sentence."""
    found: list[Bystander] = []
    seen: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for role in _BYSTANDER_ROLES:
            if role in seen or not re.search(rf"\b{role}\b", sentence, re.IGNORECASE):
                continue
            seen.add(role)
            found.append(Bystander(role=role, state=_first_match(_BYSTANDER_STATES, sentence)
                                   or "present"))
    return tuple(found)


# ── the derivation ───────────────────────────────────────────────────────────

def derive_scene(
    frontmatter: dict, body: str, environment: Optional[Environment] = None
) -> SceneSpec:
    """Build the `SceneSpec` for one scenario. Pure, deterministic, offline."""
    environment = environment or Environment()
    presentation = get_section(body, "Presentation") or ""
    dispatch = get_section(body, "Dispatch") or ""
    vitals = parse_vitals(get_section(body, "Vitals") or "")
    narrative = f"{dispatch}\n{presentation}"

    patient = PatientSpec(
        # Posture is often only in the dispatch ("still seated in the car").
        posture=_first_match(_POSTURE_PATTERNS, narrative),
        # Vitals win; the presentation only fills a gap.
        skin=vitals.skin or _first_match(_SKIN_PATTERNS, presentation),
        effort=_first_match(_EFFORT_PATTERNS, f"{get_section(body, 'Vitals') or ''}\n{presentation}"),
        loc=vitals.loc or _first_match(_LOC_PATTERNS, presentation),
        rr=vitals.rr,
        hr=vitals.hr,
        spo2=vitals.spo2,
    )

    # The scenario is vetted content; the environment is only a default.
    spoken_time = _first_match(_TIME_PATTERNS, narrative)

    return SceneSpec(
        scenario_id=frontmatter.get("scenario_id", ""),
        setting=_first_match(_SETTING_PATTERNS, narrative) or "unknown",
        time_of_day=spoken_time or environment.time_of_day,
        # A clock hour the scenario contradicts is worse than no hour at all:
        # "at night" with the wall clock at 14:00 would draw an afternoon sky
        # over a night call. Keep the hour only when the text left time alone.
        hour=None if spoken_time else environment.hour,
        weather=_first_match(_WEATHER_PATTERNS, narrative) or environment.weather,
        hazards=_all_matches(_HAZARD_PATTERNS, narrative),
        bystanders=_bystanders(presentation),
        patient=None if patient.is_empty() else patient,
        equipment_visible=_all_matches(_EQUIPMENT_PATTERNS, narrative),
    )
