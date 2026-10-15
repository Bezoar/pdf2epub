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

And the kinds of damage that once crashed a conversion instead of failing it cleanly
(#94, RFL-AC29), each found in a qpdf test file and rebuilt here from scratch:

- ``stale-xref.pdf``: two pages, with a comment inserted after the header once the
  cross-reference table was written, so every offset in it is short by the comment's
  length; the parsers read different page counts until the table is rebuilt (qpdf's
  ``bad6.pdf`` family);
- ``unmatched-pages.pdf``: one page, replaced by an incremental update, in a file whose
  page tree object has no ``endobj``: pdfminer then misreads the tree and finds the page
  once in each revision, two pages where pdfium finds one, even after repair (qpdf's
  ``bad6.pdf``, ``bad12.pdf``);
- ``missing-page.pdf``: the page's cross-reference entry gives its content stream's
  offset, so pdfium can't load the page (qpdf's ``bad34.pdf``);
- ``xref-loop.pdf``: one page, replaced by an incremental update, whose two
  cross-reference sections name each other as ``/Prev`` (qpdf's ``issue-149.pdf``);
- ``objstm-loop.pdf``: a cross-reference stream that says the object stream holding
  the book is stored inside itself; pdfium reads the book regardless;
- ``objstm-root-loop.pdf``: the same, with the trailer's ``/Root`` naming that object
  stream, which neither parser can read (qpdf's ``issue-120.pdf``).

Their text, where they have any, is the novel's or a single word, so none has ground
truth of its own.
"""

import random
from collections.abc import Sequence
from pathlib import Path

from fixturegen import novel, rawpdf

TRUNCATED = "damaged/truncated.pdf"
NO_XREF = "damaged/novel-no-xref.pdf"
ZERO_PAGES = "damaged/zero-pages.pdf"
IMAGE_BOMB = "damaged/image-bomb.pdf"
STREAM_BOMB = "damaged/stream-bomb.pdf"
STALE_XREF = "damaged/stale-xref.pdf"
UNMATCHED_PAGES = "damaged/unmatched-pages.pdf"
MISSING_PAGE = "damaged/missing-page.pdf"
XREF_LOOP = "damaged/xref-loop.pdf"
OBJSTM_LOOP = "damaged/objstm-loop.pdf"
OBJSTM_ROOT_LOOP = "damaged/objstm-root-loop.pdf"

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


# --- Damage that once crashed a conversion (#94) ----------------------------------------

_FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


def _one_page(parent: int, contents: int, font: int) -> bytes:
    return (
        b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 432 648] /Contents %d 0 R "
        b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (parent, contents, font)
    )


def _words(text: bytes) -> bytes:
    return rawpdf.stream(b"", b"BT /F1 18 Tf 72 560 Td (%s) Tj ET" % text)


def _revision(
    out: bytearray,
    objects: Sequence[tuple[int, bytes]],
    trailer: bytes,
    without_endobj: int | None = None,
) -> int:
    """Append ``objects`` (number, body), a cross-reference section listing them and a
    trailer ending with the ``trailer`` entries; return the section's offset. The object
    numbered ``without_endobj`` is written without its ``endobj``."""
    offsets = []
    for number, body in objects:
        offsets.append((number, len(out)))
        end = b"\n" if number == without_endobj else b"\nendobj\n"
        out += b"%d 0 obj\n" % number + body + end
    section = len(out)
    out += b"xref\n0 1\n0000000000 65535 f \n"
    for number, offset in offsets:
        out += b"%d 1\n%010d 00000 n \n" % (number, offset)
    out += b"trailer\n<< " + trailer + b" >>\nstartxref\n%d\n%%%%EOF\n" % section
    return section


def build_stale_xref(out_dir: Path) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        _one_page(2, 4, 7),
        _words(b"Stale offsets, first page."),
        _one_page(2, 6, 7),
        _words(b"Stale offsets, second page."),
        _FONT,
    ]
    data = rawpdf.document(objects)
    comment = b"%" + b"-" * 39 + b"\n"
    header_end = data.index(b"1 0 obj")
    section = data.rindex(b"startxref\n") + len(b"startxref\n")
    end = data.index(b"\n", section)
    shifted = int(data[section:end]) + len(comment)  # startxref itself is kept right
    data = data[:header_end] + comment + data[header_end:section] + b"%d" % shifted + data[end:]
    _write(out_dir, STALE_XREF, data)


def _with_update(
    first_prev: bytes, second_prev: bytes, without_endobj: int | None = None
) -> tuple[bytearray, int, int]:
    """A one-page book (objects 1-5) and an incremental update that replaces its page
    with one (object 6) saying something else; returns the file and both sections."""
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    original = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (3, _one_page(2, 4, 5)),
        (4, _words(b"The draft page.")),
        (5, _FONT),
    ]
    first = _revision(out, original, b"/Size 6 /Root 1 0 R" + first_prev, without_endobj)
    update = [(3, _one_page(2, 6, 5)), (6, _words(b"The final page."))]
    second = _revision(out, update, b"/Size 7 /Root 1 0 R /Prev %d" % first + second_prev)
    return out, first, second


def build_unmatched_pages(out_dir: Path) -> None:
    out, _, _ = _with_update(b"", b"", without_endobj=2)
    _write(out_dir, UNMATCHED_PAGES, bytes(out))


def build_xref_loop(out_dir: Path) -> None:
    # The first section's /Prev must name the second, written after it: a fixed-width
    # number is filled in once the second section's offset is known.
    placeholder = b" /Prev %010d" % 0
    out, _, second = _with_update(placeholder, b"")
    at = out.index(placeholder)
    out[at : at + len(placeholder)] = b" /Prev %010d" % second
    _write(out_dir, XREF_LOOP, bytes(out))


def build_missing_page(out_dir: Path) -> None:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        _one_page(2, 4, 5),
        _words(b"A page nobody can find."),
        _FONT,
    ]
    data = bytearray(rawpdf.document(objects))
    table = data.rindex(b"\nxref\n") + 1
    entries = table + len(b"xref\n0 6\n")
    page, contents = entries + 20 * 3, entries + 20 * 4  # 20 bytes per entry
    data[page : page + 10] = data[contents : contents + 10]
    _write(out_dir, MISSING_PAGE, bytes(data))


def build_objstm_loop(out_dir: Path) -> None:
    _write(out_dir, OBJSTM_LOOP, _objstm_loop(root=2))


def build_objstm_root_loop(out_dir: Path) -> None:
    _write(out_dir, OBJSTM_ROOT_LOOP, _objstm_loop(root=1))


def _objstm_loop(root: int) -> bytes:
    """Objects 2-5 (the book, catalog first) in object stream 1, the page's content in
    object 6, and a cross-reference stream (object 7) that says object 1 is stored in
    object 1 and names object ``root`` as the catalog."""
    stored = [
        b"<< /Type /Catalog /Pages 3 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        _one_page(3, 6, 5),
        _FONT,
    ]
    bodies, offsets, at = b"", [], 0
    for body in stored:
        offsets.append(at)
        bodies += body + b"\n"
        at += len(body) + 1
    index = b" ".join(b"%d %d" % (number, offset) for number, offset in enumerate(offsets, start=2))
    index += b"\n"
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    contents = _words(b"Inside itself.")
    positions = {}
    for number, body in (
        (1, rawpdf.stream(b"/Type /ObjStm /N 4 /First %d" % len(index), index + bodies)),
        (6, contents),
    ):
        positions[number] = len(out)
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    rows = [b"\x00\x00\x00\xff"]  # object 0: free
    rows.append(b"\x02\x00\x01\x00")  # object 1: in object stream 1, the loop
    rows += [b"\x02\x00\x01" + bytes([i]) for i in range(4)]  # objects 2-5
    rows.append(b"\x01" + positions[6].to_bytes(2, "big") + b"\x00")
    rows.append(b"\x01" + xref.to_bytes(2, "big") + b"\x00")
    table = rawpdf.stream(b"/Type /XRef /Size 8 /W [1 2 1] /Root %d 0 R" % root, b"".join(rows))
    out += b"7 0 obj\n" + table + b"\nendobj\nstartxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)
