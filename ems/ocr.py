from pathlib import Path

# Fragments whose vertical centers differ by more than this (in normalized page
# height) are treated as separate lines.
_LINE_BAND = 0.012


def ocr_image(image_path: Path, recognition_level: str = "accurate") -> str:
    """OCR a page image with Apple Vision (via ocrmac). Local and offline.

    Reconstructs reading order from Vision's per-fragment bounding boxes:
    top-to-bottom, then left-to-right. Vision's coordinate origin is the
    bottom-left corner, so a larger y is higher on the page.
    """
    try:
        from ocrmac import ocrmac
    except ImportError:
        raise ImportError("ocrmac required: pip install ocrmac")

    annotations = ocrmac.OCR(
        str(image_path), recognition_level=recognition_level
    ).recognize()
    return _reconstruct(annotations)


def _reconstruct(annotations: list) -> str:
    """Order (text, confidence, (x, y, w, h)) fragments into readable text."""
    frags = []
    for text, _conf, (x, y, _w, h) in annotations:
        if text.strip():
            frags.append((y + h / 2, x, text))

    # Top of page first (largest y), then left to right within a line band.
    frags.sort(key=lambda f: (-f[0], f[1]))

    lines: list[list[str]] = []
    last_y = None
    for y_center, _x, text in frags:
        if last_y is None or abs(y_center - last_y) > _LINE_BAND:
            lines.append([text])
            last_y = y_center
        else:
            lines[-1].append(text)
    return "\n".join(" ".join(line) for line in lines)
