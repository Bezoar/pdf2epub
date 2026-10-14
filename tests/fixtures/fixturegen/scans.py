"""The synthetic scans (TST-R3 "Scanned"), under ``scanned/``: page images with **no**
text layer, as a scanner without OCR writes them.

- ``novel-clean.pdf``: the 40 pages of ``born-digital/novel.pdf`` at 300 DPI (clean);
- ``two-pages.pdf``: the 2 pages of ``born-digital/two-pages.pdf`` at 300 DPI;
- ``two-column.pdf``: the 4 pages of ``born-digital/two-column.pdf`` at 300 DPI;
- ``image-only.pdf``: a 3-page image-only scan, each page a running header, one English
  paragraph in 11 pt Times-Roman and a centred page number;
- ``blank-page.pdf``: page 1 of ``image-only.pdf``, then a blank scanned page (a white
  300 DPI image, no text layer) (OCR-AC25);
- the degraded scans (TST-R3), each of chapter 1 of the novel (its pages 1-4):
  ``novel-noise.pdf`` (1% of the pixels of the clean render flipped, at random),
  ``novel-skew.pdf`` (the clean render turned 2 degrees counter-clockwise),
  ``novel-rotated.pdf`` (the page scanned sideways: the render turned 90 degrees
  clockwise, on a landscape page) and ``novel-150dpi.pdf`` (rendered at 150 DPI);
- ``emphasis.pdf``: one page of three English paragraphs in 11 pt Times with italic
  (Times-Italic) and bold (Times-Bold) words inside their lines (OCR-AC23).

Each ground truth (the ``.txt`` beside the PDF) is the text of the page images without
furniture: for the renders of a born-digital fixture, that fixture's own ground truth;
for ``image-only.pdf``, its paragraphs, separated by blank lines; for ``blank-page.pdf``,
the first of them; for the degraded scans, chapter 1 of the novel's ground truth; for
``emphasis.pdf``, its paragraphs without markup.

How the bytes stay the same on every platform: each page is rendered by PDFium (shipped
inside the pinned pypdfium2 wheel) with its own built-in fonts only (never the system's),
without anti-aliasing, and cut to bitonal at mid-grey. It is stored CCITT Group 4
encoded (``/CCITTFaxDecode``, ``/K -1``), which is a canonical encoding: every correct
encoder (here libtiff, through Pillow) writes the same bits for the same image. The PDF
around the images is written by ``rawpdf``, uncompressed. The degraded scans change the
render only by exact steps: noise from NumPy's PCG64 generator with a fixed seed, skew as
three shears of whole-pixel row and column shifts (Paeth's rotation), and the quarter
turn and the 150 DPI render by PDFium itself.
"""

import io
import math
import random
import shutil
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from numpy.typing import NDArray
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
NOISE = "scanned/novel-noise.pdf"
NOISE_TRUTH = "scanned/novel-noise.txt"
SKEW = "scanned/novel-skew.pdf"
SKEW_TRUTH = "scanned/novel-skew.txt"
ROTATED = "scanned/novel-rotated.pdf"
ROTATED_TRUTH = "scanned/novel-rotated.txt"
LOW_DPI = "scanned/novel-150dpi.pdf"
LOW_DPI_TRUTH = "scanned/novel-150dpi.txt"
EMPHASIS = "scanned/emphasis.pdf"
EMPHASIS_TRUTH = "scanned/emphasis.txt"

DPI = 300
LANGUAGE = "en"
PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0  # 6 x 9 in

IMAGE_ONLY_TITLE = "Notes from the Lantern Coast"
BODY_FONT, HEADER_FONT = "Times-Roman", "Times-Italic"
BODY_SIZE, SMALL_SIZE, LEADING = 11.0, 9.0, 14.5
MARGIN_X, HEADER_Y, BODY_TOP, FOLIO_Y, INDENT = 54.0, 600.0, 560.0, 40.0, 18.0
_SEED = 4018
DEGRADED_PAGES = 4
"""The degraded scans are of chapter 1 of the novel: its first 4 pages."""
NOISE_SHARE = 0.01
SKEW_DEGREES = 2.0
LOW_RESOLUTION = 150
_NOISE_SEED = 4319
EMPHASIS_TITLE = "Emphasis in a Scan"
# Each paragraph is its lines, each line a list of (text, style) runs; style is "", "i"
# (italic) or "b" (bold). Lines are drawn as given: no line breaking.
EMPHASIS_LINES: list[list[list[tuple[str, str]]]] = [
    [
        [("The keeper wrote in the ", ""), ("Harbour Log", "i"), (" every evening,", "")],
        [("and on the night of the storm he underlined the word ", ""), ("never", "b")],
        [("twice before he closed the book.", "")],
    ],
    [
        [("The schoolteacher read the entry aloud. It said the ", ""), ("Mariner", "i")],
        [("had passed the point at midnight, ", ""), ("without", "i"), (" a light,", "")],
        [("and that the bell on the reef had rung ", ""), ("three", "b"), (" times.", "")],
    ],
    [
        [("Nobody in the village believed it until the morning, when the", "")],
        [("boats came back with a ", ""), ("broken", "i"), (" oar and a ", ""), ("silver", "b")],
        [("lamp that nobody could explain.", "")],
    ],
]
EMPHASIS_FONTS = {"": "Times-Roman", "i": "Times-Italic", "b": "Times-Bold"}


# --- Rendering and encoding -------------------------------------------------------------


_NO_SYSTEM_FONTS: list[object] = []


def _builtin_fonts_only() -> None:
    """Stop PDFium from looking up fonts installed on the system: a PDF font that isn't
    embedded (the standard 14 fonts of the born-digital fixtures) is then drawn with
    PDFium's own built-in substitute, the same on every platform. Process-wide; the
    callbacks are kept alive for as long as the process runs."""
    if _NO_SYSTEM_FONTS:
        return
    info = pdfium_c.FPDF_SYSFONTINFO()
    types = dict(pdfium_c.FPDF_SYSFONTINFO._fields_)
    info.version = 1
    info.Release = types["Release"](lambda this: None)
    info.EnumFonts = types["EnumFonts"](lambda this, mapper: None)
    info.MapFont = types["MapFont"](lambda this, weight, italic, charset, pitch, face, exact: None)
    info.GetFont = types["GetFont"](lambda this, face: None)
    info.GetFontData = types["GetFontData"](lambda this, font, table, buffer, size: 0)
    info.GetFaceName = types["GetFaceName"](lambda this, font, buffer, size: 0)
    info.GetFontCharset = types["GetFontCharset"](lambda this, font: 0)
    info.DeleteFont = types["DeleteFont"](lambda this, font: None)
    pdfium_c.FPDF_SetSystemFontInfo(info)
    _NO_SYSTEM_FONTS.append(info)


def _render(
    pdf: bytes, dpi: int = DPI, rotation: int = 0, count: int | None = None
) -> list[Image.Image]:
    """The first ``count`` pages of ``pdf`` (all, by default) as bitonal ``dpi`` images,
    turned ``rotation`` degrees clockwise."""
    _builtin_fonts_only()
    document = pdfium.PdfDocument(pdf)
    pages: list[Image.Image] = []
    try:
        for index in range(len(document) if count is None else count):
            page = document[index]
            width, height = page.get_size()
            bitmap = page.render(
                scale=dpi / 72,
                rotation=rotation,
                grayscale=True,
                no_smoothtext=True,
                no_smoothpath=True,
                no_smoothimage=True,
            )
            if rotation in (90, 270):
                width, height = height, width
            size = (round(width * dpi / 72), round(height * dpi / 72))
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


def _scan_pdf(images: list[Image.Image], title: str, dpi: int = DPI) -> bytes:
    """A PDF of one page per image, each image filling its page at ``dpi``. Objects: 1
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
        width, height = image.width * 72 / dpi, image.height * 72 / dpi
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


# --- The degraded scans (TST-R3) --------------------------------------------------------


def _chapter_one_truth(out_dir: Path) -> str:
    """Chapter 1 of the novel's ground truth: its entries before chapter 2's title."""
    entries = (out_dir / novel.GROUND_TRUTH).read_text(encoding="utf-8").split("\n\n")
    end = entries.index(novel.CHAPTER_TITLES[1])
    return "\n\n".join(entries[:end]) + "\n"


def _chapter_one(out_dir: Path, dpi: int = DPI, rotation: int = 0) -> list[Image.Image]:
    """The pages of chapter 1 of the generated novel, rendered bitonal."""
    return _render((out_dir / novel.PATH).read_bytes(), dpi, rotation, DEGRADED_PAGES)


def _degraded(out_dir: Path, path: str, truth: str, images: list[Image.Image], dpi: int) -> None:
    _write(out_dir, path, _scan_pdf(images, f"{novel.BOOK_TITLE} (chapter 1)", dpi))
    (out_dir / truth).write_text(_chapter_one_truth(out_dir), encoding="utf-8")


def _noisy(image: Image.Image, rng: np.random.Generator) -> Image.Image:
    """``image`` (bitonal) with ``NOISE_SHARE`` of its pixels flipped."""
    pixels = np.array(image.convert("L"), dtype=np.uint8)
    flips = rng.random(pixels.shape) < NOISE_SHARE
    pixels[flips] = 255 - pixels[flips]
    return Image.fromarray(pixels).convert("1")


def _shear_rows(pixels: NDArray[np.uint8], factor: float) -> NDArray[np.uint8]:
    """Each row shifted right by ``factor`` times its distance below the centre row,
    rounded to whole pixels; paper fills in."""
    out = np.full_like(pixels, 255)
    height, width = pixels.shape
    for row in range(height):
        shift = round(factor * (row - height / 2))
        if shift >= 0:
            out[row, shift:] = pixels[row, : width - shift]
        else:
            out[row, :shift] = pixels[row, -shift:]
    return out


def _skewed(image: Image.Image, degrees: float) -> Image.Image:
    """``image`` (bitonal) turned ``degrees`` counter-clockwise about its centre by three
    shears (rows, columns, rows), each moving whole pixels."""
    radians = math.radians(degrees)
    pixels = np.array(image.convert("L"), dtype=np.uint8)
    pixels = _shear_rows(pixels, math.tan(radians / 2))
    pixels = np.ascontiguousarray(_shear_rows(pixels.T.copy(), -math.sin(radians)).T)
    pixels = _shear_rows(pixels, math.tan(radians / 2))
    return Image.fromarray(pixels).convert("1")


def build_noise(out_dir: Path) -> None:
    rng = np.random.default_rng(_NOISE_SEED)
    images = [_noisy(image, rng) for image in _chapter_one(out_dir)]
    _degraded(out_dir, NOISE, NOISE_TRUTH, images, DPI)


def build_skew(out_dir: Path) -> None:
    images = [_skewed(image, SKEW_DEGREES) for image in _chapter_one(out_dir)]
    _degraded(out_dir, SKEW, SKEW_TRUTH, images, DPI)


def build_rotated(out_dir: Path) -> None:
    _degraded(out_dir, ROTATED, ROTATED_TRUTH, _chapter_one(out_dir, rotation=90), DPI)


def build_low_dpi(out_dir: Path) -> None:
    images = _chapter_one(out_dir, dpi=LOW_RESOLUTION)
    _degraded(out_dir, LOW_DPI, LOW_DPI_TRUTH, images, LOW_RESOLUTION)


# --- The emphasis scan (OCR-AC23) -------------------------------------------------------


def build_emphasis(out_dir: Path) -> None:
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), invariant=True, pageCompression=0)
    y = BODY_TOP
    paragraphs = []
    for paragraph in EMPHASIS_LINES:
        for index, line in enumerate(paragraph):
            x = MARGIN_X + (0 if index else INDENT)
            for text, style in line:
                font = EMPHASIS_FONTS[style]
                canvas.setFont(font, BODY_SIZE)
                canvas.drawString(x, y, text)
                x += stringWidth(text, font, BODY_SIZE)
            y -= LEADING
        y -= LEADING
        paragraphs.append(" ".join("".join(text for text, _ in line) for line in paragraph))
    canvas.showPage()
    canvas.save()
    _write(out_dir, EMPHASIS, _scan_pdf(_render(buffer.getvalue()), EMPHASIS_TITLE))
    (out_dir / EMPHASIS_TRUTH).write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")
