"""The Japanese and Korean line-join sample (RFL-AC28): ``born-digital/cjk-lines.pdf``.

One page with two paragraphs, each wrapped over several lines: a Japanese paragraph
(Han, Hiragana and Katakana; Japanese breaks lines anywhere, here mid-word) and then a
Korean paragraph (Hangul; Korean separates words with spaces, so its lines break at
spaces). The text is set in ReportLab's built-in CID fonts (``HeiseiMin-W3`` and
``HYSMyeongJo-Medium``, not embedded) with the ``UniJIS-UCS2-H`` and ``UniKS-UCS2-H``
encodings, so the text layer carries the exact code points drawn.

The ground truth, ``born-digital/cjk-lines.txt``, is the two paragraphs as a reader sees
them: the Japanese lines joined with no space, the Korean lines with one space.
"""

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

PATH = "born-digital/cjk-lines.pdf"
GROUND_TRUTH = "born-digital/cjk-lines.txt"

TITLE = "CJK Line Sample"
LANGUAGE = "ja"
JAPANESE_FONT, KOREAN_FONT = "HeiseiMin-W3", "HYSMyeongJo-Medium"
SIZE, LEADING = 11.0, 16.0
PAGE_WIDTH, PAGE_HEIGHT = 432.0, 648.0
MARGIN_X, TOP, INDENT = 54.0, 560.0, 11.0
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X

# 28 full-width characters per line (308 pt at 11 pt), the first line one em shorter for
# its indent. The breaks fall inside words, as Japanese typesetting allows.
JAPANESE_LINES = [
    "春の朝、港町の小さな図書館には静かな光が差し込んで、窓",
    "辺の机では学生たちが古い地図を広げて、遠い島々への航路を",
    "指でたどっていた。司書は棚の間を歩きながら、返却された本",
    "を一冊ずつ元の場所に戻した。",
]
KOREAN_LINES = [
    "봄날 아침 항구 마을의 작은 도서관에는 조용한 햇살이 비쳐",
    "들었고, 창가의 책상에서는 학생들이 낡은 지도를 펼쳐 놓고 먼",
    "섬들로 가는 뱃길을 손가락으로 따라가고 있었다. 사서는 서가",
    "사이를 걸으며 반납된 책을 한 권씩 제자리에 꽂았고, 오후가 되자",
    "바다에서 불어오는 바람이 열린 창문으로 들어와 책장을 조용히",
    "넘겼다.",
]
JAPANESE = "".join(JAPANESE_LINES)
KOREAN = " ".join(KOREAN_LINES)


def build(out_dir: Path) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont(JAPANESE_FONT))
    pdfmetrics.registerFont(UnicodeCIDFont(KOREAN_FONT))

    pdf_path = out_dir / PATH
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(
        str(pdf_path),
        pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
        invariant=True,
        pageCompression=0,
        lang=LANGUAGE,
    )
    canvas.setTitle(TITLE)
    y = TOP
    for font, lines in ((JAPANESE_FONT, JAPANESE_LINES), (KOREAN_FONT, KOREAN_LINES)):
        canvas.setFont(font, SIZE)
        for index, line in enumerate(lines):
            width = TEXT_WIDTH - (INDENT if index == 0 else 0)
            assert pdfmetrics.stringWidth(line, font, SIZE) <= width
            canvas.drawString(MARGIN_X + (INDENT if index == 0 else 0), y, line)
            y -= LEADING
        y -= LEADING  # a blank line between the paragraphs
    canvas.showPage()
    canvas.save()

    (out_dir / GROUND_TRUTH).write_text(f"{JAPANESE}\n\n{KOREAN}\n", encoding="utf-8")
