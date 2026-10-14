"""Resource limits on decoded content from an untrusted PDF (RFL-R6).

The limits are internal constants. An image is checked by the dimensions it declares,
before anything decodes it. A stream is decoded stage by stage, each stage stopping as
soon as its output passes the limit, so a decompression bomb is caught before more
than the limit is ever held in memory.
"""

import zlib
from collections.abc import Iterable

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


def check_stream_size(size: int) -> None:
    """Raise if a content stream of ``size`` bytes is above ``MAX_STREAM_BYTES``."""
    if size > MAX_STREAM_BYTES:
        raise ResourceLimitExceeded(
            f"decompressed stream size limit of {MAX_STREAM_BYTES:,} bytes",
            "A content stream",
        )


def inflate(data: bytes) -> bytes:
    """``data`` inflated in bounded chunks, raising as soon as the output passes
    ``MAX_STREAM_BYTES``. Like the parser, it keeps what it got before any damage."""
    decoder = zlib.decompressobj()
    out = bytearray()
    try:
        while data:
            chunk = decoder.decompress(data, _CHUNK)
            data = decoder.unconsumed_tail
            if not chunk:  # all input consumed: nothing more to come
                break
            out += chunk
            check_stream_size(len(out))
    except zlib.error:
        pass
    return bytes(out)


def join_bounded(chunks: Iterable[bytes]) -> bytes:
    """The chunks a streaming decoder yields, joined, raising as soon as they pass
    ``MAX_STREAM_BYTES``."""
    out = bytearray()
    for chunk in chunks:
        out += chunk
        check_stream_size(len(out))
    return bytes(out)


def run_length_size(data: bytes) -> int:
    """How many bytes ``/RunLengthDecode`` makes of ``data``, without decoding it."""
    size, index = 0, 0
    while index < len(data):
        length = data[index]
        if length == 128:  # end of data
            break
        if length < 128:  # copy the next length + 1 bytes
            size += min(length + 1, len(data) - index - 1)
            index += length + 2
        else:  # repeat the next byte 257 - length times
            size += 257 - length
            index += 2
    return size
