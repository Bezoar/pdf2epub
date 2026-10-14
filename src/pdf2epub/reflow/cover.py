"""The book's cover (RFL-R28): a render of page 1 by default, a given image file, or none.

A cover file is checked before the batch starts: one that can't be read or decoded is a
usage error. Either way the cover goes through the same downscaling and re-encoding as
every other image in the book (RFL-R27), and its declared size is held to the pixel
limit (RFL-R6) before it is decoded.
"""

from pathlib import Path
from typing import Literal

from PIL import Image

from pdf2epub.errors import UsageError
from pdf2epub.passwords import Secret
from pdf2epub.reflow.limits import ResourceLimitExceeded, check_image
from pdf2epub.reflow.model import ImageAsset
from pdf2epub.reflow.render import encode, render_pages

Cover = Literal["page1"] | Path | None


def check_cover(cover: Cover) -> None:
    """Raise ``UsageError`` when ``cover`` names an image file that can't be read or
    decoded."""
    if cover is not None and cover != "page1":
        load_cover(Path(cover))


def book_cover(cover: Cover, source: Path, password: Secret | None = None) -> ImageAsset | None:
    """The cover for the book converted from ``source`` (opened with ``password`` if it
    needs one), or None for no cover."""
    if cover is None:
        return None
    if cover == "page1":
        [(_, asset)] = render_pages(source, [1], password)
        return asset
    return load_cover(Path(cover))


def load_cover(path: Path) -> ImageAsset:
    """The image file at ``path``, encoded for the book. Raises ``UsageError`` when it
    can't be read or decoded."""
    try:
        with Image.open(path) as picture:
            check_image(*picture.size)
            picture.load()
            return encode(picture)
    except ResourceLimitExceeded as error:
        raise UsageError(f"the cover image {path} is too large: {error}") from error
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        reason = getattr(error, "strerror", None) or error
        raise UsageError(f"the cover image {path} can't be read or decoded: {reason}") from error
