"""The hostile-input fixture (RFL-R5, RFL-AC5): ``hostile/actions.pdf``.

One page with one line of text, plus everything a viewer might run or fetch:

- document-level JavaScript (the ``/Names /JavaScript`` tree) that would open a URL;
- an ``/OpenAction`` launching a URI;
- a link annotation whose action launches ``launched.sh`` beside the PDF;
- a page-open (``/AA /O``) JavaScript action;
- an image XObject whose data is an external file at a URL (``/F`` with ``/FS /URL``).

Every URL is under ``example.invalid``, which can never resolve (RFC 6761). The ground
truth, ``hostile/actions.txt``, is the page's one line.
"""

from pathlib import Path

from fixturegen import rawpdf

PATH = "hostile/actions.pdf"
GROUND_TRUTH = "hostile/actions.txt"
LAUNCH_TARGET = "launched.sh"
TEXT = "Nothing on this page may run or reach the network."


def build(out_dir: Path) -> None:
    content = b"BT /F1 12 Tf 54 600 Td (%s) Tj ET q 100 0 0 100 54 400 cm /Im1 Do Q" % (
        TEXT.encode("ascii")
    )
    objects = [
        # 1: catalog
        b"<< /Type /Catalog /Pages 2 0 R /OpenAction 5 0 R"
        b" /Names << /JavaScript << /Names [(init) 6 0 R] >> >> >>",
        # 2: page tree
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        # 3: the page
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 432 648]"
        b" /Resources << /Font << /F1 4 0 R >> /XObject << /Im1 7 0 R >> >>"
        b" /Contents 8 0 R /Annots [9 0 R] /AA << /O 10 0 R >> >>",
        # 4: font
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        # 5: open action: launch a URI
        b"<< /S /URI /URI (http://example.invalid/open-action) >>",
        # 6: document-level JavaScript
        b"<< /S /JavaScript"
        b" /JS (app.launchURL\\('http://example.invalid/document-js', true\\);) >>",
        # 7: an image whose data lives at a URL
        rawpdf.stream(
            b"/Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray"
            b" /BitsPerComponent 8 /F << /FS /URL /F (http://example.invalid/image.png) >>",
            b"",
        ),
        # 8: page content
        rawpdf.stream(b"", content),
        # 9: a link that launches a program
        b"<< /Type /Annot /Subtype /Link /Rect [54 590 378 615] /Border [0 0 0]"
        b" /A << /S /Launch /F (%s) >> >>" % LAUNCH_TARGET.encode("ascii"),
        # 10: page-open JavaScript
        b"<< /S /JavaScript /JS (app.launchURL\\('http://example.invalid/page-js', true\\);) >>",
    ]
    target = out_dir / PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rawpdf.document(objects))
    (out_dir / GROUND_TRUTH).write_text(TEXT + "\n", encoding="utf-8")
