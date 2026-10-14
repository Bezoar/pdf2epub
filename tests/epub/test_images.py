"""Book images and the cover (RFL-R26-R28, EPUB-R12): read back from the written EPUB.

Expected sizes and formats come from the fixtures' documented content (a 4000 x 3000
many-coloured photograph on two pages, an 800 x 600 two-colour drawing) and from the
spec's limits (long edge 1600 px, JPEG for photographs, PNG for line art); the cover
render is compared with pdfium's own render of page 1.
"""

import io
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from conftest import FIXTURES, NOVEL
from lxml import etree
from PIL import Image, ImageChops, ImageStat
from test_structure import Epub, open_epub
from test_text import EPUB_TYPE, OPF_NS, XHTML, convert

from pdf2epub import ConversionOptions

PHOTO_AND_DRAWING = FIXTURES / "images" / "photo-and-drawing.pdf"


def manifest(epub: Epub) -> list[etree._Element]:
    return epub.xml("content.opf").findall("opf:manifest/opf:item", OPF_NS)


def picture(epub: Epub, href: str) -> Image.Image:
    return Image.open(io.BytesIO(epub.archive.read(f"OEBPS/{href}")))


def cover_items(epub: Epub) -> list[etree._Element]:
    return [i for i in manifest(epub) if "cover-image" in (i.get("properties") or "").split()]


@pytest.mark.ac("RFL-AC18")
def test_images_are_downscaled_re_encoded_and_stored_once(tmp_path: Path) -> None:
    _, path = convert(PHOTO_AND_DRAWING, tmp_path, ConversionOptions(cover=None))
    epub = open_epub(path)

    assets = [i for i in manifest(epub) if str(i.get("media-type")).startswith("image/")]
    assert len(assets) == 2
    sources = [
        str(img.get("src")) for name in epub.spine for img in epub.xml(name).iter(f"{XHTML}img")
    ]
    assert len(sources) == 3  # the photograph twice, then the drawing

    photo, drawing = (str(i.get("href")) for i in assets)
    if sources.count(photo) != 2:
        photo, drawing = drawing, photo
    assert sources == [photo, photo, drawing]

    photo_item, drawing_item = (
        next(i for i in assets if i.get("href") == h) for h in (photo, drawing)
    )
    assert photo_item.get("media-type") == "image/jpeg"
    with picture(epub, photo) as image:
        assert image.format == "JPEG"
        assert image.size == (1600, 1200)
    assert drawing_item.get("media-type") == "image/png"
    with picture(epub, drawing) as image:
        assert image.format == "PNG"
        assert image.size == (800, 600)  # below the limit: not scaled
        assert len(image.convert("L").getcolors() or []) == 2


def page_one_render(size: tuple[int, int]) -> Image.Image:
    document = pdfium.PdfDocument(NOVEL)
    try:
        page = document[0]
        scale = size[0] / page.get_width()
        render: Image.Image = page.render(scale=scale).to_pil()
        return render.convert("RGB").resize(size)
    finally:
        document.close()


@pytest.mark.ac("RFL-AC19")
@pytest.mark.ac("EPUB-AC8")
def test_the_default_cover_is_a_render_of_page_one(tmp_path: Path) -> None:
    _, path = convert(NOVEL, tmp_path)
    epub = open_epub(path)

    [item] = cover_items(epub)
    href = str(item.get("href"))
    with picture(epub, href) as image:
        cover = image.convert("RGB")
    assert max(cover.size) == 1600
    # The novel's pages are 6 x 9 in: the render keeps that shape and shows page 1.
    assert cover.size == (1067, 1600)
    difference = ImageStat.Stat(ImageChops.difference(cover, page_one_render(cover.size)))
    assert max(difference.mean) < 4

    # EPUB-R12: a cover page showing it comes first in the spine.
    first = epub.spine[0]
    images = list(epub.xml(first).iter(f"{XHTML}img"))
    assert [(img.get("src"), img.get("alt")) for img in images] == [(href, "Cover")]
    landmarks = epub.nav("landmarks")
    assert [a.get("href") for a in landmarks.iter(f"{XHTML}a") if a.get(EPUB_TYPE) == "cover"] == [
        first
    ]


@pytest.mark.ac("RFL-AC19")
@pytest.mark.ac("EPUB-AC8")
def test_no_cover_means_no_cover_image_and_no_cover_page(tmp_path: Path) -> None:
    _, path = convert(NOVEL, tmp_path, ConversionOptions(cover=None))
    epub = open_epub(path)

    assert cover_items(epub) == []
    assert [i for i in manifest(epub) if str(i.get("media-type")).startswith("image/")] == []
    assert not [img for name in epub.spine for img in epub.xml(name).iter(f"{XHTML}img")]


@pytest.mark.ac("RFL-AC19")
def test_a_cover_image_file_is_downscaled_and_used(tmp_path: Path) -> None:
    given = tmp_path / "cover.png"
    Image.new("RGB", (3200, 1000), (200, 30, 30)).save(given)
    _, path = convert(NOVEL, tmp_path, ConversionOptions(cover=given))
    epub = open_epub(path)

    [item] = cover_items(epub)
    with picture(epub, str(item.get("href"))) as image:
        assert image.size == (1600, 500)
        assert image.convert("RGB").getcolors() == [(1600 * 500, (200, 30, 30))]
