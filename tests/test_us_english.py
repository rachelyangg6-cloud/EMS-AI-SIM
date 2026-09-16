"""The corpus and the interface are US English, because the source material is.

Swept by hand twice — source 24, then again after a British spelling reached a
scenario the EMT was reading on screen. A third sweep is a failing process, so
the rule lives here instead.

`raw/` is excluded: it is OCR of the source book and must stay a faithful
transcription, not a corrected one.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: British form → the US form to use instead. Prefix matches, so "authoris"
#: catches authorise/authorised/authorising.
BRITISH = {
    "authoris": "authoriz",
    "recognis": "recogniz",
    "colour": "color",
    "behaviour": "behavior",
    "practis": "practic",
    "haemo": "hemo",
    "oedema": "edema",
    "anaemi": "anemi",
    "paediatr": "pediatr",
    "oesophag": "esophag",
    "manoeuvr": "maneuver",
    "sulph": "sulf",
    "litre": "liter",
    "defence": "defense",
    "licence": "license",
    "whilst": "while",
    "amongst": "among",
}
#: Needs a boundary at the end too, or a correct word gets flagged: "centre"
#: must not fire inside "central", and "grey" must not catch "greyhound".
BRITISH_WHOLE_WORD = {"centre": "center", "grey": "gray", "cancelled": "canceled",
                      "travelled": "traveled"}

#: "organise" is British; "organism" is not, and the infection sources are full
#: of the latter. A prefix rule cannot tell them apart, so this one is explicit.
BRITISH_LOOKAHEAD = {"organis(?!m)": "organiz"}

SUFFIXES = {".md", ".py", ".ts", ".tsx", ".css", ".yaml", ".json"}
SKIP = {"raw", "node_modules", "dist", ".git", ".venv", "var",
        # A generated copy of wiki/. Testing it would flag every hit twice
        # and point at a file whose fix belongs upstream.
        "obsidian_wiki"}

_PATTERN = re.compile(
    "|".join(
        [rf"\b{w}\w*" for w in BRITISH]
        + [rf"\b{w}\b" for w in BRITISH_WHOLE_WORD]
        + [rf"\b{w}\w*" for w in BRITISH_LOOKAHEAD]
    ),
    re.IGNORECASE,
)


def _files():
    for path in ROOT.rglob("*"):
        if path.suffix not in SUFFIXES or not path.is_file():
            continue
        if SKIP & set(path.relative_to(ROOT).parts):
            continue
        # This file names every British spelling on purpose.
        if path.name == Path(__file__).name:
            continue
        yield path


@pytest.mark.parametrize("path", sorted(_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_british_spellings(path):
    hits = _PATTERN.findall(path.read_text(encoding="utf-8", errors="ignore"))
    assert not hits, f"{path.relative_to(ROOT)} uses {sorted(set(hits))}"
