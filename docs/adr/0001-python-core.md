# Python for the core and CLI

pdf2epub's core and CLI are written in Python (≥ 3.12). It has the strongest permissively licensed PDF stack (pypdfium2, pdfminer.six) and fast iteration for the heuristic-heavy layout and OCR work, and coverage.py measures branch coverage reliably, which the v1 bar requires. Front ends, the planned macOS app included, drive the CLI's `--json` event stream as a subprocess, so the core language doesn't constrain them.

## Considered Options

- **Rust:** one fast binary and a natural fit with Tauri and UniFFI-generated Swift bindings. Rejected for v1: heuristic work iterates more slowly, PDFium still ships as a separate library, and `cargo llvm-cov --branch` needs a nightly toolchain. Kept on the roadmap as a possible port.
- **Swift:** cheapest for a Mac app, but weak on Linux, and PDFKit's decryption support is undocumented.

## Consequences

GUIs ship a frozen CLI helper (e.g. PyInstaller) rather than embedding CPython. Tesseract and PDFium are native dependencies outside Python's control.
