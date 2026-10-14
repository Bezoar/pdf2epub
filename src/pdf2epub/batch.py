"""The batch entry points (API §2): ``plan_batch`` turns inputs into planned conversions,
and ``run_batch`` runs them, emitting events to a sink and returning the batch report.

So far a plan holds the explicitly named files, each mapped to ``<stem>.epub`` beside it
or under ``DiscoveryOptions.output`` (BAT-R9, BAT-R10). Folder discovery and the
planning-time issues (BAT-R1 to BAT-R6, BAT-R11, BAT-R12) arrive with input discovery.
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pdf2epub.cancel import CancelToken
from pdf2epub.conversion import PlannedConversion, convert
from pdf2epub.events import Emitter, EventSink
from pdf2epub.issues import Issue, IssueCode, Outcome, Severity
from pdf2epub.options import BatchOptions, ConversionOptions, DiscoveryOptions
from pdf2epub.passwords import PasswordProvider
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


def plan_batch(inputs: Sequence[InputSpec], options: DiscoveryOptions) -> BatchPlan:
    """Plan the conversions for ``inputs`` without converting anything (API-R2)."""
    single = len(inputs) == 1 and not inputs[0].from_list and Path(inputs[0].path).is_file()
    conversions: list[PlannedConversion] = []
    for index, spec in enumerate(inputs):
        source = Path(os.path.abspath(spec.path))
        conversions.append(
            PlannedConversion(
                id=index,
                source=str(source),
                destination=str(_destination(source, options, single)),
            )
        )
    return BatchPlan(conversions=conversions, single=single)


def _destination(source: Path, options: DiscoveryOptions, single: bool) -> Path:
    name = source.with_suffix(".epub").name
    if options.output is None:
        return source.with_name(name)
    output = Path(os.path.abspath(options.output))
    return output if single else output / name


class _Reporter:
    """Turns one conversion's progress and issues into events."""

    def __init__(self, emitter: Emitter, conversion_id: int) -> None:
        self._emitter = emitter
        self._id = conversion_id

    def progress(self, stage: str, done: int, of: int, **fields: Any) -> None:
        self._emitter.emit("progress", id=self._id, stage=stage, done=done, of=of, **fields)

    def issue(self, issue: Issue) -> None:
        self._emitter.emit("issue", id=self._id, issue=issue.to_dict())


def run_batch(
    plan: BatchPlan,
    batch_options: BatchOptions,
    conversion_options: ConversionOptions,
    sink: EventSink,
    cancel: CancelToken | None = None,
    passwords: PasswordProvider | None = None,
) -> BatchReport:
    """Run every planned conversion, synchronously, and return the batch report (API-R3).

    Events go to ``sink`` from the calling thread only (API-R4). Every conversion runs in
    this process for now, whatever ``batch_options.isolation`` says: worker subprocesses
    (BAT-R19) arrive with worker isolation.
    """
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

    results: list[ConversionResult] = []
    for planned in plan.conversions:
        if cancel is not None and cancel.cancelled:
            result = _not_attempted(planned)
        else:
            emitter.emit("conversion_started", id=planned.id)
            result = convert(planned, conversion_options, _Reporter(emitter, planned.id))
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


def _not_attempted(planned: PlannedConversion) -> ConversionResult:
    issue = Issue(IssueCode.NOT_ATTEMPTED, "The batch was interrupted before this conversion.")
    return ConversionResult(
        id=planned.id,
        source=planned.source,
        destination=planned.destination,
        outcome=Outcome.SKIPPED,
        issues=[issue],
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
