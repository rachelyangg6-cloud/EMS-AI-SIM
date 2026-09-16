import re
from pathlib import Path
from typing import Optional

import yaml

from ems.extraction import extract_source_text
from ems.models import SourceMeta
from ems.paths import raw_dir


def slugify(text: str) -> str:
    """Lowercase kebab-case slug from arbitrary text."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "source"


def create_source(
    file_path: Path,
    sop_id: Optional[str] = None,
    effective_date: Optional[str] = None,
    dest_dir: Optional[Path] = None,
) -> SourceMeta:
    """Extract a source file into a raw note (status: new) and return its meta.

    The raw note holds the extracted text as its body plus tracking frontmatter.
    Ingest later scans for these notes by their ``status: new`` marker.
    """
    dest = dest_dir or raw_dir()
    dest.mkdir(parents=True, exist_ok=True)

    text = extract_source_text(file_path)
    slug = slugify(file_path.stem)

    frontmatter = {
        "source_type": file_path.suffix.lstrip(".").lower() or "text",
        "filename": file_path.name,
        "sop_id": sop_id or "",
        "effective_date": effective_date or "",
        "status": "new",
    }
    fm_text = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)

    out_path = dest / f"{slug}.md"
    out_path.write_text(f"---\n{fm_text}---\n\n{text}\n", encoding="utf-8")

    return SourceMeta(path=out_path, status="new", filename=file_path.name)
