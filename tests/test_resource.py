"""A resource arrives as page PNGs, a PDF, or a .txt — all end as [p.NN] blocks."""
import pytest
import yaml

from ems.cli.resource import find_resource
from ems.resource import create_resource_note, extract_resource


def _pdf(pages: list[str]) -> bytes:
    """A minimal text PDF, one line of Helvetica per page."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None,
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        content = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content} 0 R >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"

    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_a_pdf_gets_one_marker_per_page(tmp_path):
    path = tmp_path / "source_3.pdf"
    path.write_bytes(_pdf(["Scene safety first", "Open the airway"]))
    text = extract_resource(path)
    assert text.startswith("[p.1]\nScene safety first")
    assert "[p.2]\nOpen the airway" in text
    assert "[p.3]" not in text


def test_a_pdf_with_no_text_layer_is_refused(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(_pdf([""]))
    with pytest.raises(ValueError, match="no text layer"):
        extract_resource(path)


def test_a_txt_splits_on_form_feeds_and_keeps_empty_page_numbers(tmp_path):
    path = tmp_path / "source_1.txt"
    path.write_text("Page one.\fPage two.\f\fPage four.\f", encoding="utf-8")
    text = extract_resource(path)
    assert text == "[p.1]\nPage one.\n\n[p.2]\nPage two.\n\n[p.3]\n\n\n[p.4]\nPage four."


def test_a_txt_without_form_feeds_is_one_page(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Just one page.\n", encoding="utf-8")
    assert extract_resource(path) == "[p.1]\nJust one page."


def test_a_png_folder_is_still_ocrd_in_page_order(tmp_path):
    folder = tmp_path / "source_2"
    folder.mkdir()
    for name in ("10.png", "9_1.png", "9_0.png", "._9.png"):
        (folder / name).write_bytes(b"")
    text = extract_resource(folder, ocr=lambda p: p.stem)
    assert text == "[p.9]\n9_0\n9_1\n\n[p.10]\n10"


def test_the_note_records_the_file_it_came_from(tmp_path):
    source = tmp_path / "source_5.txt"
    source.write_text("Body.", encoding="utf-8")
    meta = create_resource_note(source, 5, dest_dir=tmp_path / "raw")
    fm = yaml.safe_load(meta.path.read_text().split("---")[1])
    assert meta.path.name == "source-5.md"
    assert fm["filename"] == "source_5.txt" and fm["source_index"] == 5


def test_unsupported_files_are_refused(tmp_path):
    path = tmp_path / "source_1.docx"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="unsupported"):
        extract_resource(path)


def test_lookup_prefers_the_png_folder_then_pdf_then_txt(tmp_path):
    assert find_resource(tmp_path, 1) is None
    (tmp_path / "chapter_1").mkdir()
    assert find_resource(tmp_path, 1).name == "chapter_1"
    (tmp_path / "source_1.txt").write_text("x")
    assert find_resource(tmp_path, 1).name == "source_1.txt"
    (tmp_path / "source_1.pdf").write_bytes(b"")
    assert find_resource(tmp_path, 1).name == "source_1.pdf"
    (tmp_path / "source_1").mkdir()
    assert find_resource(tmp_path, 1).name == "source_1"
