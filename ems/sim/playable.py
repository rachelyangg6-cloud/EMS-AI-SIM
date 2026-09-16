"""Which approved scenarios can actually be played as a ride-along call.

The wiki holds two kinds of vetted scenario and only one of them is a call.

`kind: patient-care` means there is a patient you are dispatched to, assess and
treat. The other kinds — provider-safety, medical-legal, operational,
documentation-qi, communication, public-health — are real EMS competencies and
worth keeping, but they have no patient, so the simulator has nothing to put on
the stretcher. Playing one produces the transcript that prompted this module:

    TONE_OUT  Medic 41, respond for: Back at the station after transporting a
              patient with a sensitive diagnosis (AIDS).

Being `patient-care` is necessary and not sufficient. Two of the three sessions
that exposed this were tagged patient-care and still unplayable, because a call
also needs:

  * a dispatch that says who the patient is and what is wrong — otherwise the
    trainee arrives with no thread to follow (reused from `context_check`); and
  * a Presentation written as a scene you walk into rather than a teaching frame
    addressed to the reader. "You are preparing to secure a 6-year-old to a
    backboard" cannot be narrated on arrival, because it describes something the
    trainee is supposedly already doing.

Nothing here deletes or edits a scenario. Excluded files stay exactly where they
are and keep serving retrieval and `/query`; this only decides what the
simulator is willing to deal.
"""
from pathlib import Path

from ems.cli.context_check import _PERSON_RE, problems
from ems.frontmatter import read_page
from ems.markdown import get_section
from ems.scenarios import list_approved
from ems.sim.session import _SECOND_PERSON_RE, _sentences


def unplayable(frontmatter: dict, body: str) -> list[str]:
    """Why this scenario cannot be played as a call. Empty means it can."""
    reasons = []

    kind = frontmatter.get("kind", "patient-care")
    if kind != "patient-care":
        reasons.append(f"kind is {kind} — no patient to assess")

    # `problems` is an editorial worklist, and not all of it is disqualifying.
    # "no age or life stage" fires on "Adult with an asthma attack, short of
    # breath" — which is a perfectly good tone-out that simply does not give a
    # number. Gating on it cut the pool to 58 and threw away 37 playable calls.
    # Naming *nobody* does leave the trainee with no thread to follow, so that
    # still blocks.
    #
    # "mechanism only, no complaint" is a real authoring signal and a bad gate.
    # Some calls have no complaint on purpose: a scene size-up is dispatched as
    # a mechanism because the point is to read the mechanism before touching
    # anyone, and src11-s09 turns on a worker who fell fifteen feet and says he
    # feels fine. Withholding the complaint IS the lesson there, so once the
    # tone-out says who is involved, the trainee has their thread and the
    # simulator has a patient. It stays in the worklist for `context-check`,
    # where an author can still be told the dispatch is thin.
    ignore = {"no age or life stage"}
    dispatch = (get_section(body, "Dispatch") or "").strip()
    if _PERSON_RE.search(dispatch):
        ignore.add("mechanism only, no complaint")
    reasons += [
        f"dispatch {p}" for p in problems(frontmatter, body) if p not in ignore
    ]

    opening = next(iter(_sentences(get_section(body, "Presentation") or "")), "")
    if _SECOND_PERSON_RE.match(opening):
        reasons.append("presentation is a teaching frame, not a scene")

    return reasons


def playable_cases(**kwargs) -> list[Path]:
    """`list_approved`, minus everything that cannot be played as a call."""
    return [p for p in list_approved(**kwargs) if not unplayable(*read_page(p))]
