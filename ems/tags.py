"""What a scenario is *about*, in words an EMT would use.

A scenario used to be placed by its source alone. That works for the 283 cases
written out of a source and not at all for a generated draft, which is grounded
in a handful of wiki pages and belongs to no source — the field was simply
missing, and the schema rejected the file.

So placement is now a tag, and `source_index` is optional. Tags are drawn from
`scenario_tags` in `system/source-vocabulary.json`, the same way conditions,
procedures and medications are, because free text would give us "heart attack",
"Heart Attack" and "MI" as three separate topics inside a month.

**These tables seed a tag; they do not own it.** A newly written
scenario gets its tags from here once, and the value then lives in the file.
Correcting one afterwards is an edit to that file, not a change to this module —
which matters, because a source-derived tag is only as specific as the source.
"""

import json
from functools import lru_cache

from ems.paths import get_wiki_root


@lru_cache(maxsize=1)
def valid_tags() -> frozenset[str]:
    """The controlled list. A tag outside it is a typo, and a test says so."""
    path = get_wiki_root() / "system" / "source-vocabulary.json"
    return frozenset(json.loads(path.read_text(encoding="utf-8"))["scenario_tags"])


#: Condition slug → the topics a case about it belongs under.
#:
#: What is actually wrong with the patient. A few slugs carry two: a GI bleed is
#: an abdominal complaint *and* a bleeding patient, and someone searching either
#: should find it.
CONDITION_TAGS: dict[str, tuple[str, ...]] = {
    "abdominal-pain": ("abdominal emergency",),
    "acute-mi": ("heart attack and chest pain",),
    "acute-psychosis": ("behavioral and psychiatric",),
    "altered-mental-status": ("stroke and altered mental status",),
    "amputation": ("soft-tissue trauma",),
    "anaphylaxis": ("allergic reaction",),
    "anemia": ("kidney and blood disorders",),
    "aneurysm": ("heart attack and chest pain",),
    "aortic-dissection": ("heart attack and chest pain",),
    "appendicitis": ("abdominal emergency",),
    "asthma": ("respiratory emergency",),
    "avulsion": ("soft-tissue trauma",),
    "behavioral-emergency": ("behavioral and psychiatric",),
    "burn": ("soft-tissue trauma",),
    "cardiac-arrest": ("cardiac arrest",),
    "cardiogenic-shock": ("bleeding and shock", "heart attack and chest pain"),
    "chemical-burn": ("soft-tissue trauma",),
    "chest-pain": ("heart attack and chest pain",),
    "cholecystitis": ("abdominal emergency",),
    "closed-wound": ("soft-tissue trauma",),
    "coagulopathy": ("kidney and blood disorders",),
    "crush-syndrome": ("soft-tissue trauma",),
    "diabetic-ketoacidosis": ("diabetic emergency",),
    "dialysis-complication": ("kidney and blood disorders",),
    "distributive-shock": ("bleeding and shock",),
    "drowning": ("environmental emergency",),
    "autism-spectrum": ('special challenges', 'behavioral and psychiatric'),
    "child-abuse": ('abuse and neglect', 'special challenges'),
    "elder-abuse": ('abuse and neglect', 'special challenges'),
    "human-trafficking": ('abuse and neglect',),
    "vp-shunt-malfunction": ('special challenges', 'stroke and altered mental status'),
    "breech-presentation": ('pregnancy and childbirth',),
    "eclampsia": ('pregnancy and childbirth', 'stroke and altered mental status'),
    "ectopic-pregnancy": ('pregnancy and childbirth', 'abdominal emergency', 'bleeding and shock'),
    "meconium-staining": ('pregnancy and childbirth', 'airway and breathing'),
    "miscarriage": ('pregnancy and childbirth', 'bleeding and shock'),
    "postpartum-hemorrhage": ('pregnancy and childbirth', 'bleeding and shock'),
    "premature-birth": ('pregnancy and childbirth',),
    "prolapsed-umbilical-cord": ('pregnancy and childbirth',),
    "sexual-assault": ('gynecologic emergency', 'behavioral and psychiatric'),
    "supine-hypotensive-syndrome": ('pregnancy and childbirth', 'bleeding and shock'),
    "third-trimester-bleeding": ('pregnancy and childbirth', 'bleeding and shock'),
    "trauma-in-pregnancy": ('pregnancy and childbirth', 'multisystem trauma'),
    "decompression-sickness": ('environmental emergency',),
    "frostbite": ('environmental emergency', 'soft-tissue trauma'),
    "heat-exhaustion": ('environmental emergency',),
    "heat-stroke": ('environmental emergency', 'stroke and altered mental status'),
    "high-altitude-illness": ('environmental emergency', 'respiratory emergency'),
    "snakebite": ('environmental emergency', 'soft-tissue trauma'),
    "electrical-injury": ("environmental emergency",),
    "epistaxis": ("bleeding and shock",),
    "excited-delirium": ("behavioral and psychiatric",),
    "foreign-body-airway-obstruction": ("airway and breathing",),
    "gi-bleed": ("abdominal emergency", "bleeding and shock"),
    "hemorrhagic-shock": ("bleeding and shock",),
    "hernia": ("abdominal emergency",),
    "hyperglycemia": ("diabetic emergency",),
    "hypertensive-emergency": ("heart attack and chest pain",),
    "hypertrophic-cardiomyopathy": ("heart attack and chest pain",),
    "hypoglycemia": ("diabetic emergency",),
    "hypothermia": ("environmental emergency",),
    "hypovolemic-shock": ("bleeding and shock",),
    "hypoxia": ("airway and breathing",),
    "internal-bleeding": ("bleeding and shock",),
    "obstructive-shock": ("bleeding and shock",),
    "open-wound": ("soft-tissue trauma",),
    "multisystem-trauma": ("multisystem trauma", "bleeding and shock"),
    "air-embolism": ("head and spine trauma", "airway and breathing"),
    "brain-contusion": ("head and spine trauma", "stroke and altered mental status"),
    "concussion": ("head and spine trauma", "stroke and altered mental status"),
    "epidural-hematoma": ("head and spine trauma", "stroke and altered mental status"),
    "facial-fracture": ("head and spine trauma", "airway and breathing"),
    "increased-intracranial-pressure": ("head and spine trauma", "stroke and altered mental status"),
    "mandible-fracture": ("head and spine trauma", "airway and breathing"),
    "neurogenic-shock": ("head and spine trauma", "bleeding and shock"),
    "open-neck-wound": ("head and spine trauma", "bleeding and shock"),
    "skull-fracture": ("head and spine trauma", "stroke and altered mental status"),
    "spinal-column-injury": ("head and spine trauma",),
    "spinal-cord-injury": ("head and spine trauma",),
    "subdural-hematoma": ("head and spine trauma", "stroke and altered mental status"),
    "compartment-syndrome": ("musculoskeletal trauma", "bleeding and shock"),
    "dislocation": ("musculoskeletal trauma",),
    "femoral-shaft-fracture": ("musculoskeletal trauma", "bleeding and shock"),
    "fracture": ("musculoskeletal trauma",),
    "hip-dislocation": ("musculoskeletal trauma",),
    "hip-fracture": ("musculoskeletal trauma",),
    "knee-dislocation": ("musculoskeletal trauma",),
    "open-fracture": ("musculoskeletal trauma", "soft-tissue trauma"),
    "pelvic-fracture": ("musculoskeletal trauma", "bleeding and shock"),
    "shoulder-dislocation": ("musculoskeletal trauma",),
    "sprain": ("musculoskeletal trauma",),
    "strain": ("musculoskeletal trauma",),
    "abdominal-trauma": ("chest and abdominal trauma", "abdominal emergency"),
    "cardiac-contusion": ("chest and abdominal trauma", "heart attack and chest pain"),
    "cardiac-tamponade": ("chest and abdominal trauma", "bleeding and shock"),
    "evisceration": ("chest and abdominal trauma", "abdominal emergency"),
    "flail-chest": ("chest and abdominal trauma", "airway and breathing"),
    "hemothorax": ("chest and abdominal trauma", "airway and breathing"),
    "pneumothorax": ("chest and abdominal trauma", "airway and breathing"),
    "pulmonary-contusion": ("chest and abdominal trauma", "airway and breathing"),
    "rib-fracture": ("chest and abdominal trauma", "airway and breathing"),
    "traumatic-asphyxia": ("chest and abdominal trauma", "airway and breathing"),
    "opioid-overdose": ("poisoning and overdose",),
    "pancreatitis": ("abdominal emergency",),
    "peritonitis": ("abdominal emergency",),
    "positional-asphyxia": ("airway and breathing",),
    "pulmonary-edema": ("respiratory emergency",),
    "renal-colic": ("kidney and blood disorders",),
    "renal-failure": ("kidney and blood disorders",),
    "respiratory-failure": ("respiratory emergency",),
    "seizure": ("stroke and altered mental status",),
    "sepsis": ("infection and sepsis",),
    "shock": ("bleeding and shock",),
    "sickle-cell-disease": ("kidney and blood disorders",),
    "stroke": ("stroke and altered mental status",),
    "suicidal-ideation": ("behavioral and psychiatric",),
    "syncope": ("stroke and altered mental status",),
    "tension-pneumothorax": ("chest and abdominal trauma", "respiratory emergency"),
    "traumatic-arrest": ("cardiac arrest",),
    # The head injury itself belongs with head trauma, which is source 33 and
    # not ingested yet. Until it is, what these cases actually turn on is the
    # falling mental status.
    "traumatic-brain-injury": ("head and spine trauma", "stroke and altered mental status"),
    "urinary-tract-infection": ("infection and sepsis", "kidney and blood disorders"),
}

#: Source → topic, from the source's own title in the resource.
#:
#: What the case was written to *teach*, which is not always what is wrong with
#: the patient — and both are worth being findable by. A quarter of the corpus
#: carries a source topic its conditions do not imply: src13-s08 is a vital
#: signs scenario about an airway patient, and someone filtering for assessment
#: practice should get it. It also covers the 112 scenarios that name no
#: condition at all, nearly all in the foundational sources, where the subject
#: is a skill rather than a disease.
SOURCE_TAGS: dict[int, tuple[str, ...]] = {
    1: ("EMS systems and roles",),
    2: ("EMT well-being",),
    3: ("scene safety and lifting",),
    4: ("legal and ethical",),
    5: ("anatomy and terminology",),
    6: ("anatomy and terminology",),
    7: ("anatomy and terminology",),
    8: ("life span and development",),
    9: ("airway and breathing",),
    10: ("airway and breathing",),
    # Sizing up a scene is both halves at once: it opens the assessment and it
    # is where the safety call gets made.
    11: ("patient assessment", "scene safety and lifting"),
    12: ("patient assessment",),
    13: ("patient assessment",),
    14: ("patient assessment",),
    15: ("patient assessment",),
    16: ("patient assessment",),
    17: ("communication and records",),
    18: ("medication and pharmacology",),
    19: ("respiratory emergency",),
    20: ("heart attack and chest pain",),
    21: ("cardiac arrest",),
    22: ("diabetic emergency",),
    23: ("allergic reaction",),
    24: ("infection and sepsis",),
    25: ("poisoning and overdose",),
    26: ("abdominal emergency",),
    27: ("behavioral and psychiatric",),
    28: ("kidney and blood disorders",),
    29: ("bleeding and shock",),
    30: ("soft-tissue trauma",),
    31: ("chest and abdominal trauma",),
    32: ("musculoskeletal trauma",),
    33: ("head and spine trauma",),
    34: ("multisystem trauma",),
    35: ("environmental emergency",),
    36: ("pregnancy and childbirth",),
    37: ("special challenges",),
    38: ("EMS systems and roles",),
}


class UntaggableScenario(Exception):
    """Nothing in the file says what it is about. Raised rather than guessed."""


def tags_for(frontmatter: dict) -> list[str]:
    """The tags a scenario should carry, sorted and deduplicated.

    Both sources contribute, rather than the source only filling in when there
    is no condition. What is wrong with the patient and what the case was
    written to teach are different questions, and a scenario should be findable
    by either answer.

    Ending up with nothing is not a result worth writing an empty list for — a
    scenario nobody can find is what this field exists to prevent — so it raises.
    """
    tags: set[str] = set()
    for slug in frontmatter.get("conditions") or ():
        tags.update(CONDITION_TAGS.get(slug, ()))

    source_index = frontmatter.get("source_index")
    if source_index is not None and source_index not in SOURCE_TAGS:
        raise UntaggableScenario(
            f"source {source_index} is not in SOURCE_TAGS — add it there with the "
            f"source's own title as the comment"
        )
    tags.update(SOURCE_TAGS.get(source_index, ()))

    if not tags:
        raise UntaggableScenario(
            "no condition slug maps to a tag and there is no source either; "
            "tag this one by hand"
        )
    return sorted(tags)
