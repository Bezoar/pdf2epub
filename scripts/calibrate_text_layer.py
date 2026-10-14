"""Print the text-layer quality check's signals (OCR-R7) on every page of the must-trust and
must-reject fixtures, and how far each set sits from the thresholds (OCR-R8).

The thresholds live in ``src/pdf2epub/ocr/textlayer.py``. They are calibrated so that every
must-trust page passes and every must-reject page fails; this script shows the values they
were chosen from and the margins they leave. Run it after changing a signal, a threshold
or a fixture.

Usage: ``uv run python scripts/calibrate_text_layer.py [--pages]`` (``--pages`` prints one
row per page; by default one row per fixture, with each signal's worst value).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from pdf2epub.ocr.languages import ocr_languages
from pdf2epub.ocr.pages import ocr_directly
from pdf2epub.ocr.signals import language_scripts
from pdf2epub.ocr.textlayer import (
    MAX_GARBAGE_RATIO,
    MIN_LAYER_COVERAGE,
    MIN_PLAUSIBILITY,
    MIN_TOKENS,
    LayerCheck,
    check_layers,
)
from pdf2epub.options import ConversionOptions
from pdf2epub.reflow.extract import read_pages
from pdf2epub.reflow.images import read_images
from pdf2epub.reflow.metadata import DEFAULT_LANGUAGE, read_xmp
from pdf2epub.reflow.parse import ParsedPdf
from pdf2epub.reflow.source import open_source
from pdf2epub.reflow.wordlists import wordlist

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
# Born-digital fixtures with no text layer at all hold nothing to trust.
_NO_TEXT_LAYER = {"image-only.pdf", "blank-pages.pdf"}


def must_trust() -> list[Path]:
    """Every born-digital fixture with a text layer, and every scan with a good invisible
    OCR layer (OCR-AC3)."""
    born = FIXTURES / "born-digital"
    scanned = FIXTURES / "scanned"
    return [
        *sorted(p for p in born.glob("*.pdf") if p.name not in _NO_TEXT_LAYER),
        scanned / "ocr-layer.pdf",
        *sorted(scanned.glob("page-numbers-*.pdf")),
    ]


def must_reject() -> list[Path]:
    """The three must-reject fixtures (TST-R3)."""
    return sorted((FIXTURES / "must-reject").glob("*.pdf"))


@dataclass(frozen=True)
class Row:
    fixture: str
    page: int
    check: LayerCheck


def checks(path: Path) -> list[Row]:
    """The check on every page the conversion would check, as ``ocr_pages`` runs it under
    ``auto`` with default options."""

    options = ConversionOptions()
    source = open_source(path, None)
    with ParsedPdf(path) as pdf:
        pages = list(read_pages(pdf))
        declared = source.language or read_xmp(pdf.xmp()).language
    images = read_images(path)
    languages = ocr_languages(options, declared)
    words = wordlist(options.language or declared or DEFAULT_LANGUAGE)
    layered = [p for p in pages if p.lines and not ocr_directly(p, images.get(p.page, []))]
    found = check_layers(path, None, layered, images, language_scripts(languages), words)
    name = path.relative_to(FIXTURES).as_posix()
    return [Row(name, number, check) for number, check in sorted(found.items())]


def _range(values: list[float]) -> str:
    if not values:
        return "—"
    low, high = min(values), max(values)
    return f"{low:.3f}" if f"{low:.3f}" == f"{high:.3f}" else f"{low:.3f} to {high:.3f}"


def main(argv: list[str]) -> int:
    per_page = "--pages" in argv
    print(
        f"Thresholds: garbage ratio > {MAX_GARBAGE_RATIO} → garbled; word plausibility < "
        f"{MIN_PLAUSIBILITY} (pages with ≥ {MIN_TOKENS} tokens) → implausible_words; "
        f"prior-OCR coverage < {MIN_LAYER_COVERAGE} → low_coverage\n"
    )
    wrong = 0
    totals: dict[str, dict[str, list[float]]] = {}
    for label, paths, should_reject in (
        ("must-trust", must_trust(), False),
        ("must-reject", must_reject(), True),
    ):
        print(f"## {label}\n")
        print("| fixture | pages | layer | garbage | plausibility | tokens | coverage | verdicts |")
        print("|---|---|---|---|---|---|---|---|")
        total = totals.setdefault(label, {"garbage": [], "plausibility": [], "coverage": []})
        for path in paths:
            rows = checks(path)
            groups = [[row] for row in rows] if per_page else [rows]
            for group in groups:
                if not group:
                    continue
                found = [r.check for r in group]
                garbage = [c.garbage for c in found]
                plausible = [c.plausibility for c in found if c.tokens >= MIN_TOKENS]
                coverage = [c.coverage for c in found if c.coverage is not None]
                total["garbage"] += garbage
                total["plausibility"] += plausible
                total["coverage"] += coverage
                verdicts: dict[str, int] = {}
                for check in found:
                    verdict = check.reason or "trusted"
                    verdicts[verdict] = verdicts.get(verdict, 0) + 1
                    wrong += (check.reason is not None) != should_reject
                pages = f"{group[0].page}" if per_page else f"{len(group)}"
                layers = sorted({"prior OCR" if c.prior_ocr else "typeset" for c in found})
                tokens = [c.tokens for c in found]
                print(
                    f"| {group[0].fixture} | {pages} | {', '.join(layers)} | {_range(garbage)} "
                    f"| {_range(plausible)} | {min(tokens)} to {max(tokens)} | {_range(coverage)} "
                    f"| {', '.join(f'{v} {k}' for k, v in sorted(verdicts.items()))} |"
                )
        print()
    print("## Ranges over all checked pages\n")
    for label, signals in totals.items():
        for signal, values in signals.items():
            print(f"- {label} {signal}: {_range(values)} ({len(values)} pages)")
    print(f"\n{wrong} page(s) on the wrong side of a threshold")
    return 1 if wrong else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
