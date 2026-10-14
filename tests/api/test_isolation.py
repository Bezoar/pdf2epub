"""Worker isolation, timeouts and cancellation through ``plan_batch`` / ``run_batch``
(API-R5, API-R6, BAT-R17, BAT-R19 to BAT-R21).

Crashes, hangs and slowness come from the test hooks in ``tests/hooks``; a worker picks
them up from its environment, so each test that needs one sets it with ``monkeypatch``.
"""

import shutil
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import worker_hooks
from conftest import NOVEL, PUBLIC_DOMAIN_SAMPLE, RecordingSink

from pdf2epub import (
    BatchOptions,
    BatchReport,
    CancelToken,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    IssueCode,
    Outcome,
    plan_batch,
    run_batch,
)
from pdf2epub import conversion as conversion_module
from pdf2epub.options import Isolation
from pdf2epub.reflow.source import open_source


def run(
    sources: list[Path],
    isolation: Isolation,
    sink: Any,
    cancel: CancelToken | None = None,
    timeout: int = 1800,
) -> BatchReport:
    plan = plan_batch([InputSpec(source) for source in sources], DiscoveryOptions())
    return run_batch(
        plan,
        BatchOptions(isolation=isolation, timeout=timeout),
        ConversionOptions(),
        sink,
        cancel=cancel,
    )


def copies(source: Path, folder: Path, *names: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    targets = [folder / name for name in names]
    for target in targets:
        shutil.copyfile(source, target)
    return targets


def leftovers(folder: Path) -> list[str]:
    """Hidden (temporary) files left in ``folder``."""
    return sorted(p.name for p in folder.iterdir() if p.name.startswith("."))


def use_hooks(monkeypatch: pytest.MonkeyPatch, rules: worker_hooks.Rules) -> None:
    """Install ``rules`` in every worker this test starts."""
    for name, value in worker_hooks.environment(rules).items():
        monkeypatch.setenv(name, value)


def issue_codes(report: BatchReport) -> list[list[IssueCode]]:
    return [[issue.code for issue in result.issues] for result in report.conversions]


@pytest.mark.ac("API-AC3")
def test_subprocess_and_inprocess_runs_agree(tmp_path: Path) -> None:
    results = {}
    for isolation in ("inprocess", "subprocess"):
        [pdf] = copies(PUBLIC_DOMAIN_SAMPLE, tmp_path / isolation, "sample.pdf")
        sink = RecordingSink()
        report = run([pdf], isolation, sink)
        events = [e["type"] for e in sink.events]
        progress = [(e["stage"], e["done"], e["of"]) for e in sink.of_type("progress")]
        [result] = report.conversions
        assert result.output is not None
        epub = Path(result.output).read_bytes()
        results[isolation] = (events, progress, result.outcome, issue_codes(report), epub)

    assert results["subprocess"] == results["inprocess"]
    assert results["subprocess"][2] is Outcome.CONVERTED


@pytest.mark.ac("BAT-AC13")
def test_a_crashing_worker_fails_its_conversion_and_the_batch_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crash, good = copies(NOVEL, tmp_path, "crash.pdf", "good.pdf")
    use_hooks(monkeypatch, {"crash.pdf": {"action": "abort"}})
    sink = RecordingSink()

    report = run([crash, good], "subprocess", sink)

    first, second = report.conversions
    assert first.outcome is Outcome.FAILED
    assert [issue.code for issue in first.issues] == [IssueCode.INTERNAL_ERROR]
    assert first.issues[0].message.endswith("please report this bug")
    assert second.outcome is Outcome.CONVERTED
    assert good.with_suffix(".epub").is_file()
    assert not crash.with_suffix(".epub").exists()
    assert report.exit_code == 1
    assert [e["type"] for e in sink.events][-1] == "batch_finished"


@pytest.mark.ac("BAT-AC13")
def test_an_unexpected_exception_inprocess_fails_only_that_conversion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crash, good = copies(NOVEL, tmp_path, "crash.pdf", "good.pdf")
    hooked = worker_hooks.wrap(open_source, {"crash.pdf": {"action": "raise"}})
    monkeypatch.setattr(conversion_module, "open_source", hooked)

    report = run([crash, good], "inprocess", RecordingSink())

    first, second = report.conversions
    assert [issue.code for issue in first.issues] == [IssueCode.INTERNAL_ERROR]
    assert first.issues[0].message.endswith("please report this bug")
    assert second.outcome is Outcome.CONVERTED
    assert report.exit_code == 1


@pytest.mark.ac("BAT-AC14")
def test_a_hung_worker_is_stopped_at_the_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hung, good = copies(NOVEL, tmp_path, "hung.pdf", "good.pdf")
    rules = {"hung.pdf": {"action": "sleep", "seconds": 60}}
    use_hooks(monkeypatch, rules)

    sink = RecordingSink()
    report = run([hung, good], "subprocess", sink, timeout=2)

    first, second = report.conversions
    assert [issue.code for issue in first.issues] == [IssueCode.TIMEOUT]
    assert first.outcome is Outcome.FAILED
    assert first.duration < 15  # from the worker's start, which the limit counts too
    # The next conversion runs (under the same 2-second limit, so a slow machine may stop
    # it too).
    assert [e["id"] for e in sink.of_type("conversion_started")] == [0, 1]
    assert IssueCode.NOT_ATTEMPTED not in [issue.code for issue in second.issues]
    assert leftovers(tmp_path) == []
    assert not hung.with_suffix(".epub").exists()


@pytest.mark.ac("BAT-AC11")
def test_a_worker_that_ignores_sigterm_is_killed_after_the_grace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BAT-R17's SIGTERM, then SIGKILL after the grace. The worker ignores SIGTERM from
    the moment it creates ``started``; a thread waits for that file, then cancels."""
    hung, other = copies(NOVEL, tmp_path, "hung.pdf", "other.pdf")
    started, term = tmp_path.parent / f"{tmp_path.name}-started", tmp_path / "term"
    rule = {"action": "sleep", "seconds": 60, "started": str(started), "on_term": str(term)}
    use_hooks(monkeypatch, {"hung.pdf": rule})
    cancel = CancelToken()
    cancelled_at: list[float] = []

    def cancel_once_started() -> None:
        deadline = time.monotonic() + 60
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        cancelled_at.append(time.monotonic())
        cancel.cancel()

    canceller = threading.Thread(target=cancel_once_started)
    canceller.start()
    report = run([hung, other], "subprocess", RecordingSink(), cancel=cancel)
    finished = time.monotonic()
    canceller.join()

    assert started.exists(), "the worker never reached the hook"
    assert term.exists(), "the worker got SIGTERM first"
    assert 5 <= finished - cancelled_at[0] < 15, "killed after the 5-second grace"
    first, second = report.conversions
    assert [issue.code for issue in first.issues] == [IssueCode.NOT_ATTEMPTED]
    assert [issue.code for issue in second.issues] == [IssueCode.NOT_ATTEMPTED]
    term.unlink()
    assert leftovers(tmp_path) == []
    assert not hung.with_suffix(".epub").exists()


class CancelOnFirstProgress:
    """A recording sink that cancels the batch on the first ``progress`` event of one
    conversion."""

    def __init__(self, cancel: CancelToken, conversion_id: int) -> None:
        self.recording = RecordingSink()
        self._cancel = cancel
        self._id = conversion_id

    def __call__(self, event: dict[str, Any]) -> None:
        self.recording(event)
        if event["type"] == "progress" and event["id"] == self._id:
            self._cancel.cancel()


@pytest.mark.ac("API-AC4")
@pytest.mark.parametrize("isolation", ["inprocess", "subprocess"])
def test_cancelling_mid_batch_marks_the_rest_not_attempted(
    tmp_path: Path, isolation: Isolation
) -> None:
    pdfs = copies(NOVEL, tmp_path, "a.pdf", "b.pdf", "c.pdf")
    cancel = CancelToken()
    sink = CancelOnFirstProgress(cancel, 0)

    report = run(pdfs, isolation, sink, cancel=cancel)

    assert report.interrupted is True
    assert report.exit_code == 130
    for result in report.conversions[1:]:
        assert result.outcome is Outcome.SKIPPED
        assert [issue.code for issue in result.issues] == [IssueCode.NOT_ATTEMPTED]
    # BAT-R17: the conversion running at the time is not attempted either.
    assert [issue.code for issue in report.conversions[0].issues] == [IssueCode.NOT_ATTEMPTED]
    assert not any(pdf.with_suffix(".epub").exists() for pdf in pdfs)
    assert leftovers(tmp_path) == []
    assert sink.recording.events[-1]["type"] == "batch_finished"


@pytest.mark.ac("BAT-AC11")
def test_cancelling_in_subprocess_mode_stops_the_worker(tmp_path: Path) -> None:
    pdfs = copies(NOVEL, tmp_path, "a.pdf", "b.pdf", "c.pdf")
    cancel = CancelToken()
    sink = CancelOnFirstProgress(cancel, 1)

    report = run(pdfs, "subprocess", sink, cancel=cancel)

    first, *rest = report.conversions
    assert first.outcome is Outcome.CONVERTED
    assert pdfs[0].with_suffix(".epub").is_file()
    for result, pdf in zip(rest, pdfs[1:], strict=True):
        assert result.outcome is Outcome.SKIPPED
        assert [issue.code for issue in result.issues] == [IssueCode.NOT_ATTEMPTED]
        assert not pdf.with_suffix(".epub").exists()
    assert leftovers(tmp_path) == []
    last = sink.recording.events[-1]
    assert last["type"] == "batch_finished"
    assert last["interrupted"] is True
    assert last["exit_code"] == report.exit_code == 130


@pytest.mark.ac("BAT-AC11")
def test_cancelling_during_a_slow_worker_stops_it_promptly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, slow, c = copies(NOVEL, tmp_path, "a.pdf", "slow.pdf", "c.pdf")
    rules = {"slow.pdf": {"action": "sleep", "seconds": 60}}
    use_hooks(monkeypatch, rules)
    cancel = CancelToken()

    def sink(event: dict[str, Any]) -> None:
        if event["type"] == "conversion_started" and event["id"] == 1:
            cancel.cancel()

    started = time.monotonic()
    report = run([a, slow, c], "subprocess", sink, cancel=cancel)

    # Far less than the hook's 60 seconds, even on a slow, measured run.
    assert time.monotonic() - started < 45
    assert [r.outcome for r in report.conversions] == [
        Outcome.CONVERTED,
        Outcome.SKIPPED,
        Outcome.SKIPPED,
    ]
    assert report.exit_code == 130


@pytest.mark.ac("BAT-AC11")
def test_a_cancel_just_before_the_rename_leaves_no_epub(tmp_path: Path) -> None:
    """The worker finishes its EPUB right after the last ``reflow`` progress event. The
    sink cancels on that event, then holds the parent for a while, as a busy parent might
    be held, so that the worker reaches the rename before the parent acts on the cancel.
    The EPUB must still not appear at its destination."""
    [pdf] = copies(NOVEL, tmp_path, "a.pdf")
    epub = pdf.with_suffix(".epub")
    cancel = CancelToken()

    def sink(event: dict[str, Any]) -> None:
        if event["type"] == "progress" and event["stage"] == "reflow":
            cancel.cancel()
            deadline = time.monotonic() + 3
            while not epub.exists() and time.monotonic() < deadline:
                time.sleep(0.02)

    report = run([pdf], "subprocess", sink, cancel=cancel)

    [result] = report.conversions
    assert [issue.code for issue in result.issues] == [IssueCode.NOT_ATTEMPTED]
    assert not epub.exists()
    assert leftovers(tmp_path) == []


@pytest.mark.ac("BAT-AC14")
def test_a_rename_asked_for_after_the_time_limit_is_a_timeout(tmp_path: Path) -> None:
    """The sink holds the parent past the 2-second limit on the last ``reflow`` progress
    event, so the worker asks to rename its EPUB only after the limit. (On a machine slow
    enough to reach the limit before that event, the conversion times out all the
    same.)"""
    [pdf] = copies(NOVEL, tmp_path, "a.pdf")
    started = time.monotonic()

    def sink(event: dict[str, Any]) -> None:
        if event["type"] == "progress" and event["stage"] == "reflow":
            while time.monotonic() < started + 2.5:
                time.sleep(0.05)

    report = run([pdf], "subprocess", sink, timeout=2)

    [result] = report.conversions
    assert [issue.code for issue in result.issues] == [IssueCode.TIMEOUT]
    assert result.outcome is Outcome.FAILED
    assert report.exit_code == 1
    assert not pdf.with_suffix(".epub").exists()
    assert leftovers(tmp_path) == []


@pytest.mark.ac("BAT-AC11")
def test_a_killed_worker_leaves_no_temporary_file_even_if_its_message_was_unread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker ignores SIGTERM, so it is killed after the grace. The sink holds the
    parent from the last ``reflow`` event until the worker's temporary file exists, so the
    message naming that file is still unread in the pipe when the parent stops it."""
    [pdf] = copies(NOVEL, tmp_path, "a.pdf")
    term = tmp_path.parent / f"{tmp_path.name}-term"
    use_hooks(monkeypatch, {"a.pdf": {"action": "sleep", "seconds": 0, "on_term": str(term)}})
    cancel = CancelToken()

    def sink(event: dict[str, Any]) -> None:
        if event["type"] == "progress" and event["stage"] == "reflow":
            cancel.cancel()
            deadline = time.monotonic() + 30
            while not leftovers(tmp_path) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert leftovers(tmp_path), "the worker never wrote its temporary file"

    report = run([pdf], "subprocess", sink, cancel=cancel)

    assert term.exists(), "the worker got SIGTERM and ignored it"
    [result] = report.conversions
    assert [issue.code for issue in result.issues] == [IssueCode.NOT_ATTEMPTED]
    assert leftovers(tmp_path) == []
    assert not pdf.with_suffix(".epub").exists()
