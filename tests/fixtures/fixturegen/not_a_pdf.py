"""The damaged fixture ``damaged/not-a-pdf.pdf`` (TST-R1): a plain-text file with a
``.pdf`` name. It holds no ``%PDF-`` anywhere, so the content check (BAT-R4) rejects it
as ``not_a_pdf`` whatever its name says.
"""

from pathlib import Path

PATH = "damaged/not-a-pdf.pdf"

TEXT = (
    "This is a plain-text file, not a PDF.\n"
    "Its name ends in .pdf, but its bytes do not start a PDF document.\n"
)


def build(out_dir: Path) -> None:
    target = out_dir / PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(TEXT.encode("ascii"))
