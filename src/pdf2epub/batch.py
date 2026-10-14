"""The batch entry points (API §2): ``plan_batch`` turns inputs into planned conversions,
and ``run_batch`` runs them, emitting events to a sink and returning the batch report.

Planning expands folders, checks every file by content, drops duplicates and keeps input
order (BAT-R1 to BAT-R6); each file maps to ``<stem>.epub`` beside it or under
``DiscoveryOptions.output`` (BAT-R9, BAT-R10). A conversion whose fate is settled at
planning time (``not_found``, ``not_a_pdf``) is reported right after ``batch_started``
and never runs (API-R18).
"""

import os
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from pdf2epub.access import is_drm_wrapper, needs_password
from pdf2epub.cancel import CancelToken
from pdf2epub.conversion import PlannedConversion, convert
from pdf2epub.errors import UsageError
from pdf2epub.events import Emitter, EventSink
from pdf2epub.isolation import run_in_worker
from pdf2epub.issues import Issue, IssueCode, Outcome, Severity, derive_outcome
from pdf2epub.options import BatchOptions, ConversionOptions, DiscoveryOptions
from pdf2epub.passwords import Candidate, PasswordProvider, distinct
from pdf2epub.reflow.cover import check_cover
from pdf2epub.results import BatchReport, ConversionResult, Totals
from pdf2epub.version import TOOL_VERSION

EXIT_OK, EXIT_FAILED, EXIT_INTERRUPTED = 0, 1, 130


@dataclass(frozen=True)
class InputSpec:
    """One raw input: a path named on the command line, or a line of a files-from list."""

    path: str | os.PathLike[str]
    from_list: bool = False
    """True for a line of a files-from list (BAT-R2)."""


@dataclass(frozen=True)
class BatchPlan:
    conversions: list[PlannedConversion]
    single: bool
    """True when the run is a single conversion (BAT-R7): exactly one input, an explicitly
    named file."""


# BAT-R4: a file is a PDF only if these bytes occur within its first 1024 bytes.
PDF_MAGIC = b"%PDF-"
MAGIC_WINDOW = 1024


def read_files_from(source: str | os.PathLike[str], stdin: TextIO | None = None) -> list[InputSpec]:
    """Read a files-from list (BAT-R2) from the file ``source``, or from ``stdin`` (default
    ``sys.stdin``) when ``source`` is ``-``: one path per line, surrounding whitespace
    trimmed, blank lines and ``#`` comments skipped. Globs are not expanded.

    Raises ``UsageError`` when the list cannot be read (BAT-R25).
    """
    try:
        if os.fspath(source) == "-":
            text = (stdin or sys.stdin).read()
        else:
            text = Path(source).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        reason = getattr(error, "strerror", None) or error
        raise UsageError(
            f"cannot read the files-from list {os.fspath(source)}: {reason}"
        ) from error
    specs = []
    for line in text.splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            specs.append(InputSpec(entry, from_list=True))
    return specs


def plan_batch(inputs: Sequence[InputSpec], options: DiscoveryOptions) -> BatchPlan:
    """Plan the conversions for ``inputs`` without converting anything (API-R2).

    Raises ``UsageError`` for a batch whose ``output`` is an existing regular file
    (BAT-R25).
    """
    # A path named on its own is a file to convert, even one that turns out not to exist;
    # only a folder or a files-from list makes a one-input run a batch (BAT-R7).
    single = len(inputs) == 1 and not inputs[0].from_list and not Path(inputs[0].path).is_dir()
    if not single and options.output is not None and Path(options.output).is_file():
        raise UsageError(
            f"the output {os.fspath(options.output)} is an existing file; "
            "a batch needs an output folder"
        )

    conversions: list[PlannedConversion] = []
    seen: set[str] = set()
    claimed: set[str] = set()
    ignores_case: dict[Path, bool] = {}
    for source, folder in _discover(inputs, options.recursive):
        try:
            key = os.path.realpath(source)
        except ValueError:  # e.g. a NUL byte from a files-from list; reported not_found
            key = str(source)
        if key in seen:
            continue  # BAT-R5: planned once, at its first occurrence
        seen.add(key)
        issues = _content_issues(source, explicit=folder is None)
        destination: Path | None = None
        if not any(issue.code is IssueCode.NOT_FOUND for issue in issues):
            destination = _destination(source, folder, options, single)
        if destination is not None and not issues:
            issues = _destination_issues(destination, claimed, ignores_case)
        conversions.append(
            PlannedConversion(
                id=len(conversions),
                source=str(source),
                destination=None if destination is None else str(destination),
                issues=issues,
            )
        )
    return BatchPlan(conversions=conversions, single=single)


def _destination_issues(
    destination: Path, claimed: set[str], ignores_case: dict[Path, bool]
) -> list[Issue]:
    """``output_collision`` when an earlier conversion in the plan already maps to
    ``destination`` (BAT-R11), else ``output_exists`` when the EPUB is already there
    (BAT-R12); ``run_batch`` drops ``output_exists`` under ``overwrite``. Only conversions
    that would run claim their destination."""
    key = _identity(destination, ignores_case)
    if key in claimed:
        return [
            Issue(
                IssueCode.OUTPUT_COLLISION,
                f"An earlier conversion in this batch already writes {destination}.",
            )
        ]
    claimed.add(key)
    # Only an existing file is an earlier EPUB; anything else at the destination (a
    # folder, say) is left for the writer, which reports write_failed (BAT-R15).
    if destination.is_file():
        return [Issue(IssueCode.OUTPUT_EXISTS, f"{destination} already exists.")]
    return []


def _identity(destination: Path, ignores_case: dict[Path, bool]) -> str:
    """A key equal for two destinations exactly when they name the same file: the path
    with its folder's symbolic links resolved, case-folded when its file system ignores
    letter case (as macOS does by default). ``ignores_case`` caches the probe per folder
    for one plan."""
    folder = Path(os.path.realpath(destination.parent))
    if folder not in ignores_case:
        ignores_case[folder] = _ignores_case(folder)
    path = os.path.normcase(folder / destination.name)
    return path.casefold() if ignores_case[folder] else path


def _ignores_case(folder: Path) -> bool:
    """Whether the file system that ``folder`` is (or would be created) on ignores letter
    case, probed without writing anything: an entry of the nearest existing folder, or
    else that folder or one of its ancestors, is looked up with its name's case swapped.
    With nothing to probe, case counts."""
    while not folder.is_dir() and folder.parent != folder:
        folder = folder.parent
    try:
        with os.scandir(folder) as entries:
            inside = next((folder / e.name for e in entries if e.name != e.name.swapcase()), None)
    except OSError:
        inside = None
    candidates = [inside] if inside is not None else []
    candidates += [p for p in (folder, *folder.parents) if p.name != p.name.swapcase()]
    for path in candidates[:1]:
        try:
            original = os.lstat(path)
            swapped = os.lstat(path.with_name(path.name.swapcase()))
        except OSError:
            return False
        return (original.st_dev, original.st_ino) == (swapped.st_dev, swapped.st_ino)
    return False


def _discover(inputs: Sequence[InputSpec], recursive: bool) -> Iterator[tuple[Path, Path | None]]:
    """Every candidate file, absolute, in input order (BAT-R1, BAT-R3, BAT-R6), with the
    folder input it was found in (None for a file named explicitly)."""
    for spec in inputs:
        path = Path(os.path.abspath(spec.path))
        if path.is_dir():
            for found in sorted(_scan(path, recursive), key=lambda p: _natural_key(p, path)):
                yield found, path
        else:
            yield path, None


def _scan(folder: Path, recursive: bool) -> Iterator[Path]:
    """The ``*.pdf`` files (any case) in ``folder``, skipping hidden names and never
    following symbolic links to folders (BAT-R3)."""
    for root, folders, files in os.walk(folder, followlinks=False):
        folders[:] = [name for name in folders if recursive and not name.startswith(".")]
        for name in files:
            path = Path(root) / name
            if not name.startswith(".") and name.lower().endswith(".pdf") and path.is_file():
                yield path


def _natural_key(path: Path, folder: Path) -> list[tuple[int, int | str]]:
    """Natural sort order of ``path`` relative to ``folder`` (BAT-R6): case-insensitive,
    runs of digits compared as numbers."""
    relative = path.relative_to(folder).as_posix().casefold()
    return [
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", relative)
        if part
    ]


def _content_issues(source: Path, explicit: bool) -> list[Issue]:
    """The planning-time issues of one file: ``not_found`` when it can't be read,
    ``not_a_pdf`` when it fails the content check (BAT-R4). A DRM wrapper (PWD-R3) is
    never a PDF, whatever bytes it holds: an ``explicit`` one (named, or listed in a
    files-from list) passes, so that its conversion refuses it as ``drm_protected``; one
    found by a folder scan is ``not_a_pdf``."""
    try:
        with source.open("rb") as file:
            head = file.read(MAGIC_WINDOW)
    except ValueError:  # a path the OS cannot even name, e.g. one holding a NUL byte
        return [Issue(IssueCode.NOT_FOUND, f"Cannot read {str(source)!r}: not a valid path.")]
    except OSError as error:
        reason = error.strerror or str(error)
        return [Issue(IssueCode.NOT_FOUND, f"Cannot read {source}: {reason}.")]
    if is_drm_wrapper(source):
        return [] if explicit else [Issue(IssueCode.NOT_A_PDF, f"{source} is not a PDF file.")]
    if PDF_MAGIC not in head:
        return [Issue(IssueCode.NOT_A_PDF, f"{source} is not a PDF file.")]
    return []


def _destination(
    source: Path, folder: Path | None, options: DiscoveryOptions, single: bool
) -> Path:
    """Where ``source``'s EPUB goes (BAT-R9, BAT-R10): beside it by default; with
    ``output``, that file for a single conversion, else into that folder, under the
    source's path relative to the folder input it was found in, if any."""
    epub = source.with_suffix(".epub")
    if options.output is None:
        return epub
    output = Path(os.path.abspath(options.output))
    if single:
        return output
    return output / (epub.relative_to(folder) if folder is not None else epub.name)


class _Reporter:
    """Turns one conversion's progress and issues into events."""

    def __init__(self, emitter: Emitter, conversion_id: int) -> None:
        self._emitter = emitter
        self._id = conversion_id

    def progress(self, stage: str, done: int, of: int, **fields: Any) -> None:
        self._emitter.emit("progress", id=self._id, stage=stage, done=done, of=of, **fields)

    def issue(self, issue: Issue) -> None:
        self._emitter.emit("issue", id=self._id, issue=issue.to_dict())

    def temporary(self, path: Path) -> None:
        pass  # this process deletes its own temporary file

    def commit(self) -> bool:
        return True  # convert itself checks the cancel token first


def run_batch(
    plan: BatchPlan,
    batch_options: BatchOptions,
    conversion_options: ConversionOptions,
    sink: EventSink,
    cancel: CancelToken | None = None,
    passwords: PasswordProvider | None = None,
) -> BatchReport:
    """Run every planned conversion, synchronously, and return the batch report (API-R3).

    Events go to ``sink`` from the calling thread only (API-R4). With ``isolation =
    "subprocess"`` each conversion runs in its own worker subprocess, under the batch's
    time limit (BAT-R19 to BAT-R21); with ``"inprocess"``, in this process.

    Raises ``UsageError``, before any event, when ``conversion_options.cover`` names an
    image file that can't be read or decoded (RFL-R28).
    """
    # Preflight: a cover file that can't be used is a usage error, before any event
    # (RFL-R28, BAT-R25).
    check_cover(conversion_options.cover)
    candidates = _preflight(plan, batch_options, passwords)
    emitter = Emitter(sink)
    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    emitter.emit(
        "batch_started",
        tool_version=TOOL_VERSION,
        total=len(plan.conversions),
        jobs=1,
        planned=[
            {"id": p.id, "source": p.source, "destination": p.destination} for p in plan.conversions
        ],
    )

    # API-R18: conversions settled at planning time finish first, in plan order. Under
    # overwrite an existing EPUB settles nothing: it is replaced on success (BAT-R12).
    settled = {
        p.id: _unrun(p, issues)
        for p in plan.conversions
        if (issues := _planning_issues(p, batch_options.overwrite))
    }
    for result in settled.values():
        for issue in result.issues:
            emitter.emit("issue", id=result.id, issue=issue.to_dict())
        emitter.emit("conversion_finished", **result.to_dict())

    results: list[ConversionResult] = []
    for planned in plan.conversions:
        if planned.id in settled:
            results.append(settled[planned.id])
            continue
        if cancel is not None and cancel.cancelled:
            result = _not_attempted(planned)
        else:
            emitter.emit("conversion_started", id=planned.id)
            reporter = _Reporter(emitter, planned.id)
            found = candidates.get(planned.id, ())
            if batch_options.isolation == "subprocess":
                result = run_in_worker(
                    planned, conversion_options, reporter, cancel, batch_options.timeout, found
                )
            else:
                result = convert(planned, conversion_options, reporter, cancel, found)
        emitter.emit("conversion_finished", **result.to_dict())
        results.append(result)

    interrupted = cancel is not None and cancel.cancelled
    report = BatchReport(
        tool_version=TOOL_VERSION,
        started_at=started_at,
        conversions=results,
        totals=Totals(
            converted=sum(r.outcome is Outcome.CONVERTED for r in results),
            skipped=sum(r.outcome is Outcome.SKIPPED for r in results),
            failed=sum(r.outcome is Outcome.FAILED for r in results),
        ),
        interrupted=interrupted,
        exit_code=_exit_code(results, interrupted, batch_options.strict),
    )
    emitter.emit("batch_finished", **report.to_dict())
    return report


# PWD-R13: the most candidate passwords that may apply to one file, so pdf2epub never
# acts as a password guesser (MAIN-R7).
MAX_CANDIDATES = 25


def _preflight(
    plan: BatchPlan, batch_options: BatchOptions, passwords: PasswordProvider | None
) -> dict[int, list[Candidate]]:
    """The run's preflight (API-R29), before any event: the candidate passwords for each
    conversion that will run on a password-protected PDF, by conversion id."""
    candidates: dict[int, list[Candidate]] = {}
    if passwords is None:
        return candidates
    for planned in plan.conversions:
        if _planning_issues(planned, batch_options.overwrite):
            continue  # settled at planning time: never opened
        source = Path(planned.source)
        if needs_password(source):
            found = distinct(passwords.candidates(source))
            if len(found) > MAX_CANDIDATES:
                raise UsageError(
                    f"{source}: {len(found)} candidate passwords apply to this file, "
                    f"more than the cap of {MAX_CANDIDATES}"
                )
            candidates[planned.id] = found
    return candidates


def _not_attempted(planned: PlannedConversion) -> ConversionResult:
    issue = Issue(IssueCode.NOT_ATTEMPTED, "The batch was interrupted before this conversion.")
    return _unrun(planned, [issue])


def _planning_issues(planned: PlannedConversion, overwrite: bool) -> list[Issue]:
    """The planning issues that settle ``planned`` without running it."""
    return [
        issue
        for issue in planned.issues
        if not (overwrite and issue.code is IssueCode.OUTPUT_EXISTS)
    ]


def _unrun(planned: PlannedConversion, issues: list[Issue]) -> ConversionResult:
    return ConversionResult(
        id=planned.id,
        source=planned.source,
        destination=planned.destination,
        outcome=derive_outcome(issues),
        issues=issues,
        output=None,
        password_source=None,
        pages=None,
        duration=0.0,
        ocr=None,
    )


def _exit_code(results: list[ConversionResult], interrupted: bool, strict: bool) -> int:
    """BAT-R24: 130 if interrupted, else 1 for any failure (or, under ``strict``, any
    warning), else 0."""
    if interrupted:
        return EXIT_INTERRUPTED
    if any(r.outcome is Outcome.FAILED for r in results):
        return EXIT_FAILED
    if strict and any(i.severity is Severity.WARNING for r in results for i in r.issues):
        return EXIT_FAILED
    return EXIT_OK
