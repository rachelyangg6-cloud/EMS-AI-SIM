import re
from typing import Optional


def get_section(body: str, heading: str) -> Optional[str]:
    """Return content of a ## section, or None if the heading is not found."""
    pattern = rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, body, re.MULTILINE | re.DOTALL)
    if not match:
        return None
    return match.group(1).rstrip("\n")


def replace_section(body: str, heading: str, new_content: str) -> str:
    """Replace the content of a ## section. Returns body unchanged if heading not found."""
    new_content = new_content.strip("\n") + "\n"
    pattern = rf"(^##\s+{re.escape(heading)}\s*\n)(.*?)(?=^##\s|\Z)"
    return re.sub(pattern, rf"\g<1>{new_content}", body, flags=re.MULTILINE | re.DOTALL)


def extract_wikilinks(body: str) -> list[str]:
    """Return slugs from all [[wikilink]] patterns in the body."""
    return re.findall(r"\[\[([^\]]+)\]\]", body)


def extract_h2_headings(body: str) -> list[str]:
    """Return ordered list of ## heading texts found in the body."""
    return [m.group(1).strip() for m in re.finditer(r"^##\s+(.+)$", body, re.MULTILINE)]
