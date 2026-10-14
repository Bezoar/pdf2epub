"""The suite's epubcheck step itself: an EPUB with an epubcheck error fails the test that
checks it (TST-R19)."""

import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import NOVEL
from conftest import convert_copy as convert

GHOST = b'<item id="ghost" href="ghost.xhtml" media-type="application/xhtml+xml"/>'


def break_manifest(epub: Path, broken: Path) -> None:
    """Copy ``epub`` to ``broken`` with a manifest entry for a file that doesn't exist."""
    with zipfile.ZipFile(epub) as src, zipfile.ZipFile(broken, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename.endswith(".opf"):
                assert b"</manifest>" in data
                data = data.replace(b"</manifest>", GHOST + b"</manifest>")
            dst.writestr(info, data)


@pytest.mark.ac("TST-AC13")
def test_epubcheck_failure_fails_the_test(
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    epubcheck: Callable[[Path], None],
) -> None:
    valid = convert(NOVEL, tmp_path)
    # Outside tmp_path, so the suite-wide epubcheck of tmp_path doesn't see it.
    broken = tmp_path_factory.mktemp("broken") / "broken.epub"
    break_manifest(valid, broken)

    epubcheck(valid)
    with pytest.raises(pytest.fail.Exception) as failure:
        epubcheck(broken)
    assert "ghost.xhtml" in str(failure.value)
    assert "ERROR" in str(failure.value)
