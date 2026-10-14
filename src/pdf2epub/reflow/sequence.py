"""Page sequence gaps (RFL-R29, RFL-R30): breaks in the printed page numbers that
furniture removal found.

Only arabic numbers are checked. A run of them is followed page by page: between two
numbered pages with ``k`` unnumbered pages in between (chapter openers, plates, blank
pages), the number may go up by 1 to ``k + 1``. A number that goes up by more is a gap
(pages missing); the same number again is a repeat. A roman number, or a number that goes
down, starts a new run without a break: front matter and restarted numbering are not
gaps. Each break splits a run into in-sequence stretches. A break is reported only when
the stretches on both sides of it hold at least 5 numbered pages; breaks with only shorter
stretches between them (a page scanned three times) count as one group, reported when
long stretches surround the group. A stray or misread number never causes one.
"""

from dataclasses import dataclass

from pdf2epub.issues import Issue, IssueCode

# A break is clear only between two stretches of at least this many numbered pages.
MIN_RUN = 5

_HINT = "Check the source for a page that was not scanned, or was scanned twice."


@dataclass(frozen=True)
class _Break:
    before: int
    """PDF page of the last number before the break."""
    after: int
    """PDF page of the first number after it."""
    description: str


def sequence_gaps(page_numbers: dict[int, str]) -> Issue | None:
    """The ``page_sequence_gap`` issue for these printed page numbers (by 1-based PDF
    page), or None when the sequence has no clear break."""
    breaks: list[_Break] = []
    stretch: list[tuple[int, int]] = []  # (PDF page, number) in sequence
    pending: list[_Break] = []  # adjacent breaks, waiting for the stretch after them
    before = 0  # length of the stretch before the first pending break

    def settle() -> None:
        """Report the pending breaks if long stretches surround them, then drop them."""
        if pending and before >= MIN_RUN and len(stretch) >= MIN_RUN:
            breaks.extend(pending)
        pending.clear()

    def split(new_break: _Break | None) -> None:
        """End the current stretch at a break, or at a reset (``None``)."""
        nonlocal stretch, before
        if new_break is not None and pending and len(stretch) < MIN_RUN:
            # Too short to settle anything: this break joins the pending ones, as in
            # 8, 9, 9, 9, 10 (the same page scanned three times).
            pending.append(new_break)
        else:
            settle()
            if new_break is not None:
                pending.append(new_break)
                before = len(stretch)
        stretch = []

    for page in sorted(page_numbers):
        text = page_numbers[page]
        if not text.isdigit():
            split(None)  # roman: front matter, or the switch to arabic
            continue
        number = int(text)
        if stretch:
            last_page, last = stretch[-1]
            unnumbered = page - last_page - 1
            if number == last:
                split(_Break(last_page, page, f"printed page {last} is repeated"))
            elif number > last + 1 + unnumbered:
                missing = _numbers(last + 1, number - 1)
                verb = "is" if number - last == 2 else "are"
                state = " missing or unnumbered" if unnumbered else " missing"
                split(_Break(last_page, page, f"printed {missing} {verb}{state}"))
            elif number <= last:
                split(None)  # numbering restarts
        stretch.append((page, number))
    settle()

    if not breaks:
        return None
    details = "; ".join(
        f"{b.description} (between PDF pages {b.before} and {b.after})" for b in breaks
    )
    pages = sorted({page for b in breaks for page in (b.before, b.after)})
    return Issue(
        IssueCode.PAGE_SEQUENCE_GAP,
        f"The printed page numbers break: {details}.",
        pages=pages,
        hint=_HINT,
    )


def _numbers(first: int, last: int) -> str:
    return f"page {first}" if first == last else f"pages {first}\N{EN DASH}{last}"
