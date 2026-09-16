"""Re-skin a vetted scenario: same call, different patient.

150 approved scenarios is a small corpus to practice against — a trainee who
runs `src19-s02` three times is remembering it, not working it. Re-skinning
changes who the patient is and where the call happens while leaving the
clinical case exactly as an EMT vetted it.

**The safety property is structural, not prompted.** The new body is built by
replacing the two narrative sections in the original; everything else is carried
across verbatim because it is never rewritten. `validate_reskin` then re-checks
that byte-for-byte, and additionally re-derives the `SceneSpec` to confirm the
patient is still clinically the same person. The model can change a name; it
cannot change a respiratory rate.
"""

import os
from typing import Callable, Optional

from ems.config import SIM_PERSONA_MODEL
from ems.json_utils import parse_llm_json
from ems.llm import call_llm
from ems.markdown import get_section, replace_section
from ems.sim.scene import derive_scene

#: Rewritten by a re-skin. Everything else is frozen.
MUTABLE_SECTIONS = ("Dispatch", "Presentation")

#: Carried across verbatim. `Vitals` is here because the numbers drive both the
#: grading and the animation — a re-skin changes the story, not the physiology.
FROZEN_SECTIONS = ("Vitals", "Correct actions", "Rationale", "Red flags", "Related")


class ReskinError(ValueError):
    """A re-skin changed something it is not allowed to change."""


_SYSTEM = (
    "You re-skin EMS training scenarios. You are given the dispatch line and "
    "the on-scene description of a real, EMT-vetted case. Rewrite both so the "
    "patient is a different person in a different setting, while every "
    "clinical fact stays exactly the same.\n\n"
    "You MAY change: the patient's name, sex, occupation, the location, the "
    "time of day, who else is present, and the incidental details of how the "
    "call came in.\n\n"
    "You MUST NOT change: the patient's age band, posture, skin color, work of "
    "breathing, level of responsiveness, or any sign, symptom, or number. If the "
    "original says the patient is slumped, cyanotic, and drowsy, yours is too. "
    "Do not add findings that were not there and do not drop findings that were.\n\n"
    'Reply with JSON only: {"dispatch": "...", "presentation": "..."}'
)


def reskin_prompt(dispatch: str, presentation: str, age_group: str) -> str:
    return (
        f"Age group (must not change): {age_group}\n\n"
        f"## Dispatch\n{dispatch}\n\n"
        f"## Presentation\n{presentation}"
    )


def reskin(
    frontmatter: dict,
    body: str,
    llm: Callable = call_llm,
    model: Optional[str] = None,
) -> str:
    """Return a re-skinned body. Raises `ReskinError` if the result is unsafe."""
    dispatch = (get_section(body, "Dispatch") or "").strip()
    presentation = (get_section(body, "Presentation") or "").strip()
    if not dispatch or not presentation:
        raise ReskinError("scenario has no Dispatch/Presentation to re-skin")

    data = parse_llm_json(
        llm(
            reskin_prompt(dispatch, presentation, frontmatter.get("age_group", "adult")),
            system=_SYSTEM,
            model=model or os.environ.get("EMS_PERSONA_MODEL", SIM_PERSONA_MODEL),
        )
    )
    new_dispatch = str(data.get("dispatch", "")).strip()
    new_presentation = str(data.get("presentation", "")).strip()
    if not new_dispatch or not new_presentation:
        raise ReskinError("re-skin returned an empty dispatch or presentation")

    # Built by replacement: the frozen sections are never regenerated, so they
    # cannot drift. The validator below re-checks that anyway.
    new_body = replace_section(body, "Dispatch", new_dispatch)
    new_body = replace_section(new_body, "Presentation", new_presentation)

    validate_reskin(frontmatter, body, new_body)
    return new_body


def validate_reskin(frontmatter: dict, original: str, candidate: str) -> None:
    """Raise unless the candidate is the same clinical case as the original."""
    for heading in FROZEN_SECTIONS:
        before, after = get_section(original, heading), get_section(candidate, heading)
        if before != after:
            raise ReskinError(f"re-skin altered the frozen '## {heading}' section")

    for heading in MUTABLE_SECTIONS:
        if get_section(candidate, heading) is None:
            raise ReskinError(f"re-skin dropped the '## {heading}' section")

    before_patient = derive_scene(frontmatter, original).patient
    after_patient = derive_scene(frontmatter, candidate).patient
    if before_patient != after_patient:
        raise ReskinError(
            "re-skin changed the patient's clinical presentation: "
            f"{_diff(before_patient, after_patient)}"
        )


def _diff(before, after) -> str:
    if before is None or after is None:
        return f"{before!r} → {after!r}"
    changed = [
        f"{f}: {getattr(before, f)!r} → {getattr(after, f)!r}"
        for f in type(before).__dataclass_fields__
        if getattr(before, f) != getattr(after, f)
    ]
    return "; ".join(changed)


def reskinned_frontmatter(frontmatter: dict) -> dict:
    """Frontmatter for a re-skinned copy: unchanged, plus provenance."""
    return {**frontmatter, "reskinned_from": frontmatter.get("scenario_id", "")}
