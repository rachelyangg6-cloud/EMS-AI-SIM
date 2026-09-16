import re
from pathlib import Path
from typing import Optional

import yaml

from ems.models import SourceMeta
from ems.ocr import ocr_image
from ems.paths import raw_dir

# <page>.png or <page>_<part>.png ; ignores macOS AppleDouble ._* sidecars.
_PAGE_RE = re.compile(r"^(\d+)(?:_(\d+))?$")


def resource_pages(resource_dir: Path) -> list[tuple[int, list[Path]]]:
    """Ordered pages for a source, each with its split-part image files.

    A long page split into 85_0.png, 85_1.png groups under page 85 in part order.
    """
    pages: dict[int, list[tuple[int, Path]]] = {}
    for path in resource_dir.glob("*.png"):
        if path.name.startswith("._"):  # macOS AppleDouble sidecar
            continue
        m = _PAGE_RE.match(path.stem)
        if not m:
            continue
        page = int(m.group(1))
        part = int(m.group(2)) if m.group(2) is not None else 0
        pages.setdefault(page, []).append((part, path))

    ordered = []
    for page in sorted(pages):
        parts = [p for _, p in sorted(pages[page])]
        ordered.append((page, parts))
    return ordered


def ocr_resource(resource_dir: Path, ocr=ocr_image) -> str:
    """OCR every page of a source in reading order, with [p.NN] markers.

    The page markers back the [SRC-{n}:p{NN}] citation scheme used when
    the source is summarized and turned into scenarios.
    """
    blocks = []
    for page, part_paths in resource_pages(resource_dir):
        text = "\n".join(ocr(p) for p in part_paths).strip()
        blocks.append(f"[p.{page}]\n{text}")
    return "\n\n".join(blocks)


def paged_text(text: str) -> str:
    """[p.NN] blocks from text whose pages are separated by form feeds.

    pdfminer ends every PDF page with a form feed, so page N of the PDF becomes
    [p.N]. A plain-text file with no form feeds is a single page, [p.1].
    Empty pages keep their number so the ones after them still line up.
    """
    pages = text.split("\f")
    if len(pages) > 1 and not pages[-1].strip():
        pages.pop()
    return "\n\n".join(f"[p.{n}]\n{page.strip()}" for n, page in enumerate(pages, 1))


def pdf_resource(pdf_path: Path) -> str:
    """Extract a text PDF page by page, with [p.NN] markers.

    Raises on a PDF with no text layer rather than writing an empty note: a
    scanned PDF has to be exported as page images and OCR'd instead.
    """
    from pdfminer.high_level import extract_text

    text = extract_text(str(pdf_path))
    if not text.strip():
        raise ValueError(
            f"{pdf_path.name} has no text layer (scanned?) — export its pages as "
            f"PNGs into a source_<N>/ folder to OCR them"
        )
    return paged_text(text)


def extract_resource(resource_path: Path, ocr=ocr_image) -> str:
    """The text of a resource with [p.NN] markers, whatever form it arrives in:
    a folder of page PNGs (OCR), a PDF, or a .txt file."""
    if resource_path.is_dir():
        return ocr_resource(resource_path, ocr=ocr)
    suffix = resource_path.suffix.lower()
    if suffix == ".pdf":
        return pdf_resource(resource_path)
    if suffix == ".txt":
        return paged_text(resource_path.read_text(encoding="utf-8"))
    raise ValueError(f"unsupported resource: {resource_path} (expected a PNG folder, .pdf or .txt)")


def create_resource_note(
    resource_path: Path,
    source_index: int,
    dest_dir: Optional[Path] = None,
    ocr=ocr_image,
) -> SourceMeta:
    """Extract a resource into a raw note (status: new) for ingest.

    Unlike SOP sources there is no 50k char cap — a source is a coherent unit
    and truncating it would drop pages from citations and scenarios.
    """
    dest = dest_dir or raw_dir()
    dest.mkdir(parents=True, exist_ok=True)

    text = extract_resource(resource_path, ocr=ocr)
    frontmatter = {
        "source_type": "resource",
        "source_kind": "resource",
        "source_index": source_index,
        "filename": resource_path.name,
        "status": "new",
    }
    fm_text = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)

    out_path = dest / f"source-{source_index}.md"
    out_path.write_text(f"---\n{fm_text}---\n\n{text}\n", encoding="utf-8")
    return SourceMeta(path=out_path, status="new", filename=resource_path.name)
