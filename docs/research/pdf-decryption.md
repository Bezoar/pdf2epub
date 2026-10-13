# Research: scope of password-based PDF decryption

Ticket: [#3](https://github.com/Bezoar/pdf2epub/issues/3) (parent [#1](https://github.com/Bezoar/pdf2epub/issues/1)).
Researched 2026-10-13. The question: what can "DRM removal with a supplied password
(env or CLI), for personal backups" cover, and how should a batch run sort each
file into *missing password*, *wrong password*, *unsupported DRM*, or
*ok-with-restrictions*?

## TL;DR

- **In scope:** anything that uses the PDF **Standard security handler**
  (`/Encrypt` → `/Filter /Standard`), revisions R2–R6 (RC4-40, RC4-128,
  AES-128, AES-256). A supplied user *or* owner password unlocks the whole
  file, and a file with only an owner password (permission restrictions) opens
  with no password at all. Every permissive library we looked at (pypdf,
  pikepdf/qpdf, pypdfium2/PDFium, pdfminer.six) supports this handler and
  nothing else.
- **Out of scope:** any other `/Filter` value. That covers the public-key or
  certificate handler (`Adobe.PubSec`, which needs an X.509 private key, not a
  password), Adobe Content Server/ADEPT (`EBX_HANDLER`), FileOpen
  (`FOPN_*`), server-policy rights management, and Readium LCP (`.lcpdf` is a
  ZIP package, not a PDF). In these schemes the decryption key comes from
  vendor software or a server, never from a password the user types. The tool
  should report them as `unsupported_drm` and stop.
- **Detection is cheap and needs no password.** The `/Encrypt` dictionary,
  including `/Filter`, `/V`, `/R` and `/P`, is never encrypted itself. All four
  libraries reject non-Standard handlers up front, each with its own error type.
- **Missing vs. wrong password:** most libraries return one "password failed"
  signal. The tool should tell the two apart itself: first try the empty
  password (as the spec says readers must), then the supplied one. If none
  was supplied, the result is `missing_password`; if one was supplied and
  rejected, it is `wrong_password`.

## 1. Background: how PDF encryption is declared

- A PDF is encrypted if and only if the trailer has an `Encrypt` entry. "The
  absence of this entry from the trailer dictionary means that a conforming
  reader shall consider the document to be not encrypted." (ISO 32000-1 §7.6.1)
  [^iso]
- "The encryption dictionary's **Filter** entry identifies the file's security
  handler … PDF specifies a standard password-based security handler that all
  conforming readers shall support, but conforming readers can optionally
  provide additional security handlers of their own." "Standard shall be the name
  of the built-in password-based security handler. Names for other security
  handlers may be registered" (§7.6.1, Table 20) [^iso].
- If `SubFilter` is absent, "only this security handler shall be used when
  opening the document" (Table 20) [^iso]. A reader without that handler
  cannot open the file.
- The encryption dictionary's contents "shall not be encrypted" (§7.6.1)
  [^iso], so `/Filter`, `/V`, `/R`, `/P` and `/Length` can always be read
  without a password. The tool can classify a file before it has any key.

## 2. Taxonomy

| # | Kind | How it shows in the file | What the user supplies | Can permissive libs open it? | Batch class |
|---|---|---|---|---|---|
| 0 | Not encrypted | no `/Encrypt` in trailer | nothing | yes | `ok` |
| 1 | Owner-password only (permissions) | `/Filter /Standard`; empty user password authenticates; `/P` has bits cleared | nothing | yes, with restrictions reported but not enforced | `ok_with_restrictions` |
| 2 | User (open) password | `/Filter /Standard`; empty password fails | user **or** owner password | yes, with the password | `ok`, `missing_password` or `wrong_password` |
| 2a | Encrypted attachments only | `/Filter /Standard`, V=4/5, `StmF`/`StrF` = `Identity`, `EFF` set | nothing for page content | yes; only embedded files are locked | `ok` (warn) |
| 3 | Standard handler, unsupported variant (e.g. ISO/TS 32003 AES-GCM) | `/Filter /Standard` but an unknown `V`, `R` or `CFM` | a password, but the library can't use it | no | `unsupported_encryption` |
| 4 | Public-key/certificate | `/Filter /Adobe.PubSec` (or another PPK handler), `SubFilter adbe.pkcs7.s3/s4/s5` | an X.509 cert and private key, not a password | no | `unsupported_drm` (or `needs_certificate`) |
| 5 | Vendor DRM inside a PDF | `/Filter` = `EBX_HANDLER` (Adobe ACS/ADEPT), `FOPN_*` (FileOpen), other vendor names | an account or device activation through vendor software | no | `unsupported_drm` |
| 6 | Vendor DRM wrapping a PDF | `.lcpdf` ZIP with `license.lcpl` (Readium LCP); `.acsm` token (Adobe) | vendor reading app | no (not a PDF file at all) | `unsupported_drm` (or `not_a_pdf`) |

### 2.1 Standard security handler: owner vs. user password

- The Standard handler allows "access permissions and up to two passwords …:
  an owner password and a user password" (§7.6.3.1) [^iso].
- When opening, a reader "shall first try to authenticate … using the padding
  string … (default user password)". If that fails, "the application should
  prompt for a password. Correctly supplying either password (owner or user
  password) should enable the user to open the document, decrypt it, and
  display it" (§7.6.3.1) [^iso].
- This is how an **owner-password-only** file works: the user password is
  empty, so the file opens and decrypts with no input, and only the `/P` flags
  limit what a viewer should allow.
- Permissions are advisory. "There is nothing inherent in PDF encryption that
  enforces the document permissions specified in the encryption dictionary.
  Conforming readers shall respect the intent of the document creator…"
  (§7.6.3.1) [^iso]. qpdf says the same: "there is *fundamentally no way* to
  prevent an application from disregarding the security restrictions" [^qpdf-enc].
  pikepdf: restrictions "depend entirely on the PDF viewer software to enforce"
  and "pikepdf has no way of enforcing permissions" [^pike-sec] [^pike-api].
  pdfminer.six by default logs a warning that the file "should not allow text
  extraction … Ignoring this field and proceeding", and raises only when
  `check_extractable=True` [^pdfminer-page].
- `/P` is a 32-bit flag set. Only bits 3, 4, 5, 6, 9, 10, 11 and 12 are
  meaningful (print, modify, copy/extract, annotate, fill forms, extract for
  accessibility, assemble, high-quality print) (§7.6.3.2, Table 22) [^iso].
- **Product decision for pdf2epub:** "removing" owner restrictions just means
  opening the file and writing an EPUB. No password is needed, so the
  password feature does not apply. The tool should still record the original
  `/P` in the result (`ok_with_restrictions`) so users can see it.

### 2.2 Standard handler revisions and algorithms

| V | R | Cipher | Introduced | Notes |
|---|---|---|---|---|
| 1 | 2 | RC4, 40-bit | PDF 1.1 | |
| 2 | 3 | RC4, 40–128-bit | PDF 1.4 | |
| 3 | 3 | unpublished | PDF 1.4 | "shall not appear in a conforming PDF file" [^iso]; qpdf "believed to be able to read" [^qpdf-enc] |
| 4 | 4 | crypt filters: `V2` (RC4) or `AESV2` (AES-128-CBC) | PDF 1.5/1.6 | `CF`/`StmF`/`StrF`/`EFF` select the filter per stream or string [^iso] |
| 5 | 5 | AES-256 | Acrobat 9 extension | "never fully specified … should not be used for any purpose other than testing" [^qpdf-enc] |
| 5 | 6 | AES-256 (`AESV3`) | PDF 2.0 (ISO 32000-2) | "the only value that is not deprecated in the PDF 2.0 specification" [^qpdf-enc] |

Sources: ISO 32000-1 Tables 20–21 for V1–4/R2–4 [^iso]; the qpdf encryption
notes for R5/R6 and PDF 2.0 [^qpdf-enc]. qpdf: "40-bit encryption always uses
RC4 … 128-bit can use either RC4 … or, starting with PDF 1.6, AES … 256-bit
encryption always uses AES" [^qpdf-enc].

Library coverage:

- **pypdf:** accepts only `/Filter /Standard` with V in {1,2,3,4,5} and crypt
  filter methods in {`Identity`, `V2`, `AESV2`, `AESV3`}. Anything else raises
  `NotImplementedError` [^pypdf-enc-src]. AES needs `cryptography` or
  `pycryptodome` [^pypdf-encdoc]; without one it raises `DependencyError`
  [^pypdf-err-src].
- **pikepdf/qpdf:** handles up to AES-256 R6. "pikepdf cannot produce or read
  the newer AES-GCM or MAC-protected formats (ISO/TS 32003 and 32004)"
  [^pike-sec]. qpdf's Standard handler "is the only security handler
  implemented by qpdf" [^qpdf-enc].
- **pdfminer.six:** handler registry for V ∈ {1,2,4,5}, revisions (2,3), (4)
  and (5,6) [^pdfminer-doc-src].
- **PDFium (pypdfium2):** loads only `Filter == "Standard"`
  [^pdfium-parser]. `FPDF_GetSecurityHandlerRevision` reports R, or -1 if the
  file is not protected [^pdfium-h].

### 2.3 Public-key (certificate) security handler

- "Only specified recipients shall open the encrypted document … unlike the
  standard security handler, where a password determines access." To decrypt,
  the reader matches a recipient certificate and "the user requires access to
  the corresponding private key, which may require authentication, possibly
  using a password" (§7.6.4.1) [^iso].
- Examples of handler names: "Entrust.PPKEF, Adobe.PPKLite, and Adobe.PubSec".
  `SubFilter` is `adbe.pkcs7.s3`, `adbe.pkcs7.s4` or `adbe.pkcs7.s5`
  (§7.6.4.2) [^iso].
- **What the user would supply:** a certificate and private key (for example
  a PKCS#12 file and its passphrase), not a document password. None of the four
  libraries supports this: pypdf, qpdf, PDFium and pdfminer.six all check for
  `/Standard` and reject anything else (see §3). **Classify as
  `unsupported_drm`**, or as `needs_certificate` if we want to point users to
  Acrobat. Supporting it would be a separate feature with its own crypto
  dependency, not part of "password" scope.

### 2.4 Vendor DRM that lives inside a PDF

These are proprietary security handlers registered under their own `/Filter`
names. The key comes from a vendor plug-in or server; the user never types a
document password. pdf2epub should **only detect and report** them.

- **Adobe Content Server / ADEPT.** Adobe describes ACS as a way to "securely
  distribute and monetize your eBooks and PDF content" and "Sell or lend
  rights-protected eBooks in PDF, EPUB or EPUB3", with readers authorised
  through store credentials and Digital Editions/RMSDK [^adobe-acs]. Adobe's
  RMSDK FAQ describes "an improved and hardened DRM solution to protect PDF and
  ePub files" [^adobe-rmsdk]. Adobe does not publicly document the handler
  name. Community analysis lists `/Filter` **`EBX_HANDLER`** as "Adobe Content
  Server (aka SecurePDF - most eBooks)", alongside `Standard` ("Password
  Security") and `PubSec` ("Certificate Security") [^mobileread]. Users often
  have a `.acsm` file, which is a fulfilment token rather than the book
  [^adobe-acs].
- **FileOpen.** "The FileOpen Plug-in is required to open PDF files encrypted by
  FileOpen rights management software … The plug-in alone will not grant access
  to encrypted files". The plug-in sends a document ID and user token to "the
  publisher's server" for a grant or deny [^fileopen-faq]. Observed `/Filter`
  values start with **`FOPN_`** (e.g. `FOPN_foweb`); Acrobat sends users to a
  plug-in download page for that filter [^w3c-fopn], and Adobe staff confirm it
  is "a custom security handler, so you need the software that implements that
  handler" [^adobe-community-fopn]. These dictionaries have no `/O`, `/U` or
  `/P` keys [^hashcat-fopn], so standard-handler code cannot even begin to
  authenticate.
- **Adobe LiveCycle/AEM Rights Management** (policy-server PDFs). Access is
  set by server-side policies [^aem-rm]. Treat as vendor DRM. We found no
  primary source for its `/Filter` name, but that is fine: the rule below
  classifies **any non-`Standard` filter** the same way.

### 2.5 Vendor DRM that wraps a PDF (not a PDF file)

- **Readium LCP for PDF.** Packages "must" use "the `.lcpdf` extension" and
  "the `application/pdf+lcp` media type". The license sits at
  `license.lcpl`, and each PDF in `readingOrder` carries an `encrypted`
  property with `scheme` `http://readium.org/2014/01/lcp` and algorithm
  `aes256-cbc` [^lcp-pdf]. LCP *does* use a user passphrase: "The User Key is
  the result of applying a hashing function on the User Passphrase" (§4.2)
  [^lcp-spec]. But the published Basic profile "is for test only", and other
  profiles are "defined for use in production" (§6) [^lcp-spec]. EDRLab
  supplies the production module "pre-compiled". The production information "is
  confidential and must be protected by the license provider", and clients must
  be "trusted" and must have signed the LCP Terms of Use, which carry a yearly
  fee. Implementations are then certified ("LCP Certified") [^edrlab-lcp]. A passphrase
  therefore does **not** make LCP a "supplied password" case for an
  independent MIT tool. **Classify as `unsupported_drm`.** Detect by ZIP magic
  (`PK\x03\x04`) plus a `license.lcpl` member, or the `.lcpdf` extension.
- **Adobe `.acsm`.** This is a small XML fulfilment message, not a book. Report
  it as `unsupported_drm` with a hint that it is a download token.

## 3. How libraries report each case

| Situation | pypdf | pikepdf (qpdf) | pypdfium2 (PDFium) | pdfminer.six |
|---|---|---|---|---|
| Not encrypted | `is_encrypted == False` [^pypdf-reader] | `is_encrypted == False` [^pike-api] | `FPDF_GetSecurityHandlerRevision == -1` [^pdfium-h] | `doc.encryption is None` [^pdfminer-doc-src] |
| Owner-only (empty user pwd works) | opens; `decrypt("")` → `PasswordType.USER_PASSWORD` [^pypdf-reader] | opens; `user_password_matched` True, `owner_password_matched` False; `pdf.allow` shows restrictions [^pike-api] | opens; `FPDF_GetDocPermissions` returns `/P` (0xFFFFFFFF if owner-unlocked) [^pdfium-h] | opens; `is_extractable` etc. False, logs a warning [^pdfminer-page] |
| No password given, one required | no exception at open; later `FileNotDecryptedError` on object access [^pypdf-reader-src] | `PasswordError` (sibling of `PdfError`) [^pike-api] [^pike-cpp] | `PdfiumError`, `err_code == FPDF_ERR_PASSWORD` ("Password required or incorrect password") [^pypdfium2-doc] [^pdfium-h] | `PDFPasswordIncorrect` [^pdfminer-doc-src] |
| Wrong password given | `WrongPasswordError` (subclass of `FileNotDecryptedError`) at construction; `decrypt()` returns `NOT_DECRYPTED` [^pypdf-reader-src] [^pypdf-err-src] | `PasswordError` [^pike-api] | same `FPDF_ERR_PASSWORD` [^pdfium-h] | same `PDFPasswordIncorrect` [^pdfminer-doc-src] |
| Non-`Standard` `/Filter` | `NotImplementedError("only Standard PDF encryption handler is available")` [^pypdf-enc-src] | `PdfError` from `qpdf_e_unsupported`, "unsupported encryption filter" [^qpdf-enc-src] [^pike-cpp] [^qpdf-const] | `FPDF_ERR_SECURITY` ("Unsupported security scheme") via `HANDLER_ERROR` [^pdfium-parser] [^pdfium-helpers] | `PDFEncryptionError("Unknown filter: …")` [^pdfminer-doc-src] |
| Standard but unsupported V/R/CFM | `NotImplementedError("Encryption V=… NOT supported")` or `"… Method … NOT supported!"` [^pypdf-enc-src] | `PdfError` (`qpdf_e_unsupported`) [^qpdf-enc-src] | `FPDF_ERR_SECURITY` or `FPDF_ERR_PASSWORD` | `PDFEncryptionError("Unknown algorithm"/"Unsupported revision")` [^pdfminer-doc-src] |

The CLI check `qpdf --requires-password [--password=…]` exits with **0** if
"a password, other than as supplied, is required", **2** if "the file is not
encrypted", and **3** if "the file is encrypted, and correct password (if any)
has been supplied". `--is-encrypted` works "even if you don't know the
password" [^qpdf-cli]. This is useful for scripts and tests, but it cannot
separate missing from wrong either.

**Key point:** apart from pypdf's constructor, no library separates "missing"
from "wrong". PDFium documents a single code for "Password required or
incorrect password" [^pdfium-h].

## 4. Recommended classification algorithm (library-agnostic)

```
classify(path, password|None):
  sniff bytes:
    "PK\x03\x04" with license.lcpl or *.lcpdf  -> unsupported_drm (lcp)
    XML <fulfillmentToken> / *.acsm            -> unsupported_drm (acsm token)
    no "%PDF-"                                 -> not_a_pdf / unreadable
  enc = trailer./Encrypt (readable without any key)
  if enc is None                               -> ok
  if enc./Filter != /Standard:
      /Adobe.PubSec, /Adobe.PPKLite, /Entrust.PPKEF -> unsupported_drm (certificate)
      anything else (EBX_HANDLER, FOPN_*, ...)      -> unsupported_drm (vendor=<Filter>)
  if (V,R,CFM) not supported by our backend    -> unsupported_encryption
  try empty password ""                        # spec: default user password first
     success -> P has restrictive bits ? ok_with_restrictions : ok
  if password is None                          -> missing_password
  try password
     success -> ok   (record user_vs_owner if the backend exposes it)
     failure -> wrong_password
```

Notes:

- **Always try `""` first, even when a password is supplied.** This matches
  §7.6.3.1 [^iso] and lets owner-only files pass in a batch that has a global
  `--password`. pikepdf's default `password` is already `""` [^pike-api], and
  pypdf tries `b""` when none is given [^pypdf-reader-src].
- **Batch passwords:** one password from env or CLI will be "wrong" for every
  file that uses a different password. Consider allowing a list of candidates
  (`--password` repeatable, or `PDF2EPUB_PASSWORD_FILE`). Report
  `wrong_password` only after every candidate fails. qpdf already has a
  `--password-file` pattern [^qpdf-cli].
- **Password encoding:** pikepdf encodes `str` as UTF-8, uses `bytes` as
  given, and pads or truncates to 32 bytes internally; it recommends ASCII
  passwords for compatibility [^pike-api] [^pike-sec]. If a non-ASCII password
  fails, retrying with Latin-1 bytes is a cheap fallback for old R2–R4 files.
- **Mapping to SPEC exit codes:** `docs/SPEC.md` gives `3` for "input
  unreadable/encrypted". Every class except `ok` and `ok_with_restrictions`
  maps to 3. The batch summary (and `--json`, if added) should carry the
  finer class.
- **Restriction reporting:** decode `/P` bits 3/4/5/6/9/10/11/12 per Table 22
  [^iso] (pikepdf exposes `pdf.allow` [^pike-api]; PDFium exposes
  `FPDF_GetDocUserPermissions` [^pdfium-h]). Show these as information only.
  The converter must not refuse to run because of them, or owner-only files
  become unusable.

## 5. Suggested scope statement for SPEC.md

> pdf2epub opens PDFs that use the PDF Standard security handler (RC4/AES,
> revisions 2–6). The user password or owner password can be supplied with
> `--password` or `PDF2EPUB_PASSWORD`. Files that carry only owner permission
> restrictions open with no password, and the restrictions are reported. Files
> protected by any other security handler (certificate/public-key, Adobe
> ADEPT/ACS, FileOpen, rights-management servers) or wrapped in vendor DRM
> containers (Readium LCP `.lcpdf`, Adobe `.acsm`) are detected and reported as
> `unsupported_drm`. pdf2epub does not attempt to bypass them.

This scope works the same whichever backend Q1 picks: all four libraries
implement exactly the Standard handler.

## Open questions

- Does the EPUB output need to carry the source's restrictions in some form
  (for example, a note in the metadata)? This is a product and ethics decision,
  not a technical one.
- Should `needs_certificate` be its own class? It would let users of
  certificate-encrypted corporate PDFs see that the file is not DRM in the
  vendor sense.

## Sources

[^iso]: ISO 32000-1:2008 (PDF 1.7), Adobe-hosted copy, §7.6.1 (Table 20), §7.6.3.1–7.6.3.2 (Tables 21–22), §7.6.4.1–7.6.4.2 — https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf
[^qpdf-enc]: qpdf manual, "PDF Encryption" — https://qpdf.readthedocs.io/en/stable/encryption.html
[^qpdf-cli]: qpdf manual, "Running qpdf" (`--requires-password`, `--is-encrypted`, `--password`, `--password-file`, `--decrypt`, `--show-encryption`) — https://qpdf.readthedocs.io/en/stable/cli.html
[^qpdf-enc-src]: qpdf source, `libqpdf/QPDF_encryption.cc` (`"unsupported encryption filter"`, SubFilter warning) — https://github.com/qpdf/qpdf/blob/main/libqpdf/QPDF_encryption.cc
[^qpdf-const]: qpdf source, `include/qpdf/Constants.h` (`qpdf_e_unsupported`, `qpdf_e_password`) — https://github.com/qpdf/qpdf/blob/main/include/qpdf/Constants.h
[^pike-sec]: pikepdf docs, "PDF security" — https://pikepdf.readthedocs.io/en/latest/topics/security.html
[^pike-api]: pikepdf API, `Pdf.open`, `is_encrypted`, `encryption`, `allow`, `owner_password_matched`, `user_password_matched` — https://pikepdf.readthedocs.io/en/latest/api/main.html
[^pike-cpp]: pikepdf source, `src/core/pikepdf.cpp` (exception translator: `qpdf_e_password` → `PasswordError`, other `QPDFExc` → `PdfError`) — https://github.com/pikepdf/pikepdf/blob/main/src/core/pikepdf.cpp
[^pypdf-encdoc]: pypdf docs, "Encryption and Decryption of PDFs" — https://pypdf.readthedocs.io/en/stable/user/encryption-decryption.html
[^pypdf-reader]: pypdf API, `PdfReader` (`password`, `decrypt`, `PasswordType`, `is_encrypted`) — https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html
[^pypdf-reader-src]: pypdf source, `pypdf/_reader.py` (`_handle_encryption`: empty password tried; `WrongPasswordError` only if a password was supplied; `FileNotDecryptedError` on access) — https://github.com/py-pdf/pypdf/blob/main/pypdf/_reader.py
[^pypdf-enc-src]: pypdf source, `pypdf/_encryption.py` (`Encryption.read`) — https://github.com/py-pdf/pypdf/blob/main/pypdf/_encryption.py
[^pypdf-err-src]: pypdf source, `pypdf/errors.py` — https://github.com/py-pdf/pypdf/blob/main/pypdf/errors.py
[^pdfminer-doc-src]: pdfminer.six source, `pdfminer/pdfdocument.py` (`PDFPasswordIncorrect`, `PDFEncryptionError`, `security_handler_registry`, `_initialize_password`) — https://github.com/pdfminer/pdfminer.six/blob/master/pdfminer/pdfdocument.py
[^pdfminer-page]: pdfminer.six source, `pdfminer/pdfpage.py` (`check_extractable`) — https://github.com/pdfminer/pdfminer.six/blob/master/pdfminer/pdfpage.py
[^pdfium-h]: PDFium public header `fpdfview.h` (`FPDF_ERR_*`, `FPDF_GetDocPermissions`, `FPDF_GetDocUserPermissions`, `FPDF_GetSecurityHandlerRevision`) — https://pdfium.googlesource.com/pdfium/+/refs/heads/main/public/fpdfview.h
[^pdfium-parser]: PDFium `core/fpdfapi/parser/cpdf_parser.cpp` (`SetEncryptHandler`: non-`Standard` → `HANDLER_ERROR`, failed auth → `PASSWORD_ERROR`) — https://pdfium.googlesource.com/pdfium/+/refs/heads/main/core/fpdfapi/parser/cpdf_parser.cpp
[^pdfium-helpers]: PDFium `fpdfsdk/cpdfsdk_helpers.cpp` (`HANDLER_ERROR` → `FPDF_ERR_SECURITY`, `PASSWORD_ERROR` → `FPDF_ERR_PASSWORD`) — https://pdfium.googlesource.com/pdfium/+/refs/heads/main/fpdfsdk/cpdfsdk_helpers.cpp
[^pypdfium2-doc]: pypdfium2 source, `_helpers/document.py` (`PdfDocument` password; `PdfiumError` with `err_code`) — https://github.com/pypdfium2-team/pypdfium2/blob/main/src/pypdfium2/_helpers/document.py
[^adobe-acs]: Adobe, Adobe Content Server product page — https://www.adobe.com/products/contentserver
[^adobe-rmsdk]: Adobe, Adobe Content Server and RMSDK FAQ — https://www.adobe.com/solutions/ebook/rmsdk/faq.html
[^mobileread]: MobileRead forum, list of `/Filter` values (community source; Adobe does not publish the ADEPT handler name) — https://www.mobileread.com/forums/showthread.php?p=993496
[^fileopen-faq]: FileOpen, "FAQ: The FileOpen PDF Plug-In for Adobe Reader/Acrobat" — https://plugin.fileopen.com/faq.aspx
[^w3c-fopn]: W3C bug report noting the `FOPN_foweb` filter and plug-in prompt (secondary) — https://lists.w3.org/Archives/Public/www-international/2015JulSep/0114.html
[^adobe-community-fopn]: Adobe Acrobat SDK community answer on custom security handlers (FileOpen) — https://community.adobe.com/t5/acrobat-sdk-discussions/adobe-plug-in-sdk-how-to-open-a-pdf-document-protected-by-custom-security-handler/m-p/8361560/highlight/true
[^hashcat-fopn]: hashcat forum, `FOPN_foweb` encrypt dict lacks `/O`, `/U`, `/P` (secondary) — https://hashcat.net/forum/thread-13341.html
[^aem-rm]: Adobe AEM Forms 6.1, Rights Management policies (programmatic) — https://help.adobe.com/en_US/AEMForms/6.1/ProgramLC/WS624e3cba99b79e12e69a9941333732bac8-7cc1.2.html
[^lcp-pdf]: Readium, "Readium LCP for PDF 1.0" — https://readium.org/lcp-specs/notes/lcp-for-pdf.html
[^lcp-spec]: Readium, "Readium Licensed Content Protection 1.0" §1.2, §4.2, §6 — https://readium.org/lcp-specs/releases/lcp/latest
[^edrlab-lcp]: EDRLab, "How-to for LCP reading system providers" — https://www.edrlab.org/readium-lcp/how-to-lcp-reading-system-provider/
