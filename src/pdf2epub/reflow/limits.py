"""Resource limits on decoded content from an untrusted PDF (RFL-R6).

The limits are internal constants. They are checked before anything is decoded: an
image by the dimensions it declares, a stream by inflating it in bounded chunks and
counting, so a decompression bomb is caught without ever being held in memory.
"""

import zlib

MAX_PIXELS = 100_000_000
"""The most pixels any single image or page render may decode to (100 megapixels: a
600 DPI A3 scan is about 70)."""

MAX_STREAM_BYTES = 256 * 1024 * 1024
"""The most bytes any single content stream may decompress to."""

_CHUNK = 1 << 20


class ResourceLimitExceeded(Exception):
    """A limit was hit. ``page`` is the 1-based page it was hit on, once known."""

    def __init__(self, limit: str, detail: str, page: int | None = None) -> None:
        self.limit = limit
        self.detail = detail
        self.page = page
        where = f"on page {page}" if page is not None else "in the file"
        super().__init__(f"{detail} {where} is above the {limit}; the file was not converted.")

    def on_page(self, page: int) -> "ResourceLimitExceeded":
        return ResourceLimitExceeded(self.limit, self.detail, page)


def check_image(width: int, height: int) -> None:
    """Raise unless an image of ``width`` x ``height`` is within ``MAX_PIXELS``."""
    if width * height > MAX_PIXELS:
        raise ResourceLimitExceeded(
            f"decoded pixel limit of {MAX_PIXELS:,} pixels",
            f"An image of {width:,} x {height:,} pixels",
        )


def check_inflated_size(data: bytes, layers: int) -> None:
    """Raise if ``data``, inflated ``layers`` times over (a ``/FlateDecode`` chain),
    comes to more than ``MAX_STREAM_BYTES``. Data that isn't valid zlib is left for the
    parser to deal with: it is only counted up to the point where it goes bad."""
    decoders = [zlib.decompressobj() for _ in range(layers)]
    total = 0

    def feed(level: int, data: bytes) -> None:
        nonlocal total
        decoder = decoders[level]
        while data:
            out = decoder.decompress(data, _CHUNK)
            data = decoder.unconsumed_tail
            if not out:  # all input consumed without output: nothing more to come yet
                return
            if level + 1 < layers:
                feed(level + 1, out)
                continue
            total += len(out)
            if total > MAX_STREAM_BYTES:
                raise ResourceLimitExceeded(
                    f"decompressed stream size limit of {MAX_STREAM_BYTES:,} bytes",
                    "A content stream",
                )

    try:
        feed(0, data)
    except zlib.error:
        return
