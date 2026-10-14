"""The written EPUB's container, package document and spine, read back from disk and
checked with epubcheck (EPUB-R2, EPUB-R4, EPUB-R17, TST-R19)."""

import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import NOVEL, PUBLIC_DOMAIN_SAMPLE
from conftest import convert_copy as convert
from lxml import etree

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
}
MEDIA_TYPES = {
    ".xhtml": "application/xhtml+xml",
    ".css": "text/css",
    ".ncx": "application/x-dtbncx+xml",
    ".png": "image/png",
}


def package(epub: Path) -> tuple[zipfile.ZipFile, str, etree._Element]:
    archive = zipfile.ZipFile(epub)
    container = etree.fromstring(archive.read("META-INF/container.xml"))
    [rootfile] = container.findall("c:rootfiles/c:rootfile", NS)
    opf_path = rootfile.get("full-path")
    assert opf_path is not None
    return archive, opf_path, etree.fromstring(archive.read(opf_path))


@pytest.mark.ac("EPUB-AC1")
@pytest.mark.parametrize("source", [NOVEL, PUBLIC_DOMAIN_SAMPLE], ids=["novel", "sample"])
def test_container_layout(source: Path, tmp_path: Path) -> None:
    epub = convert(source, tmp_path)

    with zipfile.ZipFile(epub) as archive:
        first = archive.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"
        for info in archive.infolist()[1:]:
            assert info.compress_type == zipfile.ZIP_DEFLATED, info.filename
    archive, opf_path, _ = package(epub)
    assert opf_path == "OEBPS/content.opf"
    rootfile = etree.fromstring(archive.read("META-INF/container.xml")).find(
        "c:rootfiles/c:rootfile", NS
    )
    assert rootfile is not None
    assert rootfile.get("media-type") == "application/oebps-package+xml"


@pytest.mark.ac("EPUB-AC1")
@pytest.mark.parametrize("source", [NOVEL, PUBLIC_DOMAIN_SAMPLE], ids=["novel", "sample"])
def test_manifest_lists_every_file_and_spine_puts_nav_first(source: Path, tmp_path: Path) -> None:
    epub = convert(source, tmp_path)
    archive, opf_path, opf = package(epub)

    base = opf_path.rsplit("/", 1)[0] + "/"
    items = {item.get("id"): item for item in opf.findall("opf:manifest/opf:item", NS)}
    hrefs = {base + str(item.get("href")): item for item in items.values()}
    packaged = set(archive.namelist()) - {"mimetype", "META-INF/container.xml", opf_path}
    assert set(hrefs) == packaged
    for path, item in hrefs.items():
        assert item.get("media-type") == MEDIA_TYPES[Path(path).suffix], path

    [nav] = [i for i in items.values() if "nav" in str(i.get("properties", "")).split()]
    spine = opf.findall("opf:spine/opf:itemref", NS)
    assert spine[0].get("idref") == nav.get("id")
    assert spine[0].get("linear") == "no"
    chapters = spine[1:]
    assert chapters, "the spine holds no chapter"
    for itemref in chapters:
        assert items[itemref.get("idref")].get("media-type") == "application/xhtml+xml"
        assert itemref.get("linear") in (None, "yes")
    ncx = opf.find("opf:spine", NS)
    assert ncx is not None
    assert items[ncx.get("toc")].get("media-type") == "application/x-dtbncx+xml"


@pytest.mark.ac("EPUB-AC1")
@pytest.mark.parametrize("source", [NOVEL, PUBLIC_DOMAIN_SAMPLE], ids=["novel", "sample"])
def test_epubcheck_reports_zero_errors(
    source: Path, tmp_path: Path, epubcheck: Callable[[Path], None]
) -> None:
    epubcheck(convert(source, tmp_path))
