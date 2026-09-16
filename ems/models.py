from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SourceMeta:
    path: Path
    status: str       # "new" | "ingested" | "error"
    filename: str


@dataclass(frozen=True)
class SourceSummary:
    clinical_summary: str
    conditions_addressed: tuple[str, ...]
    red_flags_mentioned: tuple[str, ...]
    medications_referenced: tuple[str, ...]
    scope_level: str  # "EMT-B" | "AEMT" | "Paramedic"
    sop_id: Optional[str] = None
    effective_date: Optional[str] = None


@dataclass(frozen=True)
class RoutingResult:
    target_pages: tuple[str, ...]   # wiki page slugs
    sections: tuple[str, ...]       # parallel list of section headings
    reason: str


@dataclass(frozen=True)
class PagePatch:
    page_slug: str
    page_type: str
    section_heading: str
    new_content: str


@dataclass(frozen=True)
class Scenario:
    """A rich OSCE-style training scenario generated from a resource.

    Generated scenarios start unverified; the labeling skill turns them into
    expertise-marked facts once an EMT reviews/corrects them.
    """
    dispatch: str                              # the call as it comes in
    presentation: str                          # what you find on scene
    vitals: str                                # initial vital signs
    correct_action_sequence: tuple[str, ...]   # ordered correct EMT actions
    scope_level: str                           # EMT-B | AEMT | Paramedic
    rationale: str                             # why this is the correct response
    age_group: str = "adult"                   # neonate | pediatric | adult | geriatric
    red_flags: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()            # [SRC-{n}:p{NN}]
    conditions: tuple[str, ...] = ()           # vocabulary slugs (cross-links)
    procedures: tuple[str, ...] = ()
    medications: tuple[str, ...] = ()
