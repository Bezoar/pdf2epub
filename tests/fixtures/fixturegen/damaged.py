"""The damaged fixtures (TST-R3), under ``damaged/``:

- ``truncated.pdf``: a valid ``%PDF-`` header followed by seeded random bytes, beyond any
  repair (RFL-AC2);
- ``novel-no-xref.pdf``: the born-digital novel with its cross-reference table cut out,
  which a parser can rebuild by scanning the file (RFL-AC3);
- ``zero-pages.pdf``: a valid PDF whose page tree has no pages (RFL-AC4);
- ``image-bomb.pdf``: one page drawing an image that declares 40000 x 40000 grey pixels
  (1.6 GB decoded) in a 73 KB double-deflated stream (RFL-AC6);
- ``stream-bomb.pdf``: one page whose content stream inflates to 1 GiB of spaces from
  a few kilobytes (RFL-R6, the decompressed stream size limit).

Their text, where they have any, is the novel's, so none has ground truth of its own.
"""

import random
from pathlib import Path

from fixturegen import novel, rawpdf

TRUNCATED = "damaged/truncated.pdf"
NO_XREF = "damaged/novel-no-xref.pdf"
ZERO_PAGES = "damaged/zero-pages.pdf"
IMAGE_BOMB = "damaged/image-bomb.pdf"
STREAM_BOMB = "damaged/stream-bomb.pdf"

SEED = 2902
BOMB_SIDE = 40000
STREAM_BOMB_BYTES = 1 << 30

_PAGE = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 432 648] /Resources %s /Contents 3 0 R >>"
_PAGES = b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>"


def _write(out_dir: Path, path: str, data: bytes) -> None:
    target = out_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def build_truncated(out_dir: Path) -> None:
    noise = random.Random(SEED).randbytes(4096)
    _write(out_dir, TRUNCATED, b"%PDF-1.7\n" + noise)


def build_no_xref(out_dir: Path) -> None:
    """Cut the novel's table from ``xref`` up to ``trailer``; ``startxref`` then points
    at whatever follows. Needs the novel built into ``out_dir`` first."""
    data = (out_dir / novel.PATH).read_bytes()
    start = data.rindex(b"\nxref\n") + 1
    end = data.index(b"trailer", start)
    _write(out_dir, NO_XREF, data[:start] + data[end:])


def build_zero_pages(out_dir: Path) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [] /Count 0 >>",
    ]
    _write(out_dir, ZERO_PAGES, rawpdf.document(objects))


def build_image_bomb(out_dir: Path) -> None:
    image = rawpdf.stream(
        b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Filter [/FlateDecode /FlateDecode]" % (BOMB_SIDE, BOMB_SIDE),
        rawpdf.double_deflated_run(0, BOMB_SIDE * BOMB_SIDE),
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        _PAGES,
        rawpdf.stream(b"", b"q 360 0 0 576 36 36 cm /Im1 Do Q"),
        _PAGE % b"<< /XObject << /Im1 5 0 R >> >>",
        image,
    ]
    _write(out_dir, IMAGE_BOMB, rawpdf.document(objects))


def build_stream_bomb(out_dir: Path) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        _PAGES,
        rawpdf.stream(
            b"/Filter [/FlateDecode /FlateDecode]",
            rawpdf.double_deflated_run(ord(" "), STREAM_BOMB_BYTES),
        ),
        _PAGE % b"<< >>",
    ]
    _write(out_dir, STREAM_BOMB, rawpdf.document(objects))
