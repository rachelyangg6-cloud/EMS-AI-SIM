"""protocol-add-resource — extract EMT resources into raw notes (status: new).

Source N is looked up in the resources directory as, in order:

    source_<N>/       a folder of page PNGs, OCR'd locally with Apple Vision
    source_<N>.pdf    a text PDF, one [p.NN] marker per PDF page
    source_<N>.txt    plain text, pages split on form feeds (none → one page)
    chapter_<N>/      a page folder named before the rename

Progress goes to stderr; extracted text is written to the raw note files and
never dumped to stdout.
"""
import argparse
import sys
from pathlib import Path
from typing import Optional

from ems.resource import create_resource_note


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="protocol-add-resource",
        description="Extract resources (page PNG folders, PDFs, .txt) into raw source notes.",
    )
    parser.add_argument(
        "resources_dir",
        type=Path,
        help="Directory containing source_<N>/ page-PNG folders, source_<N>.pdf or source_<N>.txt",
    )
    parser.add_argument(
        "--sources",
        default="1-4",
        help="Source range or list, e.g. '1-4' or '1,3' (default: 1-4)",
    )
    args = parser.parse_args()

    sources = _parse_sources(args.sources)
    rc = 0
    for n in sources:
        resource_path = find_resource(args.resources_dir, n)
        if resource_path is None:
            print(f"skip: no source_{n}/, source_{n}.pdf or source_{n}.txt in "
                  f"{args.resources_dir}", file=sys.stderr)
            rc = 1
            continue
        print(f"extract source {n}: {resource_path} ...", file=sys.stderr)
        try:
            meta = create_resource_note(resource_path, n)
        except ValueError as error:
            print(f"  skip: {error}", file=sys.stderr)
            rc = 1
            continue
        print(f"  wrote {meta.path} (status: {meta.status})", file=sys.stderr)
    return rc


def find_resource(resources_dir: Path, n: int) -> Optional[Path]:
    """Source N in the order the module docstring lists, or None."""
    folders = [resources_dir / f"source_{n}", resources_dir / f"chapter_{n}"]
    files = [resources_dir / f"source_{n}.pdf", resources_dir / f"source_{n}.txt"]
    if folders[0].is_dir():
        return folders[0]
    for path in files:
        if path.is_file():
            return path
    return folders[1] if folders[1].is_dir() else None


def _parse_sources(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        elif part:
            out.append(int(part))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
