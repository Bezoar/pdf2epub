"""The synthetic scans (TST-R3 "Scanned"), under ``scanned/``: page images with **no**
text layer, as a scanner without OCR writes them.

- ``novel-clean.pdf``: the 40 pages of ``born-digital/novel.pdf`` at 300 DPI (clean);
- ``two-pages.pdf``: the 2 pages of ``born-digital/two-pages.pdf`` at 300 DPI;
- ``two-column.pdf``: the 4 pages of ``born-digital/two-column.pdf`` at 300 DPI;
- ``image-only.pdf``: a 3-page image-only scan, each page a running header, one English
  paragraph in 11 pt Times-Roman and a centred page number;
- ``blank-page.pdf``: page 1 of ``image-only.pdf``, then a blank scanned page (a white
  300 DPI image, no text layer) (OCR-AC25).

Each ground truth (the ``.txt`` beside the PDF) is the text of the page images without
furniture: for the renders of a born-digital fixture, that fixture's own ground truth;
for ``image-only.pdf``, its paragraphs, separated by blank lines; for ``blank-page.pdf``,
the first of them.

How the bytes stay the same on every platform: each page is rendered by PDFium (shipped
inside the pinned pypdfium2 wheel) without anti-aliasing and cut to bitonal at mid-grey,
so the image doesn't depend on any system font or rasteriser. It is stored CCITT Group 4
encoded (``/CCITTFaxDecode``, ``/K -1``), which is a canonical encoding: every correct
encoder (here libtiff, through Pillow) writes the same bits for the same image. The PDF
around the images is written by ``rawpdf``, uncompressed.
"""

import io
import random
import shutil
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, TiffImagePlugin
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from fixturegen import layouts, novel, prose, rawpdf, twopage

NOVEL_CLEAN = "scanned/novel-clean.pdf"
NOVEL_CLEAN_TRUTH = "scanned/novel-clean.txt"
TWO_PAGES = "scanned/two-pages.pdf"
TWO_PAGES_TRUTH = "scanned/two-pages.txt"
TWO_COLUMN = "scanned/two-column.pdf"
TWO_COLUMN_TRUTH = "scanned/two-column.txt"
IMAGE_ONLY = "scanned/image-only.pdf"
IMAGE_ONLY_TRUTH = "scanned/image-only.txt"
BLANK_PAGE = "scanned/blank-page.pdf"
BLANK_PAGE_TRUTH = "scanned/blank-page.txt"

DPI = 300
LANGUAGE = "en"
PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0  # 6 x 9 in

IMAGE_ONLY_TITLE = "Notes from the Lantern Coast"
BODY_FONT, HEADER_FONT = "Times-Roman", "Times-Italic"
BODY_SIZE, SMALL_SIZE, LEADING = 11.0, 9.0, 14.5
MARGIN_X, HEADER_Y, BODY_TOP, FOLIO_Y, INDENT = 54.0, 600.0, 560.0, 40.0, 18.0
_SEED = 4018


# --- Rendering and encoding -------------------------------------------------------------


def _render(pdf: bytes) -> list[Image.Image]:
    """Every page of ``pdf`` as a bitonal 300 DPI image."""
    document = pdfium.PdfDocument(pdf)
    pages: list[Image.Image] = []
    try:
        for index in range(len(document)):
            page = document[index]
            width, height = page.get_size()
            bitmap = page.render(
                scale=DPI / 72,
                grayscale=True,
                no_smoothtext=True,
                no_smoothpath=True,
                no_smoothimage=True,
            )
            size = (round(width * DPI / 72), round(height * DPI / 72))
            grey = bitmap.to_pil().crop((0, 0, *size))
            pages.append(grey.point(lambda value: 255 if value >= 128 else 0).convert("1"))
            page.close()
    finally:
        document.close()
    return pages


def group4(image: Image.Image) -> bytes:
    """``image`` (bitonal) as one CCITT Group 4 strip, as ``/BlackIs1 false`` reads it.
    Pillow writes a bitonal TIFF as min-is-black, coding black pixels as CCITT "white"
    runs, so the image is inverted first."""
    buffer = io.BytesIO()
    image = image.convert("L").point(lambda value: 255 - value).convert("1")
    image.save(buffer, format="TIFF", compression="group4", tiffinfo={278: image.height})
    with Image.open(io.BytesIO(buffer.getvalue())) as tiff:
        assert isinstance(tiff, TiffImagePlugin.TiffImageFile)
        [offset], [length] = tiff.tag_v2[273], tiff.tag_v2[279]
    return buffer.getvalue()[offset : offset + length]


def _scan_pdf(images: list[Image.Image], title: str) -> bytes:
    """A PDF of one page per image, each image filling its page at 300 DPI. Objects: 1
    catalog, 2 page tree, 3 Info, then a page, its content stream and its image for each
    page."""
    kids = b" ".join(b"%d 0 R" % (4 + 3 * i) for i in range(len(images)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /Lang (%s) >>" % LANGUAGE.encode(),
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(images)),
        b"<< /Title (%s) /Producer (pdf2epub fixture scanner) >>" % title.encode("ascii"),
    ]
    for index, image in enumerate(images):
        image_ref = 6 + 3 * index
        width, height = image.width * 72 / DPI, image.height * 72 / DPI
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %g %g]"
            b" /Resources << /XObject << /Im0 %d 0 R >> >> /Contents %d 0 R >>"
            % (width, height, image_ref, 5 + 3 * index)
        )
        objects.append(rawpdf.stream(b"", b"q %g 0 0 %g 0 0 cm /Im0 Do Q" % (width, height)))
        objects.append(
            rawpdf.stream(
                b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray"
                b" /BitsPerComponent 1 /Filter /CCITTFaxDecode"
                b" /DecodeParms << /K -1 /Columns %d /Rows %d /BlackIs1 false >>"
                % (image.width, image.height, image.width, image.height),
                group4(image),
            )
        )
    return rawpdf.document(objects, info=3)


def _write(out_dir: Path, path: str, pdf: bytes) -> None:
    target = out_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf)


def _rescan(out_dir: Path, source: str, source_truth: str, path: str, truth: str) -> None:
    """Scan the generated born-digital fixture ``source``; its ground truth is the scan's."""
    images = _render((out_dir / source).read_bytes())
    with pdfium.PdfDocument(out_dir / source) as document:
        title = str(document.get_metadata_dict().get("Title") or Path(source).stem)
    _write(out_dir, path, _scan_pdf(images, title))
    shutil.copyfile(out_dir / source_truth, out_dir / truth)


# --- The fixtures -----------------------------------------------------------------------


def build_novel_clean(out_dir: Path) -> None:
    _rescan(out_dir, novel.PATH, novel.GROUND_TRUTH, NOVEL_CLEAN, NOVEL_CLEAN_TRUTH)


def build_two_pages(out_dir: Path) -> None:
    _rescan(out_dir, twopage.PATH, twopage.GROUND_TRUTH, TWO_PAGES, TWO_PAGES_TRUTH)


def build_two_column(out_dir: Path) -> None:
    _rescan(out_dir, layouts.TWO_COLUMN, layouts.TWO_COLUMN_TRUTH, TWO_COLUMN, TWO_COLUMN_TRUTH)


def _image_only_source() -> tuple[bytes, list[str]]:
    """The 3-page book that ``image-only.pdf`` is a scan of, and its paragraphs."""
    rng = random.Random(_SEED)
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), invariant=True, pageCompression=0)
    paragraphs = []
    for number in range(1, 4):
        canvas.setFont(HEADER_FONT, SMALL_SIZE)
        canvas.drawCentredString(PAGE_WIDTH / 2, HEADER_Y, IMAGE_ONLY_TITLE)
        canvas.setFont(BODY_FONT, BODY_SIZE)
        text = prose.paragraph(rng, 4, 5)
        paragraphs.append(text)
        y = BODY_TOP
        for index, line in enumerate(_break_lines(text)):
            canvas.drawString(MARGIN_X + (0 if index else INDENT), y, line)
            y -= LEADING
        canvas.setFont(BODY_FONT, SMALL_SIZE)
        canvas.drawCentredString(PAGE_WIDTH / 2, FOLIO_Y, str(number))
        canvas.showPage()
    canvas.save()
    return buffer.getvalue(), paragraphs


def _break_lines(text: str) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        width = PAGE_WIDTH - 2 * MARGIN_X - (0 if lines else INDENT)
        if current and stringWidth(" ".join([*current, word]), BODY_FONT, BODY_SIZE) > width:
            lines.append(" ".join(current))
            current = []
        current.append(word)
    lines.append(" ".join(current))
    return lines


def build_image_only(out_dir: Path) -> None:
    source, paragraphs = _image_only_source()
    _write(out_dir, IMAGE_ONLY, _scan_pdf(_render(source), IMAGE_ONLY_TITLE))
    (out_dir / IMAGE_ONLY_TRUTH).write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")


def build_blank_page(out_dir: Path) -> None:
    source, paragraphs = _image_only_source()
    first = _render(source)[0]
    blank = Image.new("1", first.size, 1)
    _write(out_dir, BLANK_PAGE, _scan_pdf([first, blank], IMAGE_ONLY_TITLE))
    (out_dir / BLANK_PAGE_TRUTH).write_text(paragraphs[0] + "\n", encoding="utf-8")
