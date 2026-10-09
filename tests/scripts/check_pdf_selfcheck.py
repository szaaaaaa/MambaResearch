"""Manual acceptance with an actual exported PDF and isolated damaged copies."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/mambaresearch/skills/mambaresearch/scripts"))
from check_pdf_text import check_pdf


def rejected(path, phrase, reason):
    try:
        check_pdf(path, [phrase])
    except ValueError as error:
        assert reason in str(error), str(error)
    else:
        raise AssertionError(f"Damaged PDF accepted: {reason}")


if __name__ == "__main__":
    report = Path(sys.argv[1]).resolve()
    phrase = sys.argv[2]
    assert check_pdf(report, [phrase])[0] > 0
    rejected(report, "a deliberately absent acceptance phrase", "Expected text is missing")
    with TemporaryDirectory(dir=report.parent) as temporary:
        damaged = Path(temporary) / "damaged.pdf"
        for key, reason in (
            ("/ToUnicode", "no embedded Unicode mapping"),
            ("/FontFile2", "Font is not embedded"),
        ):
            writer = PdfWriter()
            writer.clone_document_from_reader(PdfReader(report))
            fonts = writer.pages[0]["/Resources"]["/Font"].values()
            font = next(ref.get_object() for ref in fonts if "MicrosoftYaHei" in str(ref.get_object()["/BaseFont"]))
            target = font if key == "/ToUnicode" else font["/DescendantFonts"][0]["/FontDescriptor"]
            del target[NameObject(key)]
            writer.write(damaged)
            rejected(damaged, phrase, reason)
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(report))
        content = DecodedStreamObject()
        content.set_data(b"/Span << /ActualText <FEFF0063> >> BDC\n" + writer.pages[0].get_contents().get_data() + b"\nEMC")
        writer.pages[0][NameObject("/Contents")] = writer._add_object(content)
        writer.write(damaged)
        rejected(damaged, phrase, "PDFium: Expected text is missing")
    print("PASS: actual report accepted; missing text, Unicode map, font and corrupt ActualText rejected")
