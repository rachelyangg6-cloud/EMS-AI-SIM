import json
import re


def parse_llm_json(text: str) -> dict:
    """Parse a JSON object from an LLM response, tolerating stray prose or
    ```json fences around it. Raises ValueError if no object can be found."""
    text = text.strip()
    # Strip markdown code fences if present.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back to the first {...} block in the response.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError(f"No JSON object found in LLM response: {text[:200]!r}")
