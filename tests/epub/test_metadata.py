"""Metadata, language and deterministic output (RFL-R31-R33, EPUB-R13-R15), read back
from the written EPUB's package document.

Expected values come from the metadata fixtures' documented content and from the spec:
the identifier is recomputed here from the file's bytes and the pdf2epub namespace UUID,
which EPUB-R13 fixes once ("generated once and fixed in the code").
"""

import hashlib
import time
import uuid
import zipfile
from pathlib import Path

import pytest
from conftest import FIXTURES, NOVEL
from lxml import etree
from test_text import OPF_NS
from test_text import convert as convert_copy

from pdf2epub import ConversionOptions, ConversionResult

METADATA = FIXTURES / "metadata"
JANE_DOE = METADATA / "Jane Doe - A Book.pdf"
SCAN = METADATA / "scan0001.pdf"
LANG_FR = METADATA / "lang-fr.pdf"
XMP = METADATA / "xmp.pdf"

DC = "{http://purl.org/dc/elements/1.1/}"
# pdf2epub's fixed namespace for dc:identifier (EPUB-R13).
NAMESPACE = uuid.UUID("de933f19-549d-40b3-bd7c-840b7f360868")


def opf(epub: Path) -> etree._Element:
    with zipfile.ZipFile(epub) as archive:
        return etree.fromstring(archive.read("OEBPS/content.opf"))


def dc(package: etree._Element, name: str) -> list[str]:
    metadata = package.find("opf:metadata", OPF_NS)
    assert metadata is not None
    return [element.text or "" for element in metadata.iter(f"{DC}{name}")]


def modified(package: etree._Element) -> str:
    [meta] = [
        m
        for m in package.iterfind("opf:metadata/opf:meta", OPF_NS)
        if m.get("property") == "dcterms:modified"
    ]
    return meta.text or ""


def convert(
    source: Path, folder: Path, options: ConversionOptions | None = None
) -> tuple[ConversionResult, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    return convert_copy(source, folder, options)


def codes(result: ConversionResult) -> list[str]:
    return [issue.code.value for issue in result.issues]


@pytest.mark.ac("RFL-AC22")
def test_metadata_comes_from_overrides_then_info_then_the_file_name(tmp_path: Path) -> None:
    _, path = convert(JANE_DOE, tmp_path / "default")
    assert dc(opf(path), "title") == ["Real Title"]
    assert dc(opf(path), "creator") == ["Jane Doe"]

    _, path = convert(JANE_DOE, tmp_path / "override", ConversionOptions(title="Override"))
    assert dc(opf(path), "title") == ["Override"]
    assert dc(opf(path), "creator") == ["Jane Doe"]

    _, path = convert(SCAN, tmp_path / "scan")
    assert dc(opf(path), "title") == ["scan0001"]
    assert dc(opf(path), "creator") == []


def test_xmp_metadata_comes_before_the_info_dictionary(tmp_path: Path) -> None:
    # RFL-R31, RFL-R32: XMP title, creators (in order) and language win over Info.
    _, path = convert(XMP, tmp_path)
    package = opf(path)
    assert dc(package, "title") == ["XMP Title"]
    assert dc(package, "creator") == ["Ann Example", "Bob Example"]
    assert dc(package, "language") == ["de"]
    # EPUB-R14: no modification date, so the creation date, in UTC.
    assert modified(package) == "2011-02-03T02:05:06Z"


@pytest.mark.ac("RFL-AC23")
def test_a_book_with_no_language_is_english_with_a_warning(tmp_path: Path) -> None:
    result, path = convert(SCAN, tmp_path / "default")
    assert dc(opf(path), "language") == ["en"]
    assert "language_defaulted" in codes(result)
    [issue] = [i for i in result.issues if i.code.value == "language_defaulted"]
    assert issue.severity.value == "warning"

    result, path = convert(SCAN, tmp_path / "de", ConversionOptions(language="de"))
    assert dc(opf(path), "language") == ["de"]
    assert "language_defaulted" not in codes(result)

    result, path = convert(LANG_FR, tmp_path / "fr")
    assert dc(opf(path), "language") == ["fr"]
    assert "language_defaulted" not in codes(result)


@pytest.mark.ac("EPUB-AC9")
def test_the_package_metadata(tmp_path: Path) -> None:
    _, path = convert(JANE_DOE, tmp_path / "jane", ConversionOptions(authors=["A", "B"]))
    package = opf(path)
    assert dc(package, "creator") == ["A", "B"]
    assert dc(package, "language") == ["en"]
    digest = hashlib.sha256(JANE_DOE.read_bytes()).hexdigest()
    assert dc(package, "identifier") == [f"urn:uuid:{uuid.uuid5(NAMESPACE, digest)}"]
    assert package.get("unique-identifier") is not None
    assert modified(package) == "2020-01-02T03:04:05Z"

    _, path = convert(SCAN, tmp_path / "scan")
    assert modified(opf(path)) == "1980-01-01T00:00:00Z"


@pytest.mark.ac("EPUB-AC10")
def test_the_same_input_gives_a_byte_identical_epub(tmp_path: Path) -> None:
    _, first = convert(NOVEL, tmp_path / "first")
    time.sleep(2.1)  # past the 2-second resolution of zip timestamps
    _, second = convert(NOVEL, tmp_path / "second")

    assert first != second
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(second) as archive:
        assert {info.date_time for info in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
