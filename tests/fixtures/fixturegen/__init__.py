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
        cjk,
        damaged,
        drm,
        encrypted,
        headerrow,
        headings,
        hostile,
        images,
        layouts,
        metadata,
        not_a_pdf,
        novel,
        oversized,
        pagenumbers,
        scanlayers,
        scans,
        structure,
        textlayers,
        trusted,
        twopage,
        typography,
        verse,
    )

    # The novel comes first: the cross-reference fixture is cut from it.
    return [
        Fixture(novel.PATH, novel.GROUND_TRUTH, novel.build),
        Fixture(damaged.TRUNCATED, None, damaged.build_truncated),
        Fixture(damaged.NO_XREF, None, damaged.build_no_xref),
        Fixture(damaged.ZERO_PAGES, None, damaged.build_zero_pages),
        Fixture(damaged.IMAGE_BOMB, None, damaged.build_image_bomb),
        Fixture(damaged.STREAM_BOMB, None, damaged.build_stream_bomb),
        Fixture(damaged.STALE_XREF, None, damaged.build_stale_xref),
        Fixture(damaged.UNMATCHED_PAGES, None, damaged.build_unmatched_pages),
        Fixture(damaged.MISSING_PAGE, None, damaged.build_missing_page),
        Fixture(damaged.XREF_LOOP, None, damaged.build_xref_loop),
        Fixture(damaged.OBJSTM_LOOP, None, damaged.build_objstm_loop),
        Fixture(damaged.OBJSTM_ROOT_LOOP, None, damaged.build_objstm_root_loop),
        Fixture(damaged.UNLOADABLE_PAGE, None, damaged.build_unloadable_page),
        Fixture(damaged.UNTYPED_PAGE, None, damaged.build_untyped_page),
        Fixture(damaged.UNLOADABLE_FIRST_PAGE, None, damaged.build_unloadable_first_page),
        Fixture(damaged.UNPARSEABLE_PAGE, None, damaged.build_unparseable_page),
        Fixture(hostile.PATH, hostile.GROUND_TRUTH, hostile.build),
        Fixture(blank.BLANK, None, blank.build_blank),
        Fixture(blank.PLUS_TEXT, blank.PLUS_TEXT_TRUTH, blank.build_plus_text),
        Fixture(blank.BLANK_INSIDE, blank.BLANK_INSIDE_TRUTH, blank.build_blank_inside),
        Fixture(not_a_pdf.PATH, None, not_a_pdf.build),
        Fixture(typography.PATH, typography.GROUND_TRUTH, typography.build),
        Fixture(novel.NO_OUTLINE, novel.NO_OUTLINE_TRUTH, novel.build_no_outline),
        Fixture(
            novel.TWO_ENTRY_OUTLINE, novel.TWO_ENTRY_OUTLINE_TRUTH, novel.build_two_entry_outline
        ),
        Fixture(headings.PATH, headings.GROUND_TRUTH, headings.build),
        Fixture(oversized.PATH, oversized.GROUND_TRUTH, oversized.build),
        Fixture(oversized.GIANT, oversized.GIANT_TRUTH, oversized.build_giant),
        Fixture(structure.IMAGE_ONLY, None, structure.build_image_only),
        Fixture(
            structure.IMAGE_BETWEEN_LINES,
            structure.IMAGE_BETWEEN_LINES_TRUTH,
            structure.build_image_between_lines,
        ),
        Fixture(
            structure.OUTLINE_TO_PAGE,
            structure.OUTLINE_TO_PAGE_TRUTH,
            structure.build_outline_to_page,
        ),
        Fixture(structure.IMAGE_PAGE, structure.IMAGE_PAGE_TRUTH, structure.build_image_page),
        Fixture(
            pagenumbers.PAGE_LABELS, pagenumbers.PAGE_LABELS_TRUTH, pagenumbers.build_page_labels
        ),
        Fixture(pagenumbers.ODD_LABELS, pagenumbers.ODD_LABELS_TRUTH, pagenumbers.build_odd_labels),
        Fixture(pagenumbers.MISSING, pagenumbers.MISSING_TRUTH, pagenumbers.build_missing),
        Fixture(pagenumbers.REPEATED, pagenumbers.REPEATED_TRUTH, pagenumbers.build_repeated),
        Fixture(pagenumbers.TRIPLED, pagenumbers.TRIPLED_TRUTH, pagenumbers.build_tripled),
        Fixture(
            pagenumbers.FRONT_MATTER,
            pagenumbers.FRONT_MATTER_TRUTH,
            pagenumbers.build_front_matter,
        ),
        Fixture(verse.PATH, verse.GROUND_TRUTH, verse.build),
        Fixture(cjk.PATH, cjk.GROUND_TRUTH, cjk.build),
        Fixture(twopage.PATH, twopage.GROUND_TRUTH, twopage.build),
        Fixture(headerrow.PATH, headerrow.GROUND_TRUTH, headerrow.build),
        Fixture(layouts.TWO_COLUMN, layouts.TWO_COLUMN_TRUTH, layouts.build_two_column),
        Fixture(layouts.COMPLEX_PAGE, layouts.COMPLEX_PAGE_TRUTH, layouts.build_complex_page),
        Fixture(layouts.FALLBACKS, layouts.FALLBACKS_TRUTH, layouts.build_fallbacks),
        Fixture(layouts.COMPLEX_PAGES, layouts.COMPLEX_PAGES_TRUTH, layouts.build_complex_pages),
        Fixture(encrypted.AES256, encrypted.AES256_TRUTH, encrypted.build_aes256),
        Fixture(encrypted.AES128, encrypted.AES128_TRUTH, encrypted.build_aes128),
        Fixture(encrypted.RC4_128, encrypted.RC4_128_TRUTH, encrypted.build_rc4_128),
        Fixture(
            encrypted.OWNER_RESTRICTED,
            encrypted.OWNER_RESTRICTED_TRUTH,
            encrypted.build_owner_restricted,
        ),
        Fixture(encrypted.OWNER_ALL, encrypted.OWNER_ALL_TRUTH, encrypted.build_owner_all),
        Fixture(
            encrypted.USER_OWNER_RESTRICTED,
            encrypted.USER_OWNER_RESTRICTED_TRUTH,
            encrypted.build_user_owner_restricted,
        ),
        Fixture(encrypted.OWNER_PADDED, encrypted.OWNER_PADDED_TRUTH, encrypted.build_owner_padded),
        Fixture(
            encrypted.OWNER_PADDED_R5,
            encrypted.OWNER_PADDED_R5_TRUTH,
            encrypted.build_owner_padded_r5,
        ),
        Fixture(drm.EBX_HANDLER, None, drm.build_ebx_handler),
        Fixture(drm.ADOBE_PUBSEC, None, drm.build_adobe_pubsec),
        Fixture(drm.FOPN_FOWEB, None, drm.build_fopn_foweb),
        Fixture(drm.UNKNOWN_CRYPT_FILTER, None, drm.build_unknown_crypt_filter),
        Fixture(drm.LCP, None, drm.build_lcp),
        Fixture(drm.ACSM, None, drm.build_acsm),
        Fixture(images.PATH, images.GROUND_TRUTH, images.build),
        Fixture(metadata.JANE_DOE, None, metadata.build_jane_doe),
        Fixture(metadata.SCAN, None, metadata.build_scan),
        Fixture(metadata.LANG_FR, None, metadata.build_lang_fr),
        Fixture(metadata.XMP, None, metadata.build_xmp),
        # The scans are renders of the born-digital fixtures above.
        Fixture(scans.NOVEL_CLEAN, scans.NOVEL_CLEAN_TRUTH, scans.build_novel_clean),
        Fixture(scans.TWO_PAGES, scans.TWO_PAGES_TRUTH, scans.build_two_pages),
        Fixture(scans.TWO_COLUMN, scans.TWO_COLUMN_TRUTH, scans.build_two_column),
        Fixture(scans.IMAGE_ONLY, scans.IMAGE_ONLY_TRUTH, scans.build_image_only),
        Fixture(scans.BLANK_PAGE, scans.BLANK_PAGE_TRUTH, scans.build_blank_page),
        Fixture(scans.NOISE, scans.NOISE_TRUTH, scans.build_noise),
        Fixture(scans.SKEW, scans.SKEW_TRUTH, scans.build_skew),
        Fixture(scans.ROTATED, scans.ROTATED_TRUTH, scans.build_rotated),
        Fixture(scans.LOW_DPI, scans.LOW_DPI_TRUTH, scans.build_low_dpi),
        Fixture(scans.EMPHASIS, scans.EMPHASIS_TRUTH, scans.build_emphasis),
        # The text-layer quality check's fixtures (OCR-AC3 to OCR-AC6).
        Fixture(textlayers.OCR_LAYER, textlayers.OCR_LAYER_TRUTH, textlayers.build_ocr_layer),
        Fixture(
            textlayers.GARBLED_LAYER,
            textlayers.GARBLED_LAYER_TRUTH,
            textlayers.build_garbled_layer,
        ),
        Fixture(textlayers.HALF_LAYER, textlayers.HALF_LAYER_TRUTH, textlayers.build_half_layer),
        Fixture(scanlayers.LOW_BOXES, scanlayers.LOW_BOXES_TRUTH, scanlayers.build_low_boxes),
        Fixture(scanlayers.DARK_BORDER, scanlayers.DARK_BORDER_TRUTH, scanlayers.build_dark_border),
        Fixture(scanlayers.ILLUSTRATED, scanlayers.ILLUSTRATED_TRUTH, scanlayers.build_illustrated),
        Fixture(
            scanlayers.HALF_LAYER_BORDER,
            scanlayers.HALF_LAYER_BORDER_TRUTH,
            scanlayers.build_half_layer_border,
        ),
        Fixture(
            scanlayers.HALF_LAYER_NEGATIVE,
            scanlayers.HALF_LAYER_NEGATIVE_TRUTH,
            scanlayers.build_half_layer_negative,
        ),
        Fixture(
            textlayers.NO_TOUNICODE, textlayers.NO_TOUNICODE_TRUTH, textlayers.build_no_tounicode
        ),
        # A must-trust page that reproduces a real-world rejection (#89).
        Fixture(trusted.TYPE3_NAMES, trusted.TYPE3_NAMES_TRUTH, trusted.build_type3_names),
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
