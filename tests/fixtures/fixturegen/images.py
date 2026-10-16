"""The image samples (RFL-AC18), under ``images/``:

- ``photo-and-drawing.pdf``: three 6 x 9 in pages, each with one line of text above one
  image. Pages 1 and 2 each draw their own copy of the same 4000 x 3000 RGB
  "photograph" (a smooth many-coloured gradient, double-deflated so it fits in a few
  kilobytes); page 3 draws a 2-colour line drawing (a 1-bit grid, 800 x 600) through a
  form XObject, as many PDF producers place images. Its ground truth,
  ``photo-and-drawing.txt``, is the three lines of text.
- ``full-page-photo.pdf``: one 6 x 9 in page that a 1200 x 1800 RGB "photograph" (the
  same kind of gradient) fills, edge to edge, with a visible caption set over it: a
  born-digital full-page picture, a book image to keep, though an image covers the whole
  page under its text ([#107](https://github.com/Bezoar/pdf2epub/issues/107)). Its ground
  truth, ``full-page-photo.txt``, is the caption.

Written with ``rawpdf``, so the bytes don't depend on the zlib build.
"""

from pathlib import Path

from fixturegen import rawpdf

PATH = "images/photo-and-drawing.pdf"
GROUND_TRUTH = "images/photo-and-drawing.txt"
FULL_PAGE_PATH = "images/full-page-photo.pdf"
FULL_PAGE_GROUND_TRUTH = "images/full-page-photo.txt"

PHOTO_SIZE = (4000, 3000)
FULL_PAGE_PHOTO_SIZE = (1200, 1800)
DRAWING_SIZE = (800, 600)
GRID = 50
"""The drawing's grid spacing, in pixels."""

LINES = [
    "The first page shows the photograph.",
    "The second page shows the same photograph again.",
    "The third page shows a line drawing.",
]

CAPTION = "The harbour at dawn, seen from the lighthouse."

_FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


def _photo(size: tuple[int, int] = PHOTO_SIZE) -> rawpdf.Periodic:
    """Every row is the same gradient: red rises, green and blue cycle at other rates,
    so it has thousands of colours."""
    width, height = size
    row = bytearray()
    for x in range(width):
        row += bytes((x * 255 // (width - 1), (x // 3) % 256, (x * 7) % 256))
    return rawpdf.Periodic(b"", bytes(row), height, b"")


def _drawing() -> rawpdf.Periodic:
    """A black grid on white, 1 bit per pixel (0 is black): a line every ``GRID`` pixels."""
    width, height = DRAWING_SIZE
    columns = [0 if x % GRID == 0 else 1 for x in range(width)]
    plain = bytes(int("".join(map(str, columns[i : i + 8])), 2) for i in range(0, width, 8))
    ruled = bytes(width // 8)
    unit = ruled + plain * (GRID - 1)
    return rawpdf.Periodic(b"", unit, height // GRID, b"")


def _image(width: int, height: int, colour: bytes, bits: int, data: bytes, filters: bytes) -> bytes:
    return rawpdf.stream(
        b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s "
        b"/BitsPerComponent %d /Filter %s" % (width, height, colour, bits, filters),
        data,
    )


def _text(line: str) -> bytes:
    return b"BT /F1 12 Tf 54 600 Td (%s) Tj ET\n" % line.encode("ascii")


def build(out_dir: Path) -> None:
    photo = rawpdf.double_deflated(_photo())
    drawing = rawpdf.zlib_periodic(_drawing())
    # Objects: 1 catalog, 2 page tree, 3 font, 4-9 the pages and their content streams,
    # 10-11 the two photograph copies, 12 the drawing, 13 the form XObject drawing it.
    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 432 648]"
        b" /Resources << /Font << /F1 3 0 R >> /XObject << /X %d 0 R >> >> /Contents %d 0 R >>"
    )
    draw = b"q 324 0 0 243 54 300 cm /X Do Q"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R 6 0 R 8 0 R] /Count 3 >>",
        _FONT,
        page % (10, 5),
        rawpdf.stream(b"", _text(LINES[0]) + draw),
        page % (11, 7),
        rawpdf.stream(b"", _text(LINES[1]) + draw),
        page % (13, 9),
        rawpdf.stream(b"", _text(LINES[2]) + b"q 1 0 0 1 54 300 cm /X Do Q"),
        _image(*PHOTO_SIZE, b"/DeviceRGB", 8, photo, b"[/FlateDecode /FlateDecode]"),
        _image(*PHOTO_SIZE, b"/DeviceRGB", 8, photo, b"[/FlateDecode /FlateDecode]"),
        _image(*DRAWING_SIZE, b"/DeviceGray", 1, drawing, b"/FlateDecode"),
        rawpdf.stream(
            b"/Type /XObject /Subtype /Form /BBox [0 0 324 243]"
            b" /Resources << /XObject << /D 12 0 R >> >>",
            b"q 324 0 0 243 0 0 cm /D Do Q",
        ),
    ]
    target = out_dir / PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rawpdf.document(objects))
    (out_dir / GROUND_TRUTH).write_text("\n\n".join(LINES) + "\n", encoding="utf-8")


def build_full_page_photo(out_dir: Path) -> None:
    photo = rawpdf.double_deflated(_photo(FULL_PAGE_PHOTO_SIZE))
    # Objects: 1 catalog, 2 page tree, 3 font, 4 the page, 5 its content, 6 the photograph.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        _FONT,
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 432 648]"
        b" /Resources << /Font << /F1 3 0 R >> /XObject << /X 6 0 R >> >> /Contents 5 0 R >>",
        rawpdf.stream(b"", b"q 432 0 0 648 0 0 cm /X Do Q\n" + _text(CAPTION)),
        _image(*FULL_PAGE_PHOTO_SIZE, b"/DeviceRGB", 8, photo, b"[/FlateDecode /FlateDecode]"),
    ]
    target = out_dir / FULL_PAGE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rawpdf.document(objects))
    (out_dir / FULL_PAGE_GROUND_TRUTH).write_text(CAPTION + "\n", encoding="utf-8")
