import json
from pathlib import Path
from typing import Optional

from ems.paths import vocabulary_path


def load_vocabulary(path: Optional[Path] = None) -> dict:
    """Load the source vocabulary JSON. Uses default path if none given."""
    p = path or vocabulary_path()
    return json.loads(p.read_text(encoding="utf-8"))


def save_vocabulary(vocab: dict, path: Optional[Path] = None) -> None:
    """Write the vocabulary dict back to disk."""
    p = path or vocabulary_path()
    p.write_text(json.dumps(vocab, indent=2, ensure_ascii=False), encoding="utf-8")


def get_conditions(path: Optional[Path] = None) -> list[str]:
    return load_vocabulary(path).get("conditions", [])


def get_medications(path: Optional[Path] = None) -> list[str]:
    return load_vocabulary(path).get("medications", [])


def get_procedures(path: Optional[Path] = None) -> list[str]:
    return load_vocabulary(path).get("procedures", [])


def get_scope_levels(path: Optional[Path] = None) -> list[str]:
    return load_vocabulary(path).get("scope_levels", [])


def extract_pdf_header(pdf_path: Path, max_chars: int = 800) -> str:
    """Extract the first page of a PDF as plain text (max_chars limit).

    Uses pdfminer.six — text only, ignores vector graphics and diagrams.
    Intended for catching SOP-ID, effective date, and title from the cover page.
    """
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        raise ImportError("pdfminer.six required: pip install pdfminer.six")

    text = extract_text(str(pdf_path), page_numbers=[0], maxpages=1)
    return text[:max_chars].strip()
