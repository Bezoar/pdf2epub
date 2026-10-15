"""Scans with an invisible OCR layer that the coverage signal must read right (TST-R3;
OCR-AC3, OCR-AC5, OCR-R16), the causes found on the Internet Archive scans S7 and S9
([#90](https://github.com/Bezoar/pdf2epub/issues/90)).

The first four are must-trust scans of the 4-page book in ``textlayers``, each with a good
layer that misses no text; the last one is must-reject:

- ``scanned/low-boxes-layer.pdf``: the scans under a layer whose every line sits 0.3 of
  its font size below the line it reads, as Internet Archive layers put the baseline at
  the bottom of the descenders: the tops of capitals and ascenders lie above every box;
- ``scanned/dark-border.pdf``: the scans with a black film border round each page, as a
  microfiche scan has (a band 120 px deep at the top, 150 at the bottom, 100 on the
  left and 140 on the right), under the good layer;
- ``scanned/illustrated.pdf``: 4 pages that are not all text, under a layer of the text
  only:
  1. a frontispiece: a black picture plate (with white patches holding specks of ink, as
     a halftone scan breaks up) above a two-line caption;
  2. a text page with a plate across its middle;
  3. a title page of three short lines with a library stamp: a ring round the words
     ``HARBOUR TOWN PUBLIC LIBRARY``, which no layer reads (as Internet Archive layers
     don't): more of the page's text-like ink than the title's, but far less than the
     coverage allowance (OCR-R16);
  4. an endpaper: rows of large ornaments, with two lines of text below;
- ``scanned/inset-picture.pdf``: one page of text (a paragraph above, one below) whose
  scan leaves the middle of the page blank, under a layer of the text, with a separate
  picture image (a black plate, as on ``illustrated.pdf``'s page 2) placed over that
  blank middle: a scan with a smaller illustration of its own, a book image to keep
  ([#107](https://github.com/Bezoar/pdf2epub/issues/107));
- ``must-reject/half-layer-border.pdf``: the dark-border scans under ``half-layer.pdf``'s
  layer (the lines in the top half of each page only);
- ``must-reject/half-layer-negative.pdf``: the scans as a negative (white print on a black
  ground, as a microfilm negative is), under the same half layer.

Each ground truth is the text the layer holds (and the scan shows), without header and
page numbers: its paragraphs, separated by blank lines. The bytes stay the same on every
platform as in ``textlayers``: PDFium renders, bitonal, CCITT Group 4, and the plates,
borders, rings and ornaments are painted by exact integer array steps.
"""

import random
from dataclasses import replace
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from reportlab.pdfbase.pdfmetrics import stringWidth

from fixturegen import prose, rawpdf, scans
from fixturegen.textlayers import (
    BODY_BOTTOM,
    BODY_FONT,
    BODY_SIZE,
    BODY_TOP,
    LEADING,
    MARGIN_X,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    TEXT_WIDTH,
    _book,
    _break_lines,
    _catalog,
    _font_objects,
    _layered,
    _page,
    _Run,
    _text_stream,
    _typeset,
    _write,
)

LOW_BOXES = "scanned/low-boxes-layer.pdf"
LOW_BOXES_TRUTH = "scanned/low-boxes-layer.txt"
DARK_BORDER = "scanned/dark-border.pdf"
DARK_BORDER_TRUTH = "scanned/dark-border.txt"
ILLUSTRATED = "scanned/illustrated.pdf"
ILLUSTRATED_TRUTH = "scanned/illustrated.txt"
INSET_PICTURE = "scanned/inset-picture.pdf"
INSET_PICTURE_TRUTH = "scanned/inset-picture.txt"
HALF_LAYER_BORDER = "must-reject/half-layer-border.pdf"
HALF_LAYER_BORDER_TRUTH = "must-reject/half-layer-border.txt"
HALF_LAYER_NEGATIVE = "must-reject/half-layer-negative.pdf"
HALF_LAYER_NEGATIVE_TRUTH = "must-reject/half-layer-negative.txt"

DPI = 300
LOW_BY = 0.3
"""How far below its line each layer line sits, as a share of its font size."""
BORDER = (120, 150, 100, 140)
"""The film border's depth in pixels: top, bottom, left, right."""
INSET = (MARGIN_X, 250.0, PAGE_WIDTH - MARGIN_X, 420.0)
"""Where the inset picture lies, in points from the page's top-left: left, top, right,
bottom."""
_SEED = 9090

Pixels = NDArray[np.bool_]
"""A page image as ink: True where black."""


def _ink(image: Image.Image) -> Pixels:
    return np.asarray(image.convert("L")) < 128


def _image(ink: Pixels) -> Image.Image:
    return Image.fromarray(np.where(ink, 0, 255).astype(np.uint8)).convert("1")


def _px(points: float) -> int:
    return round(points * DPI / 72)


def _bordered(image: Image.Image) -> Image.Image:
    ink = _ink(image).copy()
    top, bottom, left, right = BORDER
    ink[:top, :] = True
    ink[ink.shape[0] - bottom :, :] = True
    ink[:, :left] = True
    ink[:, ink.shape[1] - right :] = True
    return _image(ink)


def _scans(pages: list[list[_Run]]) -> list[Image.Image]:
    return scans._render(_typeset(pages), dpi=DPI)


def build_low_boxes(out_dir: Path) -> None:
    pages, truth = _book()
    layers = [[replace(run, y=run.y - LOW_BY * run.size) for run in runs] for runs in pages]
    _write(out_dir, LOW_BOXES, LOW_BOXES_TRUTH, _layered(_scans(pages), layers), truth)


def build_dark_border(out_dir: Path) -> None:
    pages, truth = _book()
    images = [_bordered(image) for image in _scans(pages)]
    _write(out_dir, DARK_BORDER, DARK_BORDER_TRUTH, _layered(images, pages), truth)


def build_half_layer_border(out_dir: Path) -> None:
    pages, truth = _book()
    images = [_bordered(image) for image in _scans(pages)]
    layers = [[run for run in runs if run.y >= PAGE_HEIGHT / 2] for runs in pages]
    pdf = _layered(images, layers)
    _write(out_dir, HALF_LAYER_BORDER, HALF_LAYER_BORDER_TRUTH, pdf, truth)


def build_half_layer_negative(out_dir: Path) -> None:
    pages, truth = _book()
    images = [_image(~_ink(image)) for image in _scans(pages)]
    layers = [[run for run in runs if run.y >= PAGE_HEIGHT / 2] for runs in pages]
    pdf = _layered(images, layers)
    _write(out_dir, HALF_LAYER_NEGATIVE, HALF_LAYER_NEGATIVE_TRUTH, pdf, truth)


# --- The illustrated scan ---------------------------------------------------------------


def _lines(text: str, top: float, centred: bool = False) -> list[_Run]:
    """``text`` broken into body lines from baseline ``top`` down."""
    runs = []
    for index, line in enumerate(_break_lines(text)):
        width = stringWidth(line, BODY_FONT, BODY_SIZE)
        x = (PAGE_WIDTH - width) / 2 if centred else MARGIN_X
        runs.append(_Run(BODY_FONT, BODY_SIZE, x, top - index * LEADING, line))
    return runs


def _plate(ink: Pixels, left: float, top: float, right: float, bottom: float) -> None:
    """Paint a black picture plate over the box (points, from the page's top-left), with
    a grid of white patches each holding a speck of ink, as a halftone breaks up."""
    x0, y0, x1, y1 = _px(left), _px(top), _px(right), _px(bottom)
    ink[y0:y1, x0:x1] = True
    for y in range(y0 + 40, y1 - 60, 90):
        for x in range(x0 + 40, x1 - 60, 90):
            ink[y : y + 40, x : x + 40] = False
            ink[y + 18 : y + 24, x + 10 : x + 16] = True


def _ring(ink: Pixels, cx: float, cy: float, radius: float, width: float) -> None:
    """Paint a ring centred on (``cx``, ``cy``) points from the top-left."""
    rows, columns = np.ogrid[: ink.shape[0], : ink.shape[1]]
    squared = (rows - _px(cy)) ** 2 + (columns - _px(cx)) ** 2
    outer, inner = _px(radius), _px(radius - width)
    ink[(squared <= outer * outer) & (squared >= inner * inner)] = True


def _ornaments(ink: Pixels, top: float, bottom: float) -> None:
    """Rows of large diamond ornaments, each 40 pt high, between ``top`` and ``bottom``
    (points from the top)."""
    size = _px(20)
    rows, columns = np.ogrid[-size : size + 1, -size : size + 1]
    diamond = np.abs(rows) + np.abs(columns) <= size
    hole = np.abs(rows) + np.abs(columns) <= size // 2
    shape = diamond & ~hole
    for cy in range(_px(top) + size, _px(bottom) - size, 3 * size):
        for cx in range(_px(MARGIN_X) + size, _px(PAGE_WIDTH - MARGIN_X) - size, 3 * size):
            ink[cy - size : cy + size + 1, cx - size : cx + size + 1] |= shape


def _illustrated() -> tuple[list[list[_Run]], list[list[_Run]], list[str]]:
    """Each page's layer runs, the runs printed but not in the layer (the stamp), and the
    ground truth's paragraphs."""
    rng = random.Random(_SEED)
    caption = " ".join(prose.sentence(rng) for _ in range(3))
    above = prose.paragraph(rng, 3, 3)
    below = prose.paragraph(rng, 3, 3)
    title = [" ".join(prose.sentence(rng).rstrip(".").split()[:5]) for _ in range(3)]
    endpaper = " ".join(prose.sentence(rng) for _ in range(3))
    layers = [
        _lines(caption, 150.0),
        [*_lines(above, BODY_TOP), *_lines(below, 200.0)],
        [
            _Run(BODY_FONT, BODY_SIZE, MARGIN_X, BODY_TOP - 40 * index, line)
            for index, line in enumerate(title)
        ],
        _lines(endpaper, 150.0),
    ]
    for runs in layers:
        assert all(run.y >= BODY_BOTTOM and run.x + 1 >= MARGIN_X for run in runs)
        assert all(stringWidth(r.text, BODY_FONT, BODY_SIZE) <= TEXT_WIDTH for r in runs)
    stamp_lines = [
        _Run(BODY_FONT, BODY_SIZE, 302.0 - stringWidth(word, BODY_FONT, BODY_SIZE) / 2, y, word)
        for word, y in (("HARBOUR TOWN", 318.0), ("PUBLIC", 300.0), ("LIBRARY", 282.0))
    ]
    stamp: list[list[_Run]] = [[], [], stamp_lines, []]
    paragraphs = [caption, above, below, *title, endpaper]
    return layers, stamp, paragraphs


def build_illustrated(out_dir: Path) -> None:
    layers, stamp, paragraphs = _illustrated()
    printed = [[*runs, *extra] for runs, extra in zip(layers, stamp, strict=True)]
    images = []
    for number, image in enumerate(_scans(printed), start=1):
        ink = _ink(image).copy()
        if number == 1:
            _plate(ink, 72.0, 72.0, 360.0, 470.0)
        elif number == 2:
            _plate(ink, MARGIN_X, 250.0, PAGE_WIDTH - MARGIN_X, 420.0)
        elif number == 3:
            _ring(ink, 302.0, 345.0, 62.0, 3.0)
        else:
            _ornaments(ink, 60.0, 460.0)
        images.append(_image(ink))
    truth = "\n\n".join(paragraphs) + "\n"
    _write(out_dir, ILLUSTRATED, ILLUSTRATED_TRUTH, _layered(images, layers), truth)


# --- The scan with an inset picture -----------------------------------------------------


def _bitonal(image: Image.Image) -> bytes:
    """A bitonal image XObject, CCITT Group 4 encoded."""
    return rawpdf.stream(
        b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray"
        b" /BitsPerComponent 1 /Filter /CCITTFaxDecode"
        b" /DecodeParms << /K -1 /Columns %d /Rows %d /BlackIs1 false >>"
        % (image.width, image.height, image.width, image.height),
        scans.group4(image),
    )


def build_inset_picture(out_dir: Path) -> None:
    layers, _, paragraphs = _illustrated()
    runs = layers[1]  # the text page: a paragraph above the middle, one below
    [scan] = _scans([runs])
    left, top, right, bottom = INSET
    ink = np.zeros((_px(bottom - top), _px(right - left)), dtype=np.bool_)
    _plate(ink, 0.0, 0.0, right - left, bottom - top)
    objects = _catalog(1, per_page=4)
    objects.extend(_font_objects(4))
    resources = b"/Font << /F1 4 0 R /F2 5 0 R >> /XObject << /Im0 8 0 R /Im1 9 0 R >>"
    objects.append(_page(7, resources))
    content = b"q %g 0 0 %g 0 0 cm /Im0 Do Q\nq %g 0 0 %g %g %g cm /Im1 Do Q\n" % (
        PAGE_WIDTH,
        PAGE_HEIGHT,
        right - left,
        bottom - top,
        left,
        PAGE_HEIGHT - bottom,
    )
    objects.append(rawpdf.stream(b"", content + _text_stream(runs, invisible=True)))
    objects.append(_bitonal(scan))
    objects.append(_bitonal(_image(ink)))
    truth = "\n\n".join(paragraphs[1:3]) + "\n"
    pdf = rawpdf.document(objects, info=3)
    _write(out_dir, INSET_PICTURE, INSET_PICTURE_TRUTH, pdf, truth)
