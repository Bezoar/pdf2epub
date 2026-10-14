"""The package docstring and the API reference page state the stability of each interface
(API-R1)."""

import re
from pathlib import Path

import pytest

import pdf2epub

REPO = Path(__file__).resolve().parents[2]
API_REFERENCE = REPO / "docs" / "reference" / "api.md"


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


@pytest.mark.ac("API-AC16")
@pytest.mark.parametrize(
    "text",
    [
        pytest.param(pdf2epub.__doc__ or "", id="package docstring"),
        pytest.param(API_REFERENCE.read_text(encoding="utf-8"), id="API reference page"),
    ],
)
def test_docs_mark_the_python_api_provisional_and_json_stable(text: str) -> None:
    prose = flat(text)
    assert re.search(r"Python API .*provisional: it may change in any 0\.x release", prose)
    assert re.search(r"--json`*.{0,40}(protocol|contract).{0,60}stable|stable contract", prose)
    assert "--json" in prose


def test_readme_links_the_api_reference_page() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "(docs/reference/api.md)" in readme
