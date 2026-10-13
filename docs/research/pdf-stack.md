# MIT-compatible PDF library stack

Research for [issue #2](https://github.com/Bezoar/pdf2epub/issues/2). The
archived [SPEC.md](../SPEC.md) chose PyMuPDF, which is AGPL-3.0. pdf2epub must be
MIT-licensed. This note checks each candidate library against the converter's
needs. Sources were collected on 2026-10-13 and are primary where possible:
LICENSE files, PyPI or crates.io metadata, upstream source, and official docs.
Versions and dates are as of that day.

## TL;DR

- **Every required capability has a permissive option.** No copyleft
  dependency is essential, so nothing needs to be escalated.
- **There are two license traps.** PyMuPDF is AGPL-3.0, and so is the obvious
  Python EPUB writer, **ebooklib**. Avoid both. Write the small EPUB writer
  ourselves; the archived spec already planned this.
- **Python recommendation:** use **pypdfium2** (PDFium) as the core engine for
  decryption, rendering, outline, page labels, metadata, and per-character
  font, size and bbox data. Add **pdfminer.six** (MIT) where its layout
  grouping helps. For OCR, use **pytesseract** plus an external Tesseract
  binary, as an optional extra. For EPUB, write our own with `zipfile`, `lxml`
  and Jinja2. Validate with **epubcheck** (BSD-3, Java) as an external tool.
- **Obligations are attribution, not copyleft.** pypdfium2 wheels bundle a
  PDFium binary and its dependencies (FreeType, libjpeg-turbo, ICU, lcms,
  OpenJPEG, and others). Their license texts have to ship with any binary
  distribution of pdf2epub, such as a Docker image or a macOS app bundle.

## Capability × library matrix

Legend: ✅ supported · ⚠️ partial or caveat · ❌ not supported · — not applicable.
"MIT-OK" means an MIT project may depend on the library and redistribute it
without relicensing.

### Python

| Library | License | MIT-OK? | Text with font, size and bbox | Render | Outline / page labels / metadata | Decryption (RC4 / AES-128 / AES-256; user vs owner) | Health |
|---|---|---|---|---|---|---|---|
| **pypdfium2** 5.14.0 | Apache-2.0 / BSD-3-Clause (binding)[^p2lic]; PDFium BSD-style[^pdfiumlic]; bundled dependencies under assorted permissive licenses[^p2build] | ✅ Ship the bundled license texts.[^p2lic] Some builds link libgcc (GCC runtime exception).[^p2lic] | ✅ Helpers give char boxes, text ranges and bounded text.[^p2tp] The raw API exposes `FPDFText_GetFontInfo`, `GetFontSize`, `GetFontWeight`, `GetCharBox`, `GetLooseCharBox` and `GetMatrix`.[^fpdftext] | ✅ (PDFium) | ✅ `get_toc()`, `get_page_label()`, `get_metadata_dict()`[^p2doc] | ✅ RC4 and AES (AESV2 and AESV3), revisions 2–6.[^pdfiumsec] Takes a `password=` argument.[^p2doc] Either password opens the file. `FPDF_GetDocPermissions` and `FPDF_GetDocUserPermissions` report permissions.[^fpdfview] | Very active. 5.14.0 shipped 2026-10-04 with 131 releases.[^pypi-p2] PDFium binaries are built weekly (chromium/8100 on 2026-10-12).[^pdfbin] |
| **pdfminer.six** 20260107 | MIT[^pmlic] | ✅ | ✅ Best layout analysis. `LTChar` carries `fontname`, `size` and bbox plus colour and graphic state.[^pmlayout] | ❌ | ✅ `get_outlines()` and `get_page_labels()`[^pmdoc]; Info dict on `doc.info` | ✅ Handlers: R2–3 (RC4), R4 (AESV2 = AES-128), R5–6 (AESV3 = AES-256).[^pmdoc] Tries the user password, then the owner password.[^pmdoc] Ignores the "no extraction" flag unless `check_extractable=True`.[^pmpage] Needs `cryptography` (Apache-2.0 OR BSD-3).[^pmpyproj][^pypi-crypto] | Moderate. The last release was 2026-01-07 (about 9 months ago). Repo pushed 2026-03; 37 releases since 2014.[^pypi-pm] |
| **pdfplumber** 0.11.10 | MIT[^pypi-plumber] | ✅ | ✅ Wraps pdfminer.six with a friendlier char/word API | ⚠️ Through pypdfium2, for debug images | ⚠️ Through pdfminer | Same as pdfminer.six | Active. Last release 2026-06-15; pins `pdfminer.six==20260107` and `pypdfium2>=5.9`.[^pypi-plumber] |
| **pypdf** 6.20.1 | BSD-3-Clause[^pypdflic] | ✅ Pure Python | ⚠️ `extract_text(visitor_text=…)` returns text, CTM, Tm, font dict and font size per text operation. No per-glyph bbox.[^pypdfpage] | ❌ | ✅ `outline`, `page_labels`, `metadata`[^pypdfdoc] | ✅ RC4 and AES "until PDF-2.0".[^pypdfenc] AESV2 and AESV3 in source.[^pypdfencsrc] AES needs the `cryptography` or `pycryptodome` extra.[^pypdfenc] `decrypt()` returns `PasswordType.USER_PASSWORD` or `OWNER_PASSWORD`.[^pypdfencsrc] | Very active. Last release 2026-10-12.[^pypi-pypdf] |
| **pikepdf** 10.17.0 | MPL-2.0[^pikelic] (bundles qpdf, Apache-2.0[^qpdflic]) | ✅ MPL-2.0 is file-level copyleft. Only modifications to pikepdf files must be published.[^pikereadme] Wheels bundle qpdf and libjpeg-turbo (IJG/BSD/Zlib); the Windows wheel adds OpenSSL (Apache-2.0) and zlib.[^pike3p] | ❌ The README sends you to pdfminer.six or pdfplumber.[^pikereadme] | ❌ The README sends you to pypdfium2.[^pikereadme] | ✅ Low-level object access (outline helpers, metadata) | ✅ Up to AES-256 R6; R2–4 use RC4.[^pikesec] Either password opens the file. `user_password_matched` and `owner_password_matched` say which one did. Restrictions are not enforced.[^pikesec] | Very active. Last release 2026-10-11.[^pypi-pike] |
| **PyMuPDF** 1.28.2 (contrast) | **AGPL-3.0 or Artifex commercial**[^pymupdflic] | ❌ An MIT project cannot depend on it without AGPL-licensing the combined work or buying a commercial license. | ✅ Richest | ✅ | ✅ | ✅ | Active. Last release 2026-08-06.[^pypi-pymupdf] |
| **pytesseract** 0.3.13 | Apache-2.0[^pytesslic] | ✅ Runs the `tesseract` binary as a subprocess. Nothing is linked. | OCR (hOCR/TSV word boxes) | — | — | — | ⚠️ Quiet. Last release 2024-08-16.[^pypi-pytess] The interface is thin and stable. |
| **tesserocr** 2.11.0 | MIT[^pypi-tesserocr] | ✅ Links libtesseract (Apache-2.0) | OCR via the C++ API | — | — | — | Active. Last release 2026-08-04.[^pypi-tesserocr] |
| **Tesseract** 5.5.3 (engine) | Apache-2.0[^tesslic]. Models in tessdata_best are Apache-2.0.[^tessdatalic] Uses Leptonica (BSD-style).[^lept] | ✅ | — | — | — | — | Active. 5.5.3 released 2026-07-24.[^tessrel] |
| **ebooklib** 0.20 | **AGPL-3.0**[^ebooklic][^pypi-ebook] | ❌ | — | — | — | — | Slow. 8 releases since 2013.[^pypi-ebook] |
| Own EPUB writer (`zipfile` + **lxml** + **Jinja2**) | stdlib (PSF); lxml BSD-3[^pypi-lxml]; Jinja2 BSD-3[^jinjalic] | ✅ | — | — | — | — | — |
| **epubcheck** 5.4.0 (Java) | BSD-3-Clause[^epubchecklic] | ✅ We invoke it as a separate tool and don't redistribute it with the library. It needs a JRE. | — | — | — | — | Active. v5.4.0 released 2026-09-15.[^epubcheckrel] |

### Rust (for a possible native core or macOS helper)

| Crate | License | MIT-OK? | Text with font, size and bbox | Render | Outline / labels / metadata | Decryption | Health |
|---|---|---|---|---|---|---|---|
| **pdfium-render** 0.9.4 | MIT OR Apache-2.0[^crates] | ✅ Needs a PDFium library linked dynamically or statically.[^pdrreadme] The same bundled-license notices as pypdfium2 apply. | ✅ `PdfPageTextChar::font_name`, `font_weight`, `scaled_font_size`, `loose_bounds`, `tight_bounds`[^pdrchar] | ✅ | ✅ `bookmarks()`, `metadata()`, `permissions()`[^pdrdoc], `PdfPage::label()`[^pdrpage] | ✅ (PDFium). `load_pdf_from_file(path, password)`[^pdrreadme] | Active. Updated 2026-09-06 with 3.2M downloads.[^crates] |
| **hayro** 0.8.0 | Apache-2.0 OR MIT[^crates] | ✅ Pure Rust | ❌ Renderer only[^hayroreadme] | ✅ Passes 1400+ PDFs from the PDFBox and pdf.js corpora. Some gaps, such as non-embedded CID fonts.[^hayroreadme] | ⚠️ Low-level (hayro-syntax) | ✅ RC4, AESV2 and AESV3, revisions 2–6.[^hayrocrypto] Only the user-password path is visible for R2–4.[^hayrocrypto] | Active. Pushed 2026-10-13. |
| **lopdf** 0.45.0 | MIT[^crates] | ✅ | ❌ (object model only) | ❌ | ✅ (object model) | ✅ RC4, AES-128 and AES-256 crypt filters[^lopdfcf]; `load_with_password`; separate user and owner `authenticate_*` methods[^lopdfdoc] | Active. 24M downloads.[^crates] |
| **pdf-extract** 0.12.1 | MIT[^crates] | ✅ | ⚠️ Plain text through lopdf | ❌ | ❌ | Inherits from lopdf | Active.[^crates] |
| **pdf_oxide** 0.3.78 | MIT OR Apache-2.0 (code); the name is trademarked[^oxide] | ✅ | Claims text, layout, rendering, outline and encryption. The source has `encryption/{rc4,aes,handler}.rs`.[^oxidesrc] Not evaluated in depth. | Claimed | Claimed | Claimed | ⚠️ Young: created 2025-11 with one main author and 0.x versions.[^oxidesrc] Worth watching. |
| **mupdf** (mupdf-rs) 0.8.0 | **AGPL-3.0**[^crates] | ❌ | ✅ | ✅ | ✅ | ✅ | — |
| **pdfium** (pdfium-rs) 0.10.4 | **GPL-3.0**[^crates] | ❌ Use pdfium-render instead. | | | | | |
| **epub-builder** 0.8.3 | MPL-2.0[^crates] | ✅ File-level copyleft. OK unmodified. | — | — | — | — | Last update 2026-04.[^crates] |
| **zip** 9.0.2 (to build our own EPUB) | MIT[^crates] | ✅ | — | — | — | — | Very active.[^crates] |
| **tesseract** / **leptess** / **tesseract-rs** | MIT[^crates] (they link Apache-2.0 libtesseract) | ✅ | OCR | — | — | — | leptess has been stale since 2023-02. tesseract-rs was updated 2026-07.[^crates] |

### Swift / macOS (planned front end)

| Component | License | MIT-OK? | Text with font, size and bbox | Render | Outline / labels / metadata | Decryption | Notes |
|---|---|---|---|---|---|---|---|
| **PDFKit** (Apple system framework) | Apple SDK. Not redistributed; it ships with the OS. | ✅ Nothing to bundle. Apple platforms only. | ✅ `PDFPage.attributedString` (font attributes) and `characterBounds(at:)` in 72-dpi page space[^pk-attr][^pk-cb] | ✅ `thumbnail(of:for:)`, `draw(with:to:)`[^pk-thumb][^pk-draw] | ✅ `outlineRoot`, `PDFPage.label`, `documentAttributes`[^pk-outline][^pk-label][^pk-attrs] | ✅ `isEncrypted`, `isLocked`, `unlock(withPassword:)`. The empty password is tried automatically. `permissionsStatus` tells user access from owner access.[^pk-unlock][^pk-isenc][^pk-perm] ⚠️ **Apple does not document which algorithms are supported.** Test RC4, AES-128 and AES-256 empirically. | macOS 10.4+ |
| **Vision** text recognition | Apple SDK | ✅ | OCR via `VNRecognizeTextRequest` (macOS 10.15+) and `RecognizeTextRequest` (macOS 15+)[^vn1][^vn2] | — | — | — | Could replace Tesseract on macOS. |
| **ZIPFoundation** (to build the EPUB) | MIT[^zipf] | ✅ | — | — | — | — | Active. Pushed 2026-09. |
| PDFium through pdfium-render or a C bridge | as above | ✅ | ✅ | ✅ | ✅ | ✅ | Use if the Mac app must reproduce exactly what the Python CLI decrypts and extracts. |

## Recommended stacks

**Python (CLI and library, the first implementation)**

1. Use **pypdfium2** as the single source of truth. One parser for opening and
   decrypting (`PdfDocument(path, password=…)`), rendering for image fallback
   and OCR input, `get_toc()`, `get_page_label()`, `get_metadata_dict()`, and
   permission and revision checks. Read per-character font name, size, weight
   and boxes through the raw `FPDFText_*` API.
2. Use **pdfminer.six** (or pdfplumber on top of it) when its `LTChar`/`LTTextLine`
   grouping saves work. It decrypts AES-256 by itself, so it can open the same
   file with the same password, and it ignores the "no extraction" flag by
   default. Keep it an implementation detail behind a `PdfSource` seam so we
   can drop it if PDFium alone is enough.
3. Optional: **pikepdf** (MPL-2.0) to repair broken files before parsing.
   Optional: **pypdf** (BSD-3) as a pure-Python fallback for structure only.
4. OCR as an extra: install `pdf2epub[ocr]` to get **pytesseract**. The user
   installs the Tesseract binary. Both are Apache-2.0.
5. EPUB: build our own writer with `zipfile`, **lxml** and **Jinja2**. Do
   **not** use ebooklib (AGPL).
6. Validation: run **epubcheck** in CI and as an optional runtime check.

**Rust (if the core is ever ported, or for a native helper)**: use
**pdfium-render** with a PDFium binary from pdfium-binaries, which mirrors the
Python stack exactly. If we ever want no C dependency at all, combine
**hayro** (rendering) and **lopdf** (structure and decryption), and write our
own text extraction or evaluate **pdf_oxide**. Build the EPUB with the **zip**
crate. Use the **tesseract** crate (MIT) for OCR, or skip it on macOS.

**Swift (macOS front end)**: the simplest choice is to bundle and call the
Python CLI. A native port would use **PDFKit** (decrypt, text, bounds,
outline, labels, render), **Vision** (OCR) and **ZIPFoundation** (EPUB
container). The risk is that PDFKit and PDFium will disagree on edge cases,
which would make the two pipelines behave differently. Calling PDFium from
Swift avoids that.

## Capability gaps and license flags

- **No capability is left without a permissive option.** Nothing has to be
  escalated to the owner as an unavoidable copyleft dependency.
- **AGPL, avoid:** PyMuPDF/MuPDF, including mupdf-rs[^pymupdflic][^crates], and
  **ebooklib**[^ebooklic].
- **GPL, avoid:** the `pdfium` crate (pdfium-rs)[^crates]. Use the
  `pdfium-render` crate instead.
- **Weak copyleft, acceptable:** pikepdf and epub-builder (MPL-2.0). These are
  fine as unmodified dependencies. If we patch one of their files, the patched
  file has to be published.[^pikereadme]
- **Attribution duties:** any binary distribution (Docker image, app bundle,
  PyInstaller build) has to include the PDFium dependency licenses: FreeType
  (FTL), libjpeg-turbo (IJG notice required), ICU, lcms, OpenJPEG, libpng,
  libtiff, zlib, abseil, harfbuzz, and others.[^p2build][^pike3p] Some Linux
  musl wheels also carry libgcc or libstdc++ under GPL-3.0 with the GCC Runtime
  Library Exception, which allows redistribution.[^p2lic][^pike3p]
- **Pure-Python rendering does not exist with a permissive license.**
  Rendering always needs a native engine (PDFium). That's fine for pip wheels
  but matters for exotic platforms.[^p2lic]
- **No library in the stack enforces owner-password restrictions.** pikepdf
  says restrictions "depend entirely on the PDF viewer software to
  enforce"[^pikesec], and pdfminer ignores them by default[^pmpage]. The
  converter has to decide its own policy. See the companion decryption
  research ticket.
- **PDFKit does not document its supported encryption algorithms.** Test it
  against RC4, AES-128 and AES-256 sample files before relying on it.

## Sources

[^p2lic]: pypdfium2 README, "Licensing": https://github.com/pypdfium2-team/pypdfium2#licensing
[^p2build]: pypdfium2 BUILD_LICENSES directory (abseil, freetype, harfbuzz, icu, lcms, libjpeg_turbo, libopenjpeg, libpng, libtiff, zlib, …): https://github.com/pypdfium2-team/pypdfium2/tree/main/BUILD_LICENSES
[^p2tp]: pypdfium2 `textpage.py` (`get_charbox`, `get_text_bounded`, `get_rect`): https://github.com/pypdfium2-team/pypdfium2/blob/main/src/pypdfium2/_helpers/textpage.py
[^p2doc]: pypdfium2 `document.py` (`password`, `get_toc`, `get_page_label`, `get_metadata_dict`): https://github.com/pypdfium2-team/pypdfium2/blob/main/src/pypdfium2/_helpers/document.py
[^pdfiumlic]: PDFium LICENSE: https://pdfium.googlesource.com/pdfium/+/refs/heads/main/LICENSE
[^fpdftext]: PDFium `public/fpdf_text.h`: https://pdfium.googlesource.com/pdfium/+/refs/heads/main/public/fpdf_text.h
[^fpdfview]: PDFium `public/fpdfview.h` (`FPDF_GetDocPermissions`, `FPDF_GetDocUserPermissions`, `FPDF_GetSecurityHandlerRevision`): https://pdfium.googlesource.com/pdfium/+/refs/heads/main/public/fpdfview.h
[^pdfiumsec]: PDFium `core/fpdfapi/parser/cpdf_security_handler.cpp` (RC4, AESV2 and AESV3, revision 2–6 paths): https://pdfium.googlesource.com/pdfium/+/refs/heads/main/core/fpdfapi/parser/cpdf_security_handler.cpp
[^pdfbin]: pdfium-binaries releases: https://github.com/bblanchon/pdfium-binaries/releases
[^pypi-p2]: https://pypi.org/project/pypdfium2/
[^pmlic]: pdfminer.six LICENSE: https://github.com/pdfminer/pdfminer.six/blob/master/LICENSE
[^pmpyproj]: pdfminer.six pyproject.toml (`license = "MIT"`, `cryptography >= 36.0.0`): https://github.com/pdfminer/pdfminer.six/blob/master/pyproject.toml
[^pmlayout]: pdfminer.six `layout.py` (`LTChar`): https://github.com/pdfminer/pdfminer.six/blob/master/pdfminer/layout.py
[^pmdoc]: pdfminer.six `pdfdocument.py` (security handlers V2/V4/V5, `authenticate`, `get_outlines`, `get_page_labels`): https://github.com/pdfminer/pdfminer.six/blob/master/pdfminer/pdfdocument.py
[^pmpage]: pdfminer.six `pdfpage.py` (`check_extractable`): https://github.com/pdfminer/pdfminer.six/blob/master/pdfminer/pdfpage.py
[^pypi-pm]: https://pypi.org/project/pdfminer.six/
[^pypi-plumber]: https://pypi.org/project/pdfplumber/
[^pypi-crypto]: https://pypi.org/project/cryptography/
[^pypdflic]: pypdf LICENSE: https://github.com/py-pdf/pypdf/blob/main/LICENSE
[^pypdfpage]: pypdf `_page.py` (`extract_text(visitor_text=…)`): https://github.com/py-pdf/pypdf/blob/main/pypdf/_page.py ; docs: https://pypdf.readthedocs.io/en/stable/user/extract-text.html
[^pypdfdoc]: pypdf `_doc_common.py` (`metadata`, `outline`, `page_labels`): https://github.com/py-pdf/pypdf/blob/main/pypdf/_doc_common.py
[^pypdfenc]: pypdf docs, "Encryption and Decryption of PDFs": https://pypdf.readthedocs.io/en/stable/user/encryption-decryption.html
[^pypdfencsrc]: pypdf `_encryption.py` (`/AESV2`, `/AESV3`, `PasswordType`): https://github.com/py-pdf/pypdf/blob/main/pypdf/_encryption.py
[^pypi-pypdf]: https://pypi.org/project/pypdf/
[^pikelic]: https://pypi.org/project/pikepdf/ (License-Expression MPL-2.0)
[^pikereadme]: pikepdf README (license, "not for rendering / text extraction"): https://github.com/pikepdf/pikepdf/blob/main/README.md
[^pike3p]: pikepdf third-party licenses map: https://github.com/pikepdf/pikepdf/blob/main/third-party-licenses/README.md . The README mentions a "GnuTLS stack on macOS", but this file says GnuTLS and OpenSSL are *not* bundled on Linux or macOS. The file is the more specific source.
[^pikesec]: pikepdf docs, "PDF security": https://pikepdf.readthedocs.io/en/latest/topics/security.html
[^pypi-pike]: https://pypi.org/project/pikepdf/
[^qpdflic]: qpdf license (Apache-2.0): https://github.com/qpdf/qpdf/blob/main/LICENSE.txt
[^pymupdflic]: PyMuPDF "About", license section: https://pymupdf.readthedocs.io/en/latest/about.html ; PyPI: https://pypi.org/project/PyMuPDF/
[^pypi-pymupdf]: https://pypi.org/project/PyMuPDF/
[^pytesslic]: pytesseract LICENSE (Apache-2.0): https://github.com/madmaze/pytesseract/blob/master/LICENSE
[^pypi-pytess]: https://pypi.org/project/pytesseract/
[^pypi-tesserocr]: https://pypi.org/project/tesserocr/
[^tesslic]: Tesseract LICENSE (Apache-2.0): https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE
[^tessdatalic]: tessdata_best LICENSE (Apache-2.0): https://github.com/tesseract-ocr/tessdata_best/blob/main/LICENSE
[^lept]: Leptonica license: http://leptonica.org/about-the-license.html
[^tessrel]: https://github.com/tesseract-ocr/tesseract/releases
[^ebooklic]: ebooklib LICENSE (AGPL-3.0): https://github.com/aerkalov/ebooklib/blob/master/LICENSE.txt
[^pypi-ebook]: https://pypi.org/project/EbookLib/ (classifier "GNU Affero General Public License v3 or later")
[^pypi-lxml]: https://pypi.org/project/lxml/
[^jinjalic]: Jinja LICENSE (BSD-3-Clause): https://github.com/pallets/jinja/blob/main/LICENSE.txt
[^epubchecklic]: epubcheck LICENSE (BSD-3-Clause): https://github.com/w3c/epubcheck/blob/main/LICENSE
[^epubcheckrel]: https://github.com/w3c/epubcheck/releases
[^crates]: crates.io API metadata (license, version, updated, downloads) for each crate, e.g. https://crates.io/crates/pdfium-render , https://crates.io/crates/hayro , https://crates.io/crates/lopdf , https://crates.io/crates/pdf-extract , https://crates.io/crates/pdf_oxide , https://crates.io/crates/mupdf , https://crates.io/crates/pdfium , https://crates.io/crates/epub-builder , https://crates.io/crates/zip , https://crates.io/crates/tesseract , https://crates.io/crates/leptess , https://crates.io/crates/tesseract-rs
[^pdrreadme]: pdfium-render README (dynamic and static linking, `load_pdf_from_file(path, password)`): https://github.com/ajrcarey/pdfium-render/blob/master/README.md
[^pdrchar]: https://docs.rs/pdfium-render/latest/pdfium_render/prelude/struct.PdfPageTextChar.html
[^pdrdoc]: https://docs.rs/pdfium-render/latest/pdfium_render/prelude/struct.PdfDocument.html
[^pdrpage]: https://docs.rs/pdfium-render/latest/pdfium_render/prelude/struct.PdfPage.html
[^hayroreadme]: hayro README: https://github.com/LaurenzV/hayro/blob/main/README.md
[^hayrocrypto]: hayro-syntax `src/crypto/mod.rs`: https://github.com/LaurenzV/hayro/blob/main/hayro-syntax/src/crypto/mod.rs
[^lopdfcf]: lopdf `src/encryption/crypt_filters.rs`: https://github.com/J-F-Liu/lopdf/blob/main/src/encryption/crypt_filters.rs
[^lopdfdoc]: lopdf `src/document.rs` (`authenticate_user_password`, `authenticate_owner_password`, `decrypt`) and `src/reader.rs` (`load_with_password`): https://github.com/J-F-Liu/lopdf/blob/main/src/document.rs , https://github.com/J-F-Liu/lopdf/blob/main/src/reader.rs
[^oxide]: pdf_oxide README, "License & trademark": https://github.com/yfedoseev/pdf_oxide#license--trademark
[^oxidesrc]: pdf_oxide source tree: https://github.com/yfedoseev/pdf_oxide/tree/main/src/encryption ; repo metadata: https://github.com/yfedoseev/pdf_oxide
[^pk-attr]: https://developer.apple.com/documentation/pdfkit/pdfpage/attributedstring
[^pk-cb]: https://developer.apple.com/documentation/pdfkit/pdfpage/characterbounds(at:)
[^pk-thumb]: https://developer.apple.com/documentation/pdfkit/pdfpage/thumbnail(of:for:)
[^pk-draw]: https://developer.apple.com/documentation/pdfkit/pdfpage/draw(with:to:)
[^pk-outline]: https://developer.apple.com/documentation/pdfkit/pdfdocument/outlineroot
[^pk-label]: https://developer.apple.com/documentation/pdfkit/pdfpage/label
[^pk-attrs]: https://developer.apple.com/documentation/pdfkit/pdfdocument/documentattributes
[^pk-unlock]: https://developer.apple.com/documentation/pdfkit/pdfdocument/unlock(withpassword:)
[^pk-isenc]: https://developer.apple.com/documentation/pdfkit/pdfdocument/isencrypted
[^pk-perm]: https://developer.apple.com/documentation/pdfkit/pdfdocument/permissionsstatus
[^vn1]: https://developer.apple.com/documentation/vision/vnrecognizetextrequest
[^vn2]: https://developer.apple.com/documentation/vision/recognizetextrequest
[^zipf]: ZIPFoundation LICENSE (MIT): https://github.com/weichsel/ZIPFoundation/blob/development/LICENSE
