from pathlib import Path

MAX_CHARS = 50_000


def extract_pdf_text(pdf_path: Path, max_chars: int = MAX_CHARS) -> str:
    """Extract the full text of a PDF (max_chars cap).

    Uses pdfminer.six — text only, ignores diagram/figure vector graphics so
    SOP PDFs don't bloat with extracted vector data.
    """
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        raise ImportError("pdfminer.six required: pip install pdfminer.six")

    text = extract_text(str(pdf_path))
    return text[:max_chars].strip()


def extract_source_text(path: Path, max_chars: int = MAX_CHARS) -> str:
    """Return the text of a source file. PDFs go through pdfminer; anything
    else is read as UTF-8 text."""
    if path.suffix.lower() == ".pdf":
        return extract_pdf_text(path, max_chars)
    return path.read_text(encoding="utf-8")[:max_chars].strip()
