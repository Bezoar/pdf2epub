"""The ``pdf2epub`` command: the first front end (the cli spec).

It parses argv, builds the core inputs, calls ``plan_batch`` and ``run_batch``, and
renders the events through a sink. It holds no batch, password or conversion rules of its
own, and passes an option only when the user set it, so core defaults apply (CLI-R4).

stdout stays empty unless ``--json`` is given, when it carries only the events, one JSON
object per line; the human report, warnings and logging go to stderr (CLI-R2).
"""

import argparse
import logging
import os
import signal
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Any, BinaryIO, TextIO

from pdf2epub.batch import EXIT_INTERRUPTED, InputSpec, plan_batch, read_files_from, run_batch
from pdf2epub.cancel import CancelToken
from pdf2epub.errors import UsageError
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
    parser.add_argument(
        "inputs", nargs="*", metavar="INPUT", help="a PDF file, or a folder of PDF files"
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        default=argparse.SUPPRESS,
        help="scan folder inputs through all subfolders",
    )
    parser.add_argument(
        "--files-from",
        metavar="FILE",
        help="read more inputs from FILE (or stdin for -), one path per line",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        type=Path,
        default=argparse.SUPPRESS,
        help="the EPUB file (one input) or the output folder (a batch)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=argparse.SUPPRESS,
        help="replace EPUBs that already exist",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=argparse.SUPPRESS,
        help="exit with code 1 when any conversion has a warning (EPUBs are still written)",
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
        "-v",
        "--verbose",
        action="store_true",
        help="list each success in the report; log at INFO level",
    )
    reporting.add_argument("--debug", action="store_true", help="log at DEBUG level (to stderr)")
    reporting.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="report only the totals and the failures; no progress line",
    )
    parser.add_argument("--version", action="version", version=f"pdf2epub {TOOL_VERSION}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.quiet and (args.verbose or args.debug):
        parser.error("-q/--quiet cannot be combined with -v/--verbose or --debug")  # CLI-R7
    configure_logging(args.verbose, args.debug)

    batch_fields: dict[str, Any] = {
        name: getattr(args, name) for name in ("overwrite", "strict") if name in args
    }

    discovery_fields: dict[str, Any] = {
        name: getattr(args, name) for name in ("recursive", "output") if name in args
    }

    try:
        if not args.inputs and args.files_from is None:
            raise UsageError("no inputs: name a PDF file or folder, or use --files-from")
        inputs = [InputSpec(path) for path in args.inputs]
        if args.files_from is not None:
            inputs.extend(read_files_from(args.files_from))
        plan = plan_batch(inputs, DiscoveryOptions(**discovery_fields))
    except UsageError as error:
        parser.error(str(error))  # exits 2 with the reason on stderr (BAT-R25)
    final = FinalEvent()
    cancel = CancelToken()
    if args.json:
        writer = JsonLinesWriter(sys.stdout.buffer)
        with interrupts(cancel):
            report = run_batch(
                plan,
                BatchOptions(**batch_fields),
                ConversionOptions(),
                Tee(writer, final),
                cancel=cancel,
            )
    else:
        reporter = HumanReport(
            sys.stderr,
            single=plan.single,
            verbose=args.verbose,
            quiet=args.quiet,
            progress=not args.quiet and sys.stderr.isatty(),
        )
        handlers = logging.getLogger().handlers
        for handler in handlers:
            handler.addFilter(reporter.clear_progress)
        try:
            with interrupts(cancel):
                report = run_batch(
                    plan,
                    BatchOptions(**batch_fields),
                    ConversionOptions(),
                    Tee(reporter, final),
                    cancel=cancel,
                )
        finally:
            for handler in handlers:
                handler.removeFilter(reporter.clear_progress)
        reporter.render()
    if args.report is not None and final.event is not None:
        write_report(final.event, Path(args.report))
    return report.exit_code


@contextmanager
def interrupts(cancel: CancelToken) -> Iterator[None]:
    """While the batch runs, the first SIGINT or SIGTERM cancels it, so it ends with the
    report and exit code 130; a second one ends the process at once with 130 and no
    report (CLI-R19, BAT-R18)."""
    received = False

    def handle(signum: int, frame: FrameType | None) -> None:
        nonlocal received
        if received:
            os._exit(EXIT_INTERRUPTED)
        received = True
        cancel.cancel()

    previous = {signum: signal.signal(signum, handle) for signum in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


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


# CLI-R14: at most about 10 progress redraws a second.
REDRAW_INTERVAL = 0.1


class HumanReport:
    """An event sink that prints the human report to stderr when the batch finishes:
    one result line for a single conversion (CLI-R16); for a batch, the totals, the
    failures and the condensed warnings, plus, with ``verbose``, each success, or, with
    ``quiet``, only the totals and failures (CLI-R15).

    With ``progress`` (stderr is a terminal), it also redraws one progress line, such as
    ``[3/17] book.pdf · ocr 45/312``, at most every ``REDRAW_INTERVAL`` seconds (CLI-R14).
    """

    def __init__(
        self,
        stream: TextIO,
        single: bool,
        verbose: bool = False,
        quiet: bool = False,
        progress: bool = False,
    ) -> None:
        self._stream = stream
        self._single = single
        self._verbose = verbose
        self._quiet = quiet
        self._progress = progress
        self._finished: Event | None = None
        self._total = 0
        self._names: dict[int, str] = {}
        self._last_draw: float | None = None
        self._drawn = False

    def __call__(self, event: Event) -> None:
        if event["type"] == "batch_finished":
            self._finished = event
        elif self._progress and event["type"] == "batch_started":
            self._total = event["total"]
            self._names = {p["id"]: Path(p["source"]).name for p in event["planned"]}
        elif self._progress and event["type"] == "progress":
            self._draw(event)

    def _draw(self, event: Event) -> None:
        now = time.monotonic()
        if self._last_draw is not None and now - self._last_draw < REDRAW_INTERVAL:
            return
        self._last_draw = now
        line = (
            f"[{event['id'] + 1}/{self._total}] {self._names.get(event['id'], '')} · "
            f"{event['stage']} {event['done']}/{event['of']}"
        )
        self._stream.write(f"\r{line}\x1b[K")  # back to the line start; clear its rest
        self._stream.flush()
        self._drawn = True

    def clear_progress(self, record: logging.LogRecord | None = None) -> bool:
        """Clear the progress line, if one is drawn, so that what is written next starts
        on an empty line. As a logging filter, it runs before each log record is written
        and lets every record through."""
        if self._drawn:
            self._stream.write("\r\x1b[K")
            self._stream.flush()
            self._drawn = False
        return True

    def render(self) -> None:
        self.clear_progress()
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
                if conversion["outcome"] == "converted" and warning and not self._quiet:
                    lines.append(warning)
            if self._verbose:
                for conversion in conversions:
                    if conversion["outcome"] == "converted":
                        lines.append(f"✓ {conversion['source']} → {conversion['output']}")
                    elif conversion["outcome"] == "skipped":
                        codes = ", ".join(issue["code"] for issue in conversion["issues"])
                        lines.append(f"- {conversion['source']}: {codes}")
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
