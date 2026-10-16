"""Images that must be taken as the page shows them (RFL-R9), under ``images/``:

- ``masked-layers.pdf``: one 6 x 9 in page, a line of text above a picture drawn the way
  Internet Archive scans draw a page: a pale ``BACKGROUND`` image, then, in the same
  box, a foreground image whose own pixels are all ``SMEAR`` red and whose soft mask
  (``/SMask``) lets that red show only in the shape of a capital H. On the page the
  picture is a red H on the pale background; the raw foreground is a red rectangle.
- ``cropped.pdf``: one US Letter page (MediaBox 612 x 792) whose CropBox shows only
  ``CROP``, as print-ready PDFs trim their bleed. Inside the visible part: a paragraph,
  a picture with a caption in smaller type just below it, and another paragraph, then a
  picture cut by the CropBox's bottom edge (``CLIPPED_VISIBLE`` of its height shows).
  Outside it: a sliver wholly in the trimmed margin, and a picture of which only 3% of
  the width shows.
- ``alpha.pdf``: one 6 x 9 in page, a line of text, an opaque two-colour grid picture,
  and below it, on nothing, a picture whose own pixels are all ``SMEAR`` red and whose
  soft mask shows them only in the shape of a capital H: on the page, a red H on the
  white page, with the rest of the picture see-through.

Pixel data is stored unfiltered, so the bytes don't depend on the zlib build.
"""

from pathlib import Path

from fixturegen import rawpdf

MASKED = "images/masked-layers.pdf"
MASKED_TRUTH = "images/masked-layers.txt"
CROPPED = "images/cropped.pdf"
CROPPED_TRUTH = "images/cropped.txt"

BACKGROUND = (236, 226, 196)
"""The pale background layer's colour."""
SMEAR = (200, 30, 30)
"""Every pixel of the foreground layer, visible only where its soft mask is white."""
MASKED_SIZE = (120, 80)
"""Pixels of both layers."""
MASKED_BOX = (108.0, 300.0, 324.0, 444.0)
"""Where both layers are drawn: (left, bottom, right, top) in page space."""

ALPHA = "images/alpha.pdf"
ALPHA_TRUTH = "images/alpha.txt"
ALPHA_LINES = ["A grid, then a red letter drawn with a soft mask on nothing."]
ALPHA_GRID = (20, 60, 160)
"""The grid lines' colour (on white, every ``ALPHA_GRID_STEP`` pixels)."""
ALPHA_GRID_STEP = 10
ALPHA_GRID_BOX = (108.0, 460.0, 324.0, 568.0)
"""Where the grid (``MASKED_SIZE`` pixels) is drawn: (left, bottom, right, top)."""

MASKED_LINES = ["The picture below is a red letter on a pale page."]

CROP = (81.0, 45.0, 531.0, 729.0)
"""The CropBox (left, bottom, right, top); the MediaBox is 0 0 612 792."""
FIGURE_SIZE = (300, 180)
"""The captioned picture's pixels, drawn one pixel per point."""
CLIPPED_SIZE = (300, 120)
"""The picture cut by the CropBox's bottom edge: pixels, one per point."""
CLIPPED_VISIBLE = 75 / 120
"""The share of the cut picture's height inside the CropBox."""
CAPTION = "Figure 1. A picture on a trimmed page."

CROPPED_PARAGRAPHS = [
    [
        "The opening paragraph sits above the picture on this trimmed page, and it",
        "runs to a second line.",
    ],
    [
        "The closing paragraph follows the caption and the picture, as the reader",
        "expects it to.",
    ],
]

_FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


def _image(size: tuple[int, int], colour: bytes, data: bytes, extra: bytes = b"") -> bytes:
    width, height = size
    return rawpdf.stream(
        b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s "
        b"/BitsPerComponent 8%s" % (width, height, colour, extra),
        data,
    )


def _solid(size: tuple[int, int], rgb: tuple[int, int, int]) -> bytes:
    return bytes(rgb) * (size[0] * size[1])


def _letter_h(size: tuple[int, int]) -> bytes:
    """A soft mask: white (shown) in the shape of an H, black (hidden) elsewhere."""
    width, height = size
    rows = bytearray()
    for y in range(height):
        for x in range(width):
            stem = 20 <= x < 40 or 80 <= x < 100
            bar = 40 <= x < 80 and 34 <= y < 46
            rows.append(255 if 10 <= y < 70 and (stem or bar) else 0)
    return bytes(rows)


def _grid(size: tuple[int, int], ink: tuple[int, int, int], step: int) -> bytes:
    """A two-colour grid: ``ink`` lines every ``step`` pixels on white."""
    width, height = size
    out = bytearray()
    for y in range(height):
        for x in range(width):
            out += bytes(ink if x % step == 0 or y % step == 0 else (255, 255, 255))
    return bytes(out)


def _text(x: float, y: float, size: float, line: str) -> bytes:
    return b"BT /F1 %g Tf %g %g Td (%s) Tj ET\n" % (size, x, y, line.encode("ascii"))


def _page(media: bytes, crop: bytes, xobjects: int, count: int, contents: int) -> bytes:
    names = b" ".join(b"/X%d %d 0 R" % (n, xobjects + n) for n in range(count))
    return (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [%s]%s"
        b" /Resources << /Font << /F1 3 0 R >> /XObject << %s >> >> /Contents %d 0 R >>"
        % (media, crop, names, contents)
    )


def build_masked(out_dir: Path) -> None:
    left, bottom, right, top = MASKED_BOX
    place = b"q %g 0 0 %g %g %g cm" % (right - left, top - bottom, left, bottom)
    content = _text(54, 600, 12, MASKED_LINES[0]) + place + b" /X0 Do Q " + place + b" /X1 Do Q"
    # Objects: 1 catalog, 2 page tree, 3 font, 4 page, 5 contents, 6 background,
    # 7 foreground, 8 its soft mask.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        _FONT,
        _page(b"0 0 432 648", b"", 6, 2, 5),
        rawpdf.stream(b"", content),
        _image(MASKED_SIZE, b"/DeviceRGB", _solid(MASKED_SIZE, BACKGROUND)),
        _image(MASKED_SIZE, b"/DeviceRGB", _solid(MASKED_SIZE, SMEAR), b" /SMask 8 0 R"),
        _image(MASKED_SIZE, b"/DeviceGray", _letter_h(MASKED_SIZE)),
    ]
    target = out_dir / MASKED
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rawpdf.document(objects))
    (out_dir / MASKED_TRUTH).write_text("\n".join(MASKED_LINES) + "\n", encoding="utf-8")


def build_cropped(out_dir: Path) -> None:
    def draw(n: int, left: float, bottom: float, size: tuple[int, int]) -> bytes:
        return b"q %d 0 0 %d %g %g cm /X%d Do Q\n" % (*size, left, bottom, n)

    body = bytearray()
    for n, line in enumerate(CROPPED_PARAGRAPHS[0]):
        body += _text(120, 680 - 14 * n, 11, line)
    body += draw(0, 150, 450, FIGURE_SIZE)  # top at 630, under the opening paragraph
    body += _text(150, 438, 8, CAPTION)
    for n, line in enumerate(CROPPED_PARAGRAPHS[1]):
        body += _text(120, 400 - 14 * n, 11, line)
    body += draw(1, 150, 0, CLIPPED_SIZE)  # its bottom 45 pt of 120 below the CropBox
    body += draw(2, 560, 100, (30, 600))  # wholly in the trimmed right margin
    body += draw(3, 525, 200, (200, 100))  # 6 of its 200 pt inside the CropBox
    # Objects: 1 catalog, 2 page tree, 3 font, 4 page, 5 contents, 6-9 the pictures.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        _FONT,
        _page(b"0 0 612 792", b" /CropBox [%g %g %g %g]" % CROP, 6, 4, 5),
        rawpdf.stream(b"", bytes(body)),
        _image(FIGURE_SIZE, b"/DeviceRGB", _grid(FIGURE_SIZE, (20, 60, 160), 20)),
        _image(CLIPPED_SIZE, b"/DeviceRGB", _grid(CLIPPED_SIZE, (20, 140, 40), 15)),
        _image((30, 600), b"/DeviceRGB", _solid((30, 600), (0, 0, 0))),
        _image((200, 100), b"/DeviceRGB", _grid((200, 100), (160, 20, 20), 10)),
    ]
    target = out_dir / CROPPED
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rawpdf.document(objects))
    text = "\n\n".join(
        " ".join(p) for p in [CROPPED_PARAGRAPHS[0], [CAPTION], CROPPED_PARAGRAPHS[1]]
    )
    (out_dir / CROPPED_TRUTH).write_text(text + "\n", encoding="utf-8")


def build_alpha(out_dir: Path) -> None:
    def place(box: tuple[float, float, float, float], n: int) -> bytes:
        left, bottom, right, top = box
        return b"q %g 0 0 %g %g %g cm /X%d Do Q\n" % (right - left, top - bottom, left, bottom, n)

    content = _text(54, 600, 12, ALPHA_LINES[0]) + place(ALPHA_GRID_BOX, 0)
    content += place(MASKED_BOX, 1)
    # Objects: 1 catalog, 2 page tree, 3 font, 4 page, 5 contents, 6 grid, 7 the red
    # picture, 8 its soft mask.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        _FONT,
        _page(b"0 0 432 648", b"", 6, 2, 5),
        rawpdf.stream(b"", content),
        _image(MASKED_SIZE, b"/DeviceRGB", _grid(MASKED_SIZE, ALPHA_GRID, ALPHA_GRID_STEP)),
        _image(MASKED_SIZE, b"/DeviceRGB", _solid(MASKED_SIZE, SMEAR), b" /SMask 8 0 R"),
        _image(MASKED_SIZE, b"/DeviceGray", _letter_h(MASKED_SIZE)),
    ]
    target = out_dir / ALPHA
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rawpdf.document(objects))
    (out_dir / ALPHA_TRUTH).write_text("\n".join(ALPHA_LINES) + "\n", encoding="utf-8")
