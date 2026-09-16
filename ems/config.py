SCOPE_LEVELS = ("EMT-B", "AEMT", "Paramedic")
VALID_STATUSES = ("active", "superseded", "draft")

DIR_TO_TYPE = {
    "protocols":  "protocol",
    "conditions": "condition",
    "medications": "medication",
    "procedures": "procedure",
}

TYPE_TO_DIR = {v: k for k, v in DIR_TO_TYPE.items()}

SECTIONS_BY_PAGE_TYPE = {
    "protocol": [
        "When it applies",
        "Steps",
        "Medications & doses",
        "Scope boundaries",
        "Red flags",
        "Transport decision",
    ],
    "condition": [
        "Recognition",
        "Differentials",
        "Assessment",
        "Field management",
        "When to escalate (ALS)",
    ],
    "medication": [
        "Indications",
        "Adult dose",
        "Pediatric dose",
        "Route",
        "Contraindications",
        "Scope boundary",
    ],
    "procedure": [
        "When to use",
        "Steps",
        "Common errors",
        "Documentation",
    ],
}

RELATIONSHIP_RULES = [
    {
        "source_type": "protocol",
        "field": "treats_conditions",
        "target_type": "condition",
        "edges": ["treats", "treated_by"],
    },
    {
        "source_type": "protocol",
        "field": "medications",
        "target_type": "medication",
        "edges": ["administers", "administered_in"],
    },
    {
        "source_type": "condition",
        "field": "procedures",
        "target_type": "procedure",
        "edges": ["assessed_by", "assesses"],
    },
    {
        "source_type": "medication",
        "field": "contraindicated_conditions",
        "target_type": "condition",
        "edges": ["contraindicated_in", "contraindicates"],
    },
]

AUTO_LIST_FIELDS = {
    "protocol":  ["treats_conditions", "medications", "linked_pages"],
    "condition": ["protocols", "red_flags", "linked_pages"],
    "medication": ["used_in_protocols", "contraindicated_conditions", "linked_pages"],
    "procedure": ["conditions", "linked_pages"],
}

REQUIRED_NONEMPTY_ACTIVE = {
    "protocol":  {"title", "sop_id", "scope_level", "effective_date", "status"},
    "condition": {"title", "scope_level", "status"},
    "medication": {"title", "scope_level", "effective_date", "status"},
    "procedure": {"title", "scope_level", "status"},
}

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# LLM provider. Build phase uses the Claude API; a local-Ollama SLM swap is a
# future (offline) stage — see the implementation plan.
ANTHROPIC_MODEL = "claude-opus-4-8"
# Future local path: OLLAMA_BASE_URL = "http://localhost:11434/v1"; OLLAMA_MODEL = "mistral"

# Simulator model tiering. Personas talk a lot and say little that is hard —
# a fast model is the right tool. Grading reads a rubric and judges clinical
# performance, so it gets the strong one. Override with EMS_PERSONA_MODEL /
# EMS_GRADER_MODEL.
SIM_PERSONA_MODEL = "claude-sonnet-5"
SIM_GRADER_MODEL = "claude-opus-5"
