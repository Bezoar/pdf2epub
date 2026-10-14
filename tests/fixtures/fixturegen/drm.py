"""The fixtures pdf2epub must refuse without trying a password (PWD-R2 to PWD-R4).

Every one is synthetic. None contains vendor DRM code, keys or licences, and none needs
any: refusing them is decided from the security handler's name, the wrapper's layout or
the crypt filter's name alone. The page content is plain, unencrypted text.

- ``encrypted/ebx-handler.pdf``, ``encrypted/adobe-pubsec.pdf``,
  ``encrypted/fopn-foweb.pdf``: an ``/Encrypt`` dictionary whose ``/Filter`` names a
  non-Standard security handler (``drm_protected``, PWD-R2);
- ``encrypted/unknown-crypt-filter.pdf``: the Standard handler, ``/V 4 /R 4``, with a
  crypt filter whose ``/CFM`` no PDF library knows (``unsupported_encryption``,
  PWD-R4);
- ``drm-wrappers/sample.lcpdf``: a ZIP archive holding ``META-INF/license.lcpl``, as a
  Readium LCP package does, with a placeholder licence (``drm_protected``, PWD-R3);
- ``drm-wrappers/sample.acsm``: an XML ``fulfillmentToken`` in the Adobe ADEPT
  namespace, with placeholder values (``drm_protected``, PWD-R3).

Every URL is under ``example.invalid``, which can never resolve (RFC 6761).
"""

import zipfile
from pathlib import Path

from fixturegen import rawpdf

EBX_HANDLER = "encrypted/ebx-handler.pdf"
ADOBE_PUBSEC = "encrypted/adobe-pubsec.pdf"
FOPN_FOWEB = "encrypted/fopn-foweb.pdf"
UNKNOWN_CRYPT_FILTER = "encrypted/unknown-crypt-filter.pdf"
LCP = "drm-wrappers/sample.lcpdf"
ACSM = "drm-wrappers/sample.acsm"

TEXT = "This synthetic page is refused before any password is tried."

# The /Encrypt dictionary of each vendor-handler fixture: just the handler's name and the
# entries that make it look like what a reader would meet. Nothing in them is usable.
_VENDOR_ENCRYPT = {
    EBX_HANDLER: b"<< /Filter /EBX_HANDLER /V 2 /Length 128 >>",
    ADOBE_PUBSEC: b"<< /Filter /Adobe.PubSec /SubFilter /adbe.pkcs7.s5 /V 4 /Length 128 >>",
    FOPN_FOWEB: b"<< /Filter /FOPN_foweb /V 1 /Length 40 >>",
}

_ID = b"<73796e7468657469632d66697874757265>"
_UNKNOWN_CRYPT_FILTER_ENCRYPT = (
    b"<< /Filter /Standard /V 4 /R 4 /Length 128 /P -4"
    b" /CF << /StdCF << /CFM /XSyntheticCrypt /AuthEvent /DocOpen /Length 16 >> >>"
    b" /StmF /StdCF /StrF /StdCF"
    b" /O <" + b"00" * 32 + b"> /U <" + b"00" * 32 + b"> >>"
)

_LICENSE = b"""{
  "id": "00000000-0000-0000-0000-000000000000",
  "issued": "2000-01-01T00:00:00Z",
  "provider": "https://example.invalid/provider",
  "comment": "A synthetic placeholder for a pdf2epub test fixture. It holds no key."
}
"""

_ACSM = b"""<?xml version="1.0" encoding="UTF-8"?>
<fulfillmentToken fulfillmentType="loan" auth="user" xmlns="http://ns.adobe.com/adept">
  <distributor>urn:uuid:00000000-0000-0000-0000-000000000000</distributor>
  <operatorURL>https://example.invalid/fulfillment</operatorURL>
  <transaction>synthetic-pdf2epub-test-fixture</transaction>
  <resourceItemInfo>
    <resource>urn:uuid:00000000-0000-0000-0000-000000000000</resource>
    <metadata>
      <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Synthetic fixture</dc:title>
      <dc:format xmlns:dc="http://purl.org/dc/elements/1.1/">application/pdf</dc:format>
    </metadata>
  </resourceItemInfo>
</fulfillmentToken>
"""


def build_ebx_handler(out_dir: Path) -> None:
    _write(out_dir, EBX_HANDLER, _encrypted_pdf(_VENDOR_ENCRYPT[EBX_HANDLER]))


def build_adobe_pubsec(out_dir: Path) -> None:
    _write(out_dir, ADOBE_PUBSEC, _encrypted_pdf(_VENDOR_ENCRYPT[ADOBE_PUBSEC]))


def build_fopn_foweb(out_dir: Path) -> None:
    _write(out_dir, FOPN_FOWEB, _encrypted_pdf(_VENDOR_ENCRYPT[FOPN_FOWEB]))


def build_unknown_crypt_filter(out_dir: Path) -> None:
    _write(out_dir, UNKNOWN_CRYPT_FILTER, _encrypted_pdf(_UNKNOWN_CRYPT_FILTER_ENCRYPT))


def build_lcp(out_dir: Path) -> None:
    target = out_dir / LCP
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
        for name, data in [
            ("mimetype", b"application/pdf+lcp"),
            ("META-INF/license.lcpl", _LICENSE),
        ]:
            # Fixed metadata, so the archive is byte-identical from run to run (TST-R1).
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)


def build_acsm(out_dir: Path) -> None:
    _write(out_dir, ACSM, _ACSM)


def _encrypted_pdf(encrypt: bytes) -> bytes:
    content = b"BT /F1 12 Tf 54 600 Td (%s) Tj ET" % TEXT.encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 432 648]"
        b" /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        rawpdf.stream(b"", content),
        encrypt,
    ]
    return rawpdf.document(objects, trailer=b"/Encrypt 6 0 R /ID [%s %s]" % (_ID, _ID))


def _write(out_dir: Path, path: str, data: bytes) -> None:
    target = out_dir / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
