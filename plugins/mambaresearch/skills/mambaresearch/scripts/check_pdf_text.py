"""Reject PDFs with unmapped/unembedded fonts or lost expected text; no compilation."""

import argparse
from pathlib import Path
import re

from pypdf import PdfReader
from pypdf.generic import StreamObject
from pypdfium2 import PdfDocument


def check_pdf(path: Path, expected: list[str]) -> tuple[int, int]:
    reader = PdfReader(path)
    if not reader.pages:
        raise ValueError("PDF has no pages")
    seen = set()

    def check_resources(resources):
        if resources is None:
            return
        resources = resources.get_object()
        fonts = resources.get("/Font")
        for reference in fonts.get_object().values() if fonts is not None else ():
            font = reference.get_object()
            name = font.get("/BaseFont", "unnamed")
            mapping = font.get("/ToUnicode")
            if mapping is None or not isinstance(mapping.get_object(), StreamObject) or not mapping.get_object().get_data():
                raise ValueError(f"Font has no embedded Unicode mapping: {name}")
            descendants = font.get("/DescendantFonts")
            face = descendants[0].get_object() if descendants else font
            descriptor = face.get("/FontDescriptor")
            if descriptor is None or not any(
                key in descriptor.get_object()
                for key in ("/FontFile", "/FontFile2", "/FontFile3")
            ):
                raise ValueError(f"Font is not embedded: {name}")
        objects = resources.get("/XObject")
        for reference in objects.get_object().values() if objects is not None else ():
            form = reference.get_object()
            if form.get("/Subtype") == "/Form" and id(form) not in seen:
                seen.add(id(form))
                check_resources(form.get("/Resources"))

    for page in reader.pages:
        check_resources(page.get("/Resources"))
    text = "".join(page.extract_text() or "" for page in reader.pages)
    with PdfDocument(str(path)) as document:
        viewer_text = "".join(page.get_textpage().get_text_range() for page in document)
    for engine, extracted in (("pypdf", text), ("PDFium", viewer_text)):
        if "\ufffd" in extracted or "\x00" in extracted:
            raise ValueError(f"{engine}: replacement or null text characters")
        normalized = re.sub(r"\s+", "", extracted)
        for phrase in expected:
            if re.sub(r"\s+", "", phrase) not in normalized:
                raise ValueError(f"{engine}: Expected text is missing: {phrase}")
    return len(reader.pages), len(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--expect", action="append", required=True)
    args = parser.parse_args()
    pages, chars = check_pdf(args.pdf, args.expect)
    print(f"PASS: {pages} pages, {chars} extracted characters; embedded fonts, Unicode and pypdf/PDFium text verified")
