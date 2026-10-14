"""Suite-wide test policy from coding.md section 6."""

import os
import shutil

import pytest

# Set in the CI coverage job, where a skipped `tesseract` test must fail the job.
REQUIRE_TESSERACT = "PDF2EPUB_REQUIRE_TESSERACT"


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("tesseract") is None or shutil.which("tesseract"):
        return
    if os.environ.get(REQUIRE_TESSERACT) == "1":
        pytest.fail(f"Tesseract is not on PATH, and {REQUIRE_TESSERACT}=1 forbids skipping")
    pytest.skip("Tesseract is not on PATH")
