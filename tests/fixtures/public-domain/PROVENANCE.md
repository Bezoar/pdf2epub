# Public-domain sample: provenance

Every file in this folder is a clearly public-domain source ([TST-R5](../../../docs/specs/testing.md#tst-r5)), trimmed to a representative page range with pypdf ([TST-R7](../../../docs/specs/testing.md#tst-r7)). No other third-party PDF may be committed ([TST-R8](../../../docs/specs/testing.md#tst-r8)). The table is read by `tests/fixtures/test_public_domain.py`: keep one row per file, and update the SHA-256 whenever a file changes.

| File | Source URL | Public-domain basis | SHA-256 | Pages kept |
|---|---|---|---|---|
| `nasa-sp-4319-premonition.pdf` | https://www.nasa.gov/wp-content/uploads/2023/04/sp-4319.pdf | US government work: NASA SP-4319, Robert S. Arrighi, *Revolutionary Atmosphere: The Story of the Altitude Wind Tunnel and the Space Power Chambers* (NASA History Division, 2010) | `196036282fe4639755c01426e1d63b318516e3c6505ae8d1fb5204a60c5bc681` | 23–40 of 414 |

## How each file was made

### `nasa-sp-4319-premonition.pdf`

Chapter 1, "Premonition", of NASA SP-4319: born-digital text with running headers (`Premonition` and `Revolutionary Atmosphere`, each with the page number), photographs with captions, and endnotes. The downloaded file's SHA-256 was `6a18d02a4b4be8710dd670811800b9a2819cb8b3e6fc94c3305bd805a2018321` (the smoke set's S2, fetched on 2026-10-13). It was trimmed with pypdf 6.20.1:

1. PDF pages 23–40 (1-based, inclusive) were copied into a new document, in order.
2. The original page labels of those pages were kept: `Sec1:2` to `Sec1:19`.
3. The original Info `/CreationDate` and `/ModDate` were kept. Nothing else from the Info dictionary or the XMP was kept (neither names a title or an author).
4. The catalog `/Lang` was set to `en-US`. The original declares no language; the book is in US English.
5. Identical objects were merged (`compress_identical_objects`) and the file was written.

```python
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

reader = PdfReader("sp-4319.pdf")
writer = PdfWriter()
for i in range(22, 40):
    writer.add_page(reader.pages[i])
writer.set_page_label(0, 17, style="/D", prefix="Sec1:", start=2)
writer.add_metadata({k: reader.metadata[k] for k in ("/CreationDate", "/ModDate")})
writer._root_object[NameObject("/Lang")] = TextStringObject("en-US")
writer.compress_identical_objects()
with open("nasa-sp-4319-premonition.pdf", "wb") as f:
    writer.write(f)
```
