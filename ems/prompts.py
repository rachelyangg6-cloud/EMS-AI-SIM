"""
All LLM prompt templates in one place.
Functions return fully-formed strings ready to pass to call_llm().
"""


def summarize_source_prompt(source_text: str, vocabulary: dict) -> str:
    conditions = ", ".join(vocabulary.get("conditions", []))
    medications = ", ".join(vocabulary.get("medications", []))
    scope_levels = ", ".join(vocabulary.get("scope_levels", []))
    return f"""You are a clinical analyst reviewing an EMS source document.
Extract the following information and return it as valid JSON only — no prose, no markdown fences.

Source document:
---
{source_text}
---

Approved condition slugs: {conditions}
Approved medication slugs: {medications}
Valid scope levels: {scope_levels}

Return exactly this JSON shape:
{{
  "clinical_summary": "<2-3 sentence plain-language summary of what this document covers>",
  "conditions_addressed": ["<slug>", ...],
  "red_flags_mentioned": ["<plain text red flag>", ...],
  "medications_referenced": ["<slug>", ...],
  "scope_level": "<EMT-B|AEMT|Paramedic>",
  "sop_id": "<SOP ID if present in document, else null>",
  "effective_date": "<YYYY-MM-DD if present, else null>"
}}

Use only slugs from the approved lists for conditions and medications.
scope_level must be the HIGHEST certification level mentioned in the document."""


def route_source_prompt(
    summary_json: str, existing_pages: list[str], source_kind: str = "sop"
) -> str:
    pages = "\n".join(f"  - {p}" for p in existing_pages)
    kind_rule = ""
    if source_kind == "resource":
        kind_rule = (
            "\n- This is educational reference material from a resource. Route only "
            "to condition and procedure pages (not protocol pages)."
        )
    return f"""You are routing an EMS source document to the correct wiki pages and sections.

Source summary:
{summary_json}

Existing wiki pages (slug format):
{pages}

Return valid JSON only — no prose, no markdown fences:
{{
  "target_pages": ["<slug>", ...],
  "sections": ["<exact ## heading text>", ...],
  "reason": "<one sentence explaining the routing decision>"
}}

Rules:
- target_pages and sections must be parallel arrays (same length)
- Only use section headings that exist in the schema for the page's type
- Prefer updating existing pages over creating new ones
- If a new page is needed, use a slug that matches the vocabulary{kind_rule}"""


def patch_section_prompt(
    page_title: str,
    section_heading: str,
    current_content: str,
    source_summary: str,
    source_text: str,
    sop_id: str,
    source_kind: str = "sop",
    source_index: int = None,
) -> str:
    if source_kind == "resource":
        citation_rule = (
            f"- Cite every clinical claim with [SRC-{source_index}:p<NN>], using the "
            "[p.NN] page markers in the source text to pick the page number"
        )
    else:
        citation_rule = f"- Cite every clinical claim with [{sop_id}:{section_heading}]"
    return f"""You are updating a section of an EMS protocol wiki page.
Write only the updated section content — no ## heading, no frontmatter, no surrounding text.

Page: {page_title}
Section: {section_heading}

Current section content:
---
{current_content or "(empty)"}
---

Source summary:
{source_summary}

Relevant source text:
---
{source_text}
---

Rules:
{citation_rule}
- Do not invent doses, steps, or interventions not in the source text
- Tag scope-restricted steps: [Paramedic only] or [AEMT only]
- Keep content to this section only — do not bleed into adjacent sections
- Use active voice and second person ("Administer..." not "It should be administered...")"""


def scenario_generation_prompt(
    resource_text: str, source_index: int, vocabulary: dict, n: int = 10
) -> str:
    conditions = ", ".join(vocabulary.get("conditions", []))
    procedures = ", ".join(vocabulary.get("procedures", []))
    medications = ", ".join(vocabulary.get("medications", []))
    scope_levels = ", ".join(vocabulary.get("scope_levels", []))
    age_groups = ", ".join(vocabulary.get("age_groups", []))
    return f"""You are an EMS educator writing realistic field training scenarios from a resource.
Generate exactly {n} distinct OSCE-style scenarios grounded ONLY in the source text below.
Return valid JSON only — no prose, no markdown fences.

Source {source_index} text (with [p.NN] page markers):
---
{resource_text}
---

Approved condition slugs: {conditions}
Approved procedure slugs: {procedures}
Approved medication slugs: {medications}
Valid scope levels: {scope_levels}
Valid age groups: {age_groups}

Return exactly this JSON shape:
{{
  "scenarios": [
    {{
      "dispatch": "<the 911 call / dispatch as it comes in>",
      "presentation": "<what the EMT finds on scene>",
      "vitals": "<initial vital signs>",
      "correct_action_sequence": ["<ordered correct EMT action>", ...],
      "scope_level": "<EMT-B|AEMT|Paramedic — highest cert the correct actions require>",
      "age_group": "<the patient's life stage, one of the valid age groups>",
      "rationale": "<why this is the correct response>",
      "red_flags": ["<warning sign>", ...],
      "citations": ["[SRC-{source_index}:p<NN>]", ...],
      "conditions": ["<slug>", ...],
      "procedures": ["<slug>", ...],
      "medications": ["<slug>", ...]
    }}
  ]
}}

Rules:
- Every clinical claim and dose must be supported by the source text — do not invent doses or steps
- Cite the page(s) with [SRC-{source_index}:p<NN>] using the [p.NN] markers
- Use only slugs from the approved lists for conditions/procedures/medications
- scope_level must match what the correct_action_sequence actually requires
- age_group is the patient's life stage; use "adult" unless the case is specifically about another stage
- When the source covers pediatric care, dedicate 1-2 of the {n} scenarios to age_group "pediatric" (or "neonate"); tag "geriatric" where the material is age-specific — but never invent age-specific content the source does not support
- Make the {n} scenarios cover different topics from the source"""


def query_prompt(question: str, context_pages: str, scope_level: str) -> str:
    return f"""You are an EMS protocol reference system answering a field query.
Answer ONLY from the provided protocol pages. Do not use outside knowledge.

Provider certification level: {scope_level}

Protocol pages:
---
{context_pages}
---

Question: {question}

Rules:
1. Every clinical claim must carry a citation copied verbatim from the pages —
   either [SOP-ID:Section] (e.g. [SOP-2024-CR-01:Steps]) or [SRC-n:pNN]
   (e.g. [SRC-3:p73]). Never write a citation that is not present above.
2. If the answer is not in the provided pages, respond with exactly:
   NOT IN PROVIDED PROTOCOLS
3. If an intervention is above the provider's scope ({scope_level}), flag it:
   [OUT OF SCOPE for {scope_level}] before describing it
4. Never invent doses, drug names, or steps
5. Be concise — field conditions do not allow for long answers"""
