"""Deterministic generators for the synthetic test fixtures (TST-R1, TST-R2).

Each generator writes its files under an output folder, at the same relative paths the
committed copies have under ``tests/fixtures/``. Running every generator twice with the
same tool versions gives byte-identical files: seeds, timestamps and document IDs are
fixed, and PDFs are written uncompressed so the bytes don't depend on the zlib build.

Every fixture generated from text also writes that text as its ground truth, beside it.

Run them all with ``uv run python tests/fixtures/generate.py [OUT_DIR]``; the default
output folder is ``tests/fixtures/`` itself, which refreshes the committed copies.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Fixture:
    """One generated fixture: its file, its ground truth (if text-based) and its builder."""

    path: str
    """Path of the fixture, relative to the output folder."""
    ground_truth: str | None
    """Path of its ground-truth text, relative to the output folder; None if not text-based."""
    build: Callable[[Path], None]
    """Writes the fixture (and its ground truth) under the given output folder."""


def registry() -> list[Fixture]:
    """Every fixture generator, in a fixed order."""
    from fixturegen import not_a_pdf, novel

    return [
        Fixture(novel.PATH, novel.GROUND_TRUTH, novel.build),
        Fixture(not_a_pdf.PATH, None, not_a_pdf.build),
    ]


def generate_all(out_dir: Path) -> list[Path]:
    """Run every generator into ``out_dir`` and return the files written."""
    written: list[Path] = []
    for fixture in registry():
        fixture.build(out_dir)
        written.append(out_dir / fixture.path)
        if fixture.ground_truth is not None:
            written.append(out_dir / fixture.ground_truth)
    return written
