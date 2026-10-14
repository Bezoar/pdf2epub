"""Small structure samples, under ``born-digital/``, typeset with ReportLab:

- ``image-only.pdf``: one page holding one image and no text (RFL-R35: a kept book image
  is content);
- ``image-between-lines.pdf``: one page with a paragraph of 6 lines and a thin image
  (an ornament 2 pt tall) drawn in the gap between its 3rd and 4th lines; the ground
  truth ``image-between-lines.txt`` holds the text before and after the image as two
  entries;
- ``outline-to-page.pdf``: 4 pages, one paragraph each, with an outline of 3 top-level
  entries (pages 1, 2 and 4: ``One``, ``Two``, ``Four``) and one entry nested under
  ``Two`` (``Three``) that points to the whole of page 3, where no heading is; its ground
  truth ``outline-to-page.txt`` is the four paragraphs.

- ``image-page-in-paragraph.pdf``: a paragraph that breaks mid-sentence at the end of
  page 1 and runs on at the top of page 3, with page 2 holding only an image; its ground
  truth ``image-page-in-paragraph.txt`` is the whole paragraph.

Images are hex-encoded inline images, so the files do not depend on the zlib build.
"""

from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

from fixturegen.headings import inline_image

IMAGE_ONLY = "born-digital/image-only.pdf"
IMAGE_BETWEEN_LINES = "born-digital/image-between-lines.pdf"
IMAGE_BETWEEN_LINES_TRUTH = "born-digital/image-between-lines.txt"
OUTLINE_TO_PAGE = "born-digital/outline-to-page.pdf"
OUTLINE_TO_PAGE_TRUTH = "born-digital/outline-to-page.txt"
IMAGE_PAGE = "born-digital/image-page-in-paragraph.pdf"
IMAGE_PAGE_TRUTH = "born-digital/image-page-in-paragraph.txt"

PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0
MARGIN_X, TOP = 54.0, 560.0
FONT, SIZE, LEADING, INDENT = "Times-Roman", 11.0, 14.5, 18.0
BEFORE = [
    "The lamp room was cold that night, and the keeper",
    "wrapped his hands around a cup of tea while the",
    "wind pushed hard against the glass of the lantern",
]
AFTER = [
    "and the light turned slowly above the dark water,",
    "sweeping across the harbour wall and the boats",
    "that were waiting for the tide to come back in.",
]
PAGE_TEXT = [
    "The first page has a short paragraph of its own.",
    "The second page has a short paragraph of its own.",
    "The third page has a short paragraph of its own.",
    "The fourth page has a short paragraph of its own.",
]


def _canvas(out_dir: Path, path: str) -> Canvas:
    target = out_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(
        str(target),
        pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
        invariant=True,
        pageCompression=0,
        lang="en",
    )
    canvas.setTitle(Path(path).stem)
    return canvas


def build_image_only(out_dir: Path) -> None:
    canvas = _canvas(out_dir, IMAGE_ONLY)
    inline_image(canvas, MARGIN_X, 300.0, 90)
    canvas.showPage()
    canvas.save()


def build_image_between_lines(out_dir: Path) -> None:
    canvas = _canvas(out_dir, IMAGE_BETWEEN_LINES)
    canvas.setFont(FONT, SIZE)
    y = TOP
    for n, line in enumerate([*BEFORE, *AFTER]):
        canvas.drawString(MARGIN_X + (INDENT if n == 0 else 0), y, line)
        if n == len(BEFORE) - 1:
            # The gap between this line's descenders and the next line's ascenders.
            inline_image(canvas, MARGIN_X + 60, y - LEADING + SIZE - 1.0, 200, 120.0, 2.0)
        y -= LEADING
    canvas.showPage()
    canvas.save()
    truth = [" ".join(BEFORE), " ".join(AFTER)]
    (out_dir / IMAGE_BETWEEN_LINES_TRUTH).write_text("\n\n".join(truth) + "\n", encoding="utf-8")


def build_outline_to_page(out_dir: Path) -> None:
    canvas = _canvas(out_dir, OUTLINE_TO_PAGE)
    entries = {1: ("One", 0), 2: ("Two", 0), 3: ("Three", 1), 4: ("Four", 0)}
    for page, text in enumerate(PAGE_TEXT, start=1):
        key = f"page-{page}"
        canvas.bookmarkPage(key)
        title, level = entries[page]
        canvas.addOutlineEntry(title, key, level=level)
        canvas.setFont(FONT, SIZE)
        canvas.drawString(MARGIN_X + INDENT, 400.0, text)
        canvas.showPage()
    canvas.save()
    (out_dir / OUTLINE_TO_PAGE_TRUTH).write_text("\n\n".join(PAGE_TEXT) + "\n", encoding="utf-8")


def build_image_page(out_dir: Path) -> None:
    canvas = _canvas(out_dir, IMAGE_PAGE)
    for page, lines in enumerate([BEFORE, None, AFTER]):
        if lines is None:
            inline_image(canvas, MARGIN_X, 300.0, 150)
        else:
            canvas.setFont(FONT, SIZE)
            for n, line in enumerate(lines):
                x = MARGIN_X + (INDENT if page == 0 and n == 0 else 0)
                canvas.drawString(x, TOP - n * LEADING, line)
        canvas.showPage()
    canvas.save()
    text = " ".join([*BEFORE, *AFTER])
    (out_dir / IMAGE_PAGE_TRUTH).write_text(text + "\n", encoding="utf-8")
