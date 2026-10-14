"""The metadata samples (RFL-AC22, RFL-AC23, EPUB-AC9), under ``metadata/``. Each is one
6 x 9 in page holding one line of text (``TEXT``), and differs only in its metadata:

- ``Jane Doe - A Book.pdf``: an Info dictionary with ``/Title (Real Title)`` and
  ``/ModDate (D:20200102030405Z)``, and nothing else: no XMP, no ``/Lang``, no author;
- ``scan0001.pdf``: no metadata at all (no Info, no XMP, no ``/Lang``, no dates);
- ``lang-fr.pdf``: the catalog's ``/Lang (fr)`` and nothing else;
- ``xmp.pdf``: an XMP packet with title ``XMP Title``, creators ``Ann Example`` then
  ``Bob Example`` (the second marked ``x-default``, which must not reorder them) and
  language ``de``, beside an Info dictionary with ``/Title (Info Title)``, ``/Author
  (Info Author)``, an invalid ``/ModDate`` (offset ``+99'00'``) and ``/CreationDate
  (D:20110203040506+02'00')``.

Written with ``rawpdf``, so every byte is under control.
"""

from pathlib import Path

from fixturegen import rawpdf

JANE_DOE = "metadata/Jane Doe - A Book.pdf"
SCAN = "metadata/scan0001.pdf"
LANG_FR = "metadata/lang-fr.pdf"
XMP = "metadata/xmp.pdf"

TEXT = "A single line of text, so the book is not empty."

_XMP_PACKET = """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:title><rdf:Alt>
        <rdf:li xml:lang="de">Ein Titel</rdf:li>
        <rdf:li xml:lang="x-default">XMP Title</rdf:li>
      </rdf:Alt></dc:title>
      <dc:creator><rdf:Seq>
        <rdf:li>Ann Example</rdf:li>
        <rdf:li xml:lang="x-default">Bob Example</rdf:li>
      </rdf:Seq></dc:creator>
      <dc:language><rdf:Bag><rdf:li>de</rdf:li></rdf:Bag></dc:language>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>""".encode()


def _document(catalog: bytes = b"", info: bytes | None = None, xmp: bool = False) -> bytes:
    """Objects: 1 catalog, 2 page tree, 3 font, 4 page, 5 content, then the Info
    dictionary and the XMP stream, if any."""
    objects = [
        b"",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 432 648]"
        b" /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
        rawpdf.stream(b"", b"BT /F1 12 Tf 54 600 Td (%s) Tj ET" % TEXT.encode("ascii")),
    ]
    info_number = None
    if info is not None:
        objects.append(info)
        info_number = len(objects)
    if xmp:
        objects.append(rawpdf.stream(b"/Type /Metadata /Subtype /XML", _XMP_PACKET))
        catalog += b" /Metadata %d 0 R" % len(objects)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R%s >>" % catalog
    return rawpdf.document(objects, info=info_number)


def _write(out_dir: Path, path: str, data: bytes) -> None:
    target = out_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def build_jane_doe(out_dir: Path) -> None:
    info = b"<< /Title (Real Title) /ModDate (D:20200102030405Z) >>"
    _write(out_dir, JANE_DOE, _document(info=info))


def build_scan(out_dir: Path) -> None:
    _write(out_dir, SCAN, _document())


def build_lang_fr(out_dir: Path) -> None:
    _write(out_dir, LANG_FR, _document(catalog=b" /Lang (fr)"))


def build_xmp(out_dir: Path) -> None:
    info = (
        b"<< /Title (Info Title) /Author (Info Author) /ModDate (D:20200102030405+99'00')"
        b" /CreationDate (D:20110203040506+02'00') >>"
    )
    _write(out_dir, XMP, _document(info=info, xmp=True))
