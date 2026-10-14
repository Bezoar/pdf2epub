"""Deterministic generators for the synthetic test fixtures (TST-R1, TST-R2).

Each generator writes its files under an output folder, at the same relative paths the
committed copies have under ``tests/fixtures/``. Running every generator twice with the
same tool versions gives byte-identical files: seeds, timestamps and document IDs are
fixed, and PDFs are written uncompressed so the bytes don't depend on the zlib build
(the decompression bombs use ``rawpdf``'s own deflate encoder instead).

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
    from fixturegen import (
        blank,
        damaged,
        headings,
        hostile,
        not_a_pdf,
        novel,
        oversized,
        typography,
    )

    # The novel comes first: the cross-reference fixture is cut from it.
    return [
        Fixture(novel.PATH, novel.GROUND_TRUTH, novel.build),
        Fixture(damaged.TRUNCATED, None, damaged.build_truncated),
        Fixture(damaged.NO_XREF, None, damaged.build_no_xref),
        Fixture(damaged.ZERO_PAGES, None, damaged.build_zero_pages),
        Fixture(damaged.IMAGE_BOMB, None, damaged.build_image_bomb),
        Fixture(damaged.STREAM_BOMB, None, damaged.build_stream_bomb),
        Fixture(hostile.PATH, hostile.GROUND_TRUTH, hostile.build),
        Fixture(blank.BLANK, None, blank.build_blank),
        Fixture(blank.PLUS_TEXT, blank.PLUS_TEXT_TRUTH, blank.build_plus_text),
        Fixture(not_a_pdf.PATH, None, not_a_pdf.build),
        Fixture(typography.PATH, typography.GROUND_TRUTH, typography.build),
        Fixture(novel.NO_OUTLINE, novel.NO_OUTLINE_TRUTH, novel.build_no_outline),
        Fixture(
            novel.TWO_ENTRY_OUTLINE, novel.TWO_ENTRY_OUTLINE_TRUTH, novel.build_two_entry_outline
        ),
        Fixture(headings.PATH, headings.GROUND_TRUTH, headings.build),
        Fixture(oversized.PATH, oversized.GROUND_TRUTH, oversized.build),
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
