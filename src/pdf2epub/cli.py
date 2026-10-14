"""The ``pdf2epub`` command: the first front end (the cli spec).

It parses argv, builds the core inputs, calls ``plan_batch`` and ``run_batch``, and
renders the events through a sink. It holds no batch, password or conversion rules of its
own, and passes an option only when the user set it, so core defaults apply (CLI-R4).

stdout stays empty unless ``--json`` is given, when it carries only the events, one JSON
object per line; the human report, warnings and logging go to stderr (CLI-R2).
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from pdf2epub.batch import InputSpec, plan_batch, run_batch
from pdf2epub.events import Event, encode_event
from pdf2epub.options import BatchOptions, ConversionOptions, DiscoveryOptions
from pdf2epub.version import TOOL_VERSION

README = "https://github.com/Bezoar/pdf2epub#readme"
LEGAL_STATEMENT = (
    "Opens password-protected PDFs only with a password you supply. "
    "Honours permission restrictions. Does not remove DRM."
)
DESCRIPTION = f"""\
Convert PDF books, born-digital or scanned, into reflowable EPUB 3 books.

Each EPUB is written next to its PDF, with the same name and the extension .epub.

{LEGAL_STATEMENT}"""
EPILOG = """\
Legal scope: https://github.com/Bezoar/pdf2epub#legal-scope
Installing Tesseract (for scanned PDFs): https://github.com/Bezoar/pdf2epub#installing-tesseract"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf2epub",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("inputs", nargs="+", metavar="INPUT", help="a PDF file to convert")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=argparse.SUPPRESS,
        help="replace EPUBs that already exist",
    )
    reporting = parser.add_argument_group("reporting and machine output")
    reporting.add_argument(
        "--report",
        metavar="FILE",
        help="also write the final batch report to FILE as one JSON document",
    )
    reporting.add_argument(
        "--json", action="store_true", help="write JSON Lines events to stdout, not the report"
    )
    reporting.add_argument(
        "-v", "--verbose", action="store_true", help="log at INFO level (to stderr)"
    )
    reporting.add_argument("--debug", action="store_true", help="log at DEBUG level (to stderr)")
    parser.add_argument("--version", action="version", version=f"pdf2epub {TOOL_VERSION}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose, args.debug)

    batch_fields: dict[str, Any] = {}
    if "overwrite" in args:
        batch_fields["overwrite"] = args.overwrite

    plan = plan_batch([InputSpec(path) for path in args.inputs], DiscoveryOptions())
    final = FinalEvent()
    if args.json:
        writer = JsonLinesWriter(sys.stdout.buffer)
        report = run_batch(
            plan, BatchOptions(**batch_fields), ConversionOptions(), Tee(writer, final)
        )
    else:
        reporter = HumanReport(sys.stderr, single=plan.single)
        report = run_batch(
            plan, BatchOptions(**batch_fields), ConversionOptions(), Tee(reporter, final)
        )
        reporter.render()
    if args.report is not None and final.event is not None:
        write_report(final.event, Path(args.report))
    return report.exit_code


def configure_logging(verbose: bool, debug: bool) -> None:
    """Send logging to stderr only: pdf2epub's own records at WARNING, INFO with ``-v``,
    DEBUG with ``--debug`` (CLI-R8); other libraries' records at WARNING."""
    logging.basicConfig(
        level=logging.WARNING, stream=sys.stderr, format="%(levelname)s: %(message)s"
    )
    level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    logging.getLogger("pdf2epub").setLevel(level)


class Tee:
    """An event sink that passes each event to several sinks, in order."""

    def __init__(self, *sinks: Any) -> None:
        self._sinks = sinks

    def __call__(self, event: Event) -> None:
        for sink in self._sinks:
            sink(event)


class FinalEvent:
    """An event sink that keeps the ``batch_finished`` event."""

    def __init__(self) -> None:
        self.event: Event | None = None

    def __call__(self, event: Event) -> None:
        if event["type"] == "batch_finished":
            self.event = event


class JsonLinesWriter:
    """An event sink that writes each event to ``stream`` as one line of UTF-8 JSON and
    flushes it at once (CLI-R11, API-R20)."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream

    def __call__(self, event: Event) -> None:
        self._stream.write(encode_event(event).encode("utf-8"))
        self._stream.flush()


def write_report(event: Event, path: Path) -> None:
    """Write the ``batch_finished`` event to ``path``, byte for byte as its ``--json`` line
    (API-R19). A failure is logged as an error and changes nothing else (CLI-R18)."""
    try:
        path.write_bytes(encode_event(event).encode("utf-8"))
    except OSError as error:
        logging.getLogger(__name__).error(
            "could not write the report to %s: %s", path, error.strerror or error
        )


class HumanReport:
    """An event sink that prints the human report to stderr when the batch finishes:
    one result line for a single conversion (CLI-R16); for a batch, the totals, the
    failures and the condensed warnings (CLI-R15)."""

    def __init__(self, stream: TextIO, single: bool) -> None:
        self._stream = stream
        self._single = single
        self._finished: Event | None = None

    def __call__(self, event: Event) -> None:
        if event["type"] == "batch_finished":
            self._finished = event

    def render(self) -> None:
        if self._finished is None:
            return
        conversions: list[dict[str, Any]] = self._finished["conversions"]
        lines: list[str] = []
        if self._single:
            for conversion in conversions:
                lines.append(_result_line(conversion))
                lines.extend(_issue_lines(conversion))
        else:
            totals = self._finished["totals"]
            header = (
                f"Converted: {totals['converted']}  Skipped: {totals['skipped']}  "
                f"Failed: {totals['failed']}"
            )
            lines.append(header + ("  (interrupted)" if self._finished["interrupted"] else ""))
            for conversion in conversions:
                if conversion["outcome"] == "failed":
                    lines.append(f"✗ {conversion['source']}")
                    lines.extend(_issue_lines(conversion))
            for conversion in conversions:
                warning = _warnings_line(conversion)
                if conversion["outcome"] == "converted" and warning:
                    lines.append(warning)
        for line in lines:
            print(line, file=self._stream)


def _result_line(conversion: dict[str, Any]) -> str:
    source = conversion["source"]
    if conversion["outcome"] == "converted":
        return (
            f"✓ {source} → {conversion['output']} "
            f"({conversion['pages']} pages, {conversion['duration']:.1f}s)"
        )
    if conversion["outcome"] == "skipped":
        codes = ", ".join(issue["code"] for issue in conversion["issues"])
        return f"- {source}: skipped ({codes})"
    return f"✗ {source}: failed"


def _issue_lines(conversion: dict[str, Any]) -> list[str]:
    lines = []
    for issue in conversion["issues"]:
        line = f"  {issue['code']} [{issue['severity']}]: {issue['message']}"
        if issue["pages"]:
            line += f" (pages {page_ranges(issue['pages'])})"
        if issue["hint"]:
            line += f" — {issue['hint']}"
        lines.append(line)
    return lines


def _warnings_line(conversion: dict[str, Any]) -> str | None:
    """The condensed warnings of one conversion, e.g.
    ``! book.pdf: page_fallback(complex) pages 3, 7–9; language_defaulted``."""  # noqa: RUF002
    parts = []
    for issue in conversion["issues"]:
        if issue["severity"] != "warning":
            continue
        part = issue["code"] + (f"({issue['reason']})" if issue["reason"] else "")
        if issue["pages"]:
            part += f" pages {page_ranges(issue['pages'])}"
        parts.append(part)
    return f"! {conversion['source']}: {'; '.join(parts)}" if parts else None


def page_ranges(pages: list[int]) -> str:
    """Ascending pages as ranges, e.g. ``3, 7–9, 12`` (CLI-R17), with an en dash."""  # noqa: RUF002
    parts: list[str] = []
    ordered = sorted(set(pages))
    start = previous = ordered[0]
    for page in [*ordered[1:], None]:
        if page is not None and page == previous + 1:
            previous = page
            continue
        parts.append(str(start) if start == previous else f"{start}\u2013{previous}")
        if page is not None:
            start = previous = page
    return ", ".join(parts)
