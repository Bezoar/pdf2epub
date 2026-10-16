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
from test_structure import Epub, open_epub, text_of
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
    package = epub.xml("content.opf")
    hrefs = {i.get("id"): str(i.get("href")) for i in manifest(epub)}
    itemref = package.find("opf:spine/opf:itemref", OPF_NS)
    assert itemref is not None
    first = hrefs[itemref.get("idref")]
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


def keyed_cover(folder: Path) -> Path:
    """A 40 x 20 cover: its left half near-white, its right half black, and black is its
    transparent colour key."""
    given = folder / "cover.png"
    keyed = Image.new("RGB", (40, 20), (0, 0, 0))
    keyed.paste((250, 250, 250), (0, 0, 20, 20))
    keyed.save(given, transparency=(0, 0, 0))
    return given


@pytest.mark.ac("RFL-AC33")
def test_a_cover_with_a_transparent_colour_key_stays_transparent_on_request(
    tmp_path: Path,
) -> None:
    # RFL-R27: transparency kept means an image PNG, with its transparency.
    options = ConversionOptions(cover=keyed_cover(tmp_path), image_background="transparent")
    _, path = convert(NOVEL, tmp_path, options)
    epub = open_epub(path)

    [item] = cover_items(epub)
    assert item.get("media-type") == "image/png"
    with picture(epub, str(item.get("href"))) as image:
        alpha = image.convert("RGBA").getchannel("A")
        assert (alpha.getpixel((0, 0)), alpha.getpixel((39, 0))) == (255, 0)


@pytest.mark.ac("RFL-AC33")
def test_a_cover_with_a_transparent_colour_key_is_put_on_white_by_default(
    tmp_path: Path,
) -> None:
    _, path = convert(NOVEL, tmp_path, ConversionOptions(cover=keyed_cover(tmp_path)))
    epub = open_epub(path)

    [item] = cover_items(epub)
    with picture(epub, str(item.get("href"))) as image:
        assert image.mode in ("1", "L", "RGB")  # nothing see-through is stored
        rgb = image.convert("RGB")
    assert rgb.getpixel((0, 0)) == (250, 250, 250)
    assert rgb.getpixel((39, 0)) == (255, 255, 255)  # the transparent half, on white


MASKED_LAYERS = FIXTURES / "images" / "masked-layers.pdf"
CROPPED = FIXTURES / "images" / "cropped.pdf"
# The fixtures' documented content (tests/fixtures/fixturegen/imagelayers.py).
BACKGROUND, SMEAR = (236, 226, 196), (200, 30, 30)
CAPTION = "Figure 1. A picture on a trimmed page."
ALPHA = FIXTURES / "images" / "alpha.pdf"
GRID = (20, 60, 160)
WHITE = (255, 255, 255)


def body_items(epub: Epub) -> list[etree._Element]:
    """The paragraphs and figures of the book, in reading order."""
    return [
        element
        for name in epub.spine
        for element in epub.xml(name).iter(f"{XHTML}p", f"{XHTML}figure")
        if (parent := element.getparent()) is None or parent.tag != f"{XHTML}figure"
    ]


def near(colour: tuple[int, ...], expected: tuple[int, int, int], tolerance: int = 12) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(colour[:3], expected, strict=True))


@pytest.mark.ac("RFL-AC31")
def test_a_masked_layer_is_taken_as_the_page_shows_it(tmp_path: Path) -> None:
    _, path = convert(MASKED_LAYERS, tmp_path, ConversionOptions(cover=None))
    epub = open_epub(path)

    sources = [
        str(img.get("src")) for name in epub.spine for img in epub.xml(name).iter(f"{XHTML}img")
    ]
    # Background and masked foreground are one picture, as on the page.
    assert len(sources) == 1
    with picture(epub, sources[0]) as image:
        rgb = image.convert("RGB")
    width, height = rgb.size
    assert width / height == pytest.approx(216 / 144, rel=0.02)

    def at(x: float, y: float) -> tuple[int, ...]:
        """The colour at a point given in the 120 x 80 layers' pixels."""
        pixel = rgb.getpixel((int(x * width / 120), int(y * height / 80)))
        assert isinstance(pixel, tuple)
        return pixel

    # The H's stems and bar show the red; everywhere else is the pale background, not
    # the red the foreground's own pixels hold.
    assert near(at(30, 40), SMEAR) and near(at(90, 20), SMEAR) and near(at(60, 40), SMEAR)
    assert near(at(5, 5), BACKGROUND) and near(at(60, 20), BACKGROUND)
    assert near(at(110, 75), BACKGROUND) and near(at(60, 60), BACKGROUND)


@pytest.mark.ac("RFL-AC32")
def test_images_on_a_cropped_page_keep_their_place_and_caption(tmp_path: Path) -> None:
    _, path = convert(CROPPED, tmp_path, ConversionOptions(cover=None))
    epub = open_epub(path)

    items = body_items(epub)
    kinds = [etree.QName(item).localname for item in items]
    assert kinds == ["p", "figure", "p", "figure"]
    opening, figure, closing, clipped = items
    assert text_of(opening).startswith("The opening paragraph")
    assert text_of(closing).startswith("The closing paragraph")
    figcaption = figure.find(f"{XHTML}figcaption")
    assert figcaption is not None and text_of(figcaption) == CAPTION
    assert clipped.find(f"{XHTML}figcaption") is None

    # The sliver in the trimmed margin and the picture 3% inside are left out; the
    # picture cut by the bottom edge keeps only its visible 75 of 120 pt.
    sizes = []
    for item in (figure, clipped):
        img = item.find(f"{XHTML}img")
        assert img is not None
        with picture(epub, str(img.get("src"))) as image:
            sizes.append(image.size)
    (width, height), (cut_width, cut_height) = sizes
    assert width / height == pytest.approx(300 / 180, rel=0.02)
    assert cut_width / cut_height == pytest.approx(300 / 75, rel=0.03)


def alpha_pictures(epub: Epub) -> tuple[bytes, Image.Image]:
    """The alpha fixture's two pictures, in reading order: the grid's stored bytes and the
    masked red H as stored."""
    sources = [
        str(img.get("src")) for name in epub.spine for img in epub.xml(name).iter(f"{XHTML}img")
    ]
    assert len(sources) == 2
    grid, letter = sources
    image = picture(epub, letter)
    image.load()
    return epub.archive.read(f"OEBPS/{grid}"), image


def letter_at(image: Image.Image, x: float, y: float) -> tuple[int, ...]:
    """The RGBA colour at a point given in the fixture's 120 x 80 picture pixels."""
    pixel = image.convert("RGBA").getpixel((int(x * image.width / 120), int(y * image.height / 80)))
    assert isinstance(pixel, tuple)
    return pixel


@pytest.mark.ac("RFL-AC33")
@pytest.mark.parametrize(
    "options",
    [ConversionOptions(cover=None), ConversionOptions(cover=None, image_background="white")],
    ids=["default", "white"],
)
def test_an_image_with_an_alpha_mask_is_put_on_white(
    tmp_path: Path, options: ConversionOptions
) -> None:
    _, path = convert(ALPHA, tmp_path, options)
    _, letter = alpha_pictures(open_epub(path))

    assert letter.mode in ("1", "L", "RGB", "P")
    assert "transparency" not in letter.info
    # The H shows its red; the rest of the picture, see-through on the page, is white.
    assert near(letter_at(letter, 30, 40), SMEAR) and near(letter_at(letter, 60, 40), SMEAR)
    assert letter_at(letter, 5, 5)[:3] == WHITE and letter_at(letter, 60, 20)[:3] == WHITE
    assert letter_at(letter, 110, 75)[:3] == WHITE


@pytest.mark.ac("RFL-AC33")
def test_an_image_with_an_alpha_mask_keeps_it_on_request(tmp_path: Path) -> None:
    options = ConversionOptions(cover=None, image_background="transparent")
    _, path = convert(ALPHA, tmp_path, options)
    _, letter = alpha_pictures(open_epub(path))

    assert letter.format == "PNG"
    assert near(letter_at(letter, 30, 40), SMEAR) and letter_at(letter, 30, 40)[3] == 255
    assert letter_at(letter, 5, 5)[3] == 0 and letter_at(letter, 60, 20)[3] == 0
    assert letter_at(letter, 110, 75)[3] == 0


@pytest.mark.ac("RFL-AC33")
def test_an_opaque_image_is_the_same_under_either_background(tmp_path: Path) -> None:
    stored = []
    for background in ("white", "transparent"):
        folder = tmp_path / background
        folder.mkdir()
        options = ConversionOptions(cover=None, image_background=background)
        _, path = convert(ALPHA, folder, options)
        grid, _ = alpha_pictures(open_epub(path))
        stored.append(grid)

    white, transparent = stored
    assert white == transparent
    with Image.open(io.BytesIO(white)) as grid_image:
        colours = {colour for _, colour in grid_image.convert("RGB").getcolors() or []}
    assert colours == {GRID, WHITE}  # the grid as drawn, untouched
