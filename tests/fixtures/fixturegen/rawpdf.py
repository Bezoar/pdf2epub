"""A minimal PDF writer and a hand-rolled deflate encoder, for fixtures that ReportLab
can't or won't write: zero pages, actions and external references, decompression bombs.

Everything here is pure Python with no dependence on the zlib build, so the output is
byte-for-byte the same on every platform (TST-R1). The deflate encoder only emits fixed
Huffman codes and only knows two shapes of input: a run of one repeated byte, and a
periodic sequence (a head, a repeated unit, a tail). That is all a bomb needs.
"""

import zlib
from collections.abc import Sequence
from dataclasses import dataclass

# --- PDF objects ------------------------------------------------------------------------


def stream(entries: bytes, data: bytes) -> bytes:
    """A stream object body: ``entries`` go inside the dictionary, before ``/Length``."""
    return b"<< " + entries + b" /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"


def document(
    objects: Sequence[bytes], root: int = 1, header: bytes = b"%PDF-1.7", info: int | None = None
) -> bytes:
    """A complete PDF whose object ``n`` (1-based) is ``objects[n - 1]``, with a classic
    cross-reference table and trailer (naming object ``info`` as the Info dictionary, if
    given)."""
    out = bytearray(header + b"\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    info_entry = b" /Info %d 0 R" % info if info is not None else b""
    out += b"trailer\n<< /Size %d /Root %d 0 R%s >>\n" % (len(objects) + 1, root, info_entry)
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


# --- Deflate (RFC 1951) with fixed Huffman codes, wrapped in zlib (RFC 1950) ------------

_MAX_MATCH = 258
# Distance codes 0-29: (base distance, extra bits).
_DISTANCES = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), (7, 1), (9, 2), (13, 2), (17, 3), (25, 3),
    (33, 4), (49, 4), (65, 5), (97, 5), (129, 6), (193, 6), (257, 7), (385, 7),
    (513, 8), (769, 8), (1025, 9), (1537, 9), (2049, 10), (3073, 10), (4097, 11),
    (6145, 11), (8193, 12), (12289, 12), (16385, 13), (24577, 13),
]  # fmt: skip


class _Bits:
    """An LSB-first bit writer, as deflate packs its stream."""

    def __init__(self) -> None:
        self.out = bytearray()
        self._value = 0
        self._count = 0

    def put(self, value: int, count: int) -> None:
        self._value |= value << self._count
        self._count += count
        while self._count >= 8:
            self.out.append(self._value & 0xFF)
            self._value >>= 8
            self._count -= 8

    def code(self, code: int, length: int) -> None:
        """A Huffman code, which deflate stores most significant bit first."""
        self.put(int(f"{code:0{length}b}"[::-1], 2), length)

    def literal(self, value: int) -> None:
        if value < 144:
            self.code(0x30 + value, 8)
        elif value < 256:
            self.code(0x190 + value - 144, 9)
        else:  # 256 (end of block) to 279
            self.code(value - 256, 7)

    def match(self, distance: int) -> None:
        """A copy of 258 bytes (length code 285) from ``distance`` bytes back."""
        self.code(0xC0 + 285 - 280, 8)
        code = max(i for i, (base, _) in enumerate(_DISTANCES) if base <= distance)
        base, extra = _DISTANCES[code]
        self.code(code, 5)
        if extra:
            self.put(distance - base, extra)

    def aligned(self) -> bytes:
        """The bytes written so far; only valid on a byte boundary."""
        assert self._count == 0, "not on a byte boundary"
        return bytes(self.out)

    def finish(self) -> bytes:
        if self._count:
            self.out.append(self._value & 0xFF)
            self._value = self._count = 0
        return bytes(self.out)


@dataclass(frozen=True)
class Periodic:
    """``head + unit * count + tail``, kept compact."""

    head: bytes
    unit: bytes
    count: int
    tail: bytes

    def __len__(self) -> int:
        return len(self.head) + len(self.unit) * self.count + len(self.tail)

    def adler32(self) -> int:
        checksum = zlib.adler32(self.head)
        for _ in range(self.count):
            checksum = zlib.adler32(self.unit, checksum)
        return zlib.adler32(self.tail, checksum)

    def materialise(self) -> bytes:
        return self.head + self.unit * self.count + self.tail


def _adler32_of_run(value: int, length: int) -> int:
    """Adler-32 of ``length`` copies of byte ``value``, without building them."""
    a = (1 + length * value) % 65521
    b = (length + value * length * (length + 1) // 2) % 65521
    return (b << 16) | a


def zlib_run(value: int, length: int) -> Periodic:
    """A zlib stream that inflates to ``length`` copies of byte ``value``, as a
    ``Periodic`` (it is mostly one 13-byte unit repeated)."""
    matches, rest = divmod(length - 1, _MAX_MATCH)
    assert matches >= 9, "too short to be worth it"
    # Header bits (3) + one literal (8) + one match (13) = 24 bits: byte-aligned. Then
    # every 8 matches (104 bits) is one aligned 13-byte unit.
    head = _Bits()
    head.put(1, 1)  # BFINAL
    head.put(1, 2)  # BTYPE = fixed Huffman
    head.literal(value)
    head.match(1)
    unit = _Bits()
    for _ in range(8):
        unit.match(1)
    count, leftover = divmod(matches - 1, 8)
    tail = _Bits()
    for _ in range(leftover):
        tail.match(1)
    for _ in range(rest):
        tail.literal(value)
    tail.literal(256)
    trailer = tail.finish() + _adler32_of_run(value, length).to_bytes(4, "big")
    return Periodic(b"\x78\x01" + head.aligned(), unit.aligned(), count, trailer)


def zlib_periodic(data: Periodic) -> bytes:
    """A zlib stream that inflates to ``data``: literals for the irregular parts, and
    258-byte back-references for the repeated unit."""
    bits = _Bits()
    bits.put(1, 1)
    bits.put(1, 2)
    for byte in data.head + data.unit:
        bits.literal(byte)
    period = len(data.unit)
    repeated = period * (data.count - 1)
    matches, rest = divmod(repeated, _MAX_MATCH)
    for _ in range(matches):
        bits.match(period)
    for index in range(rest):
        bits.literal(data.unit[(matches * _MAX_MATCH + index) % period])
    for byte in data.tail:
        bits.literal(byte)
    bits.literal(256)
    return b"\x78\x01" + bits.finish() + data.adler32().to_bytes(4, "big")


def double_deflated_run(value: int, length: int) -> bytes:
    """``length`` copies of byte ``value``, deflated twice: the data of a stream with
    ``/Filter [/FlateDecode /FlateDecode]``. Gigabytes fit in a few tens of kilobytes."""
    return zlib_periodic(zlib_run(value, length))
