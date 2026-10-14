"""Fixture generators are deterministic, match the committed fixtures and ship ground
truth; the product never imports ReportLab (TST-R1, TST-R2)."""

import re
import subprocess
import sys
from pathlib import Path

import pytest
from fixturegen import registry

FIXTURES = Path(__file__).resolve().parent
GENERATE = FIXTURES / "generate.py"


def generate(out_dir: Path) -> dict[str, bytes]:
    """Run every generator, as a user would, into ``out_dir``; return the files by path."""
    out_dir.mkdir()
    proc = subprocess.run(
        [sys.executable, str(GENERATE), str(out_dir)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return {
        path.relative_to(out_dir).as_posix(): path.read_bytes()
        for path in sorted(out_dir.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, bytes], ...]:
    root = tmp_path_factory.mktemp("generated")
    return generate(root / "a"), generate(root / "b")


@pytest.mark.ac("TST-AC1")
def test_two_runs_are_byte_identical(generated: tuple[dict[str, bytes], ...]) -> None:
    first, second = generated
    assert first, "the generators wrote nothing"
    assert first.keys() == second.keys()
    differing = [path for path in first if first[path] != second[path]]
    assert differing == []


@pytest.mark.ac("TST-AC1")
def test_generated_files_match_the_committed_fixtures(
    generated: tuple[dict[str, bytes], ...],
) -> None:
    first, _ = generated
    stale = [path for path, data in first.items() if (FIXTURES / path).read_bytes() != data]
    assert stale == [], "regenerate with: uv run python tests/fixtures/generate.py"


@pytest.mark.ac("TST-AC1")
def test_every_text_based_fixture_has_ground_truth_beside_it(
    generated: tuple[dict[str, bytes], ...],
) -> None:
    first, _ = generated
    for fixture in registry():
        assert fixture.path in first
        if not fixture.text_based:
            assert fixture.ground_truth is None, f"{fixture.path} has no text of its own"
            continue
        assert fixture.ground_truth is not None, f"{fixture.path} has no ground truth"
        assert Path(fixture.ground_truth).parent == Path(fixture.path).parent
        assert first[fixture.ground_truth].decode("utf-8").strip()


@pytest.mark.ac("TST-AC1")
def test_novel_ground_truth_is_the_text_on_its_pages() -> None:
    # Ground truth is checked independently of the generator: every word pdfium extracts
    # from the novel's body (after rejoining hyphenated line ends) is in the ground truth,
    # in order.
    import pypdfium2 as pdfium

    novel = FIXTURES / "born-digital" / "novel.pdf"
    truth = (FIXTURES / "born-digital" / "novel.txt").read_text(encoding="utf-8").split()
    document = pdfium.PdfDocument(novel)
    pages: list[str] = []
    for index in range(len(document)):
        page_lines = document[index].get_textpage().get_text_range().splitlines()
        # Drop furniture: the running header (every page but the chapter openers, which
        # are every fourth page) and the page number at the foot.
        if index % 4 != 0:
            page_lines = page_lines[1:]
        body = " ".join(page_lines)
        assert re.search(rf"{index + 1}$", body), f"page {index + 1} has no folio"
        pages.append(body.removesuffix(str(index + 1)))
    # pdfium marks a hyphen it takes for a line-end break as U+FFFE and joins the lines.
    text = " ".join(pages).replace("￾ ", "").replace("￾", "")
    assert text.split() == truth


@pytest.mark.ac("TST-AC1")
def test_importing_pdf2epub_does_not_import_reportlab() -> None:
    code = (
        "import pkgutil, sys, importlib, pdf2epub\n"
        "for m in pkgutil.walk_packages(pdf2epub.__path__, 'pdf2epub.'):\n"
        "    if m.name != 'pdf2epub.__main__':\n"
        "        importlib.import_module(m.name)\n"
        "print(sorted(n for n in sys.modules if n.split('.')[0] == 'reportlab'))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]"
