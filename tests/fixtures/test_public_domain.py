"""The committed public-domain sample: provenance, size, no LFS, and no smoke-set file
committed (TST-R5, TST-R6, TST-R7, TST-R8)."""

import hashlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO / "tests" / "fixtures" / "public-domain"
PROVENANCE = SAMPLE_DIR / "PROVENANCE.md"
TESTING_SPEC = REPO / "docs" / "specs" / "testing.md"
MAX_BYTES = 30 * 1024 * 1024
LFS_POINTER = b"version https://git-lfs.github.com/spec/"
COLUMNS = ["File", "Source URL", "Public-domain basis", "SHA-256", "Pages kept"]


def provenance_rows() -> dict[str, dict[str, str]]:
    """PROVENANCE.md's table, keyed by file name."""
    lines = [line for line in PROVENANCE.read_text(encoding="utf-8").splitlines() if line]
    table = [line for line in lines if line.startswith("|")]
    header = [cell.strip() for cell in table[0].strip("|").split("|")]
    assert header == COLUMNS
    rows: dict[str, dict[str, str]] = {}
    for line in table[2:]:
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        row = dict(zip(header, cells, strict=True))
        rows[row["File"]] = row
    return rows


def sample_files() -> list[Path]:
    return sorted(p for p in SAMPLE_DIR.iterdir() if p.is_file() and p != PROVENANCE)


@pytest.mark.ac("TST-AC4")
def test_every_sample_file_has_a_complete_provenance_row() -> None:
    rows = provenance_rows()
    files = sample_files()
    assert files, "the public-domain sample is empty"
    assert sorted(rows) == [p.name for p in files]
    for path in files:
        row = rows[path.name]
        assert re.fullmatch(r"https://\S+", row["Source URL"]), row
        assert row["Public-domain basis"], row
        assert row["SHA-256"] == hashlib.sha256(path.read_bytes()).hexdigest(), path.name
        assert re.fullmatch(r"\d+[\u2013-]\d+ of \d+", row["Pages kept"]), row


@pytest.mark.ac("TST-AC4")
def test_sample_folder_is_at_most_30_mb() -> None:
    assert sum(p.stat().st_size for p in SAMPLE_DIR.rglob("*") if p.is_file()) <= MAX_BYTES


@pytest.mark.ac("TST-AC4")
def test_no_file_is_an_lfs_pointer() -> None:
    for path in (REPO / "tests").rglob("*"):
        if path.is_file():
            with path.open("rb") as f:
                assert not f.read(len(LFS_POINTER)).startswith(LFS_POINTER), path
    attributes = REPO / ".gitattributes"
    assert not attributes.exists() or "lfs" not in attributes.read_text(encoding="utf-8")


@pytest.mark.ac("TST-AC4")
def test_no_smoke_set_file_is_committed() -> None:
    # The smoke set's pinned hashes (TST-R12): none of its files may be committed.
    pinned = set(re.findall(r"`([0-9a-f]{64})`", TESTING_SPEC.read_text(encoding="utf-8")))
    assert len(pinned) >= 14
    committed = {
        hashlib.sha256(path.read_bytes()).hexdigest(): path
        for path in (REPO / "tests").rglob("*.pdf")
    }
    assert [committed[h] for h in pinned & committed.keys()] == []
