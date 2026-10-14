"""Running one conversion in its own worker subprocess (BAT-R19 to BAT-R22), from the
parent's side. The worker's side, and the messages between the two, are in
``pdf2epub.worker``.

The parent turns the worker's messages into events through the conversion's
``Reporter``, so it alone emits events (BAT-R19). It stops the worker, SIGTERM first and
SIGKILL after a grace period, when the batch is cancelled (BAT-R17) or the conversion's
time limit runs out (BAT-R21), and deletes the temporary file the worker said it was
writing. A worker that ends without a result has crashed (BAT-R20).
"""

import json
import logging
import os
import pickle
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pdf2epub.cancel import CancelToken
from pdf2epub.conversion import PlannedConversion, Reporter
from pdf2epub.issues import Issue, IssueCode, derive_outcome
from pdf2epub.options import ConversionOptions
from pdf2epub.passwords import PASSWORD_VARIABLES, Candidate
from pdf2epub.results import ConversionResult

log = logging.getLogger(__name__)

# BAT-R17: how long a worker has to exit after SIGTERM before it is killed.
GRACE = 5.0
# How often the parent looks at the cancel token and the clock while it waits.
POLL_INTERVAL = 0.05


class _Stopped(Exception):
    def __init__(self, issue: Issue) -> None:
        super().__init__(issue.message)
        self.issue = issue


def run_in_worker(
    planned: PlannedConversion,
    options: ConversionOptions,
    reporter: Reporter,
    cancel: CancelToken | None,
    timeout: float,
    candidates: Sequence[Candidate] = (),
) -> ConversionResult:
    """Run ``planned`` in a new worker subprocess and return its result. The password
    ``candidates`` reach the worker only in its request, over its stdin pipe (BAT-R22)."""
    started = time.monotonic()
    deadline = started + timeout
    # BAT-R22: password variables are never handed to a worker; candidates go over its pipe.
    env = {name: value for name, value in os.environ.items() if name not in PASSWORD_VARIABLES}
    request = {
        "planned": planned,
        "options": options,
        "log_level": logging.getLogger("pdf2epub").getEffectiveLevel(),
        # Revealed only to be written to the worker's pipe, as plain (value, label) pairs.
        "candidates": [(c.secret.reveal(), c.source) for c in candidates],
    }
    worker = subprocess.Popen(
        [sys.executable, "-m", "pdf2epub.worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=env,
    )
    assert worker.stdin is not None and worker.stdout is not None

    def stop_reason() -> Issue | None:
        """Why the worker must stop now, if it must: the batch was cancelled (BAT-R17) or
        the time limit ran out (BAT-R21)."""
        if cancel is not None and cancel.cancelled:
            return Issue(
                IssueCode.NOT_ATTEMPTED, "The batch was interrupted during this conversion."
            )
        if time.monotonic() >= deadline:
            return Issue(
                IssueCode.TIMEOUT,
                f"The conversion took longer than its time limit of {timeout:g} seconds "
                "and was stopped.",
            )
        return None

    def answer(reply: bytes) -> None:
        assert worker.stdin is not None
        try:
            worker.stdin.write(reply)
            worker.stdin.flush()
        except BrokenPipeError:
            pass  # it died: reported as a crash

    session = _Session(reporter, stop_reason, answer)
    stopped = False
    try:
        try:
            worker.stdin.write(pickle.dumps(request))
            worker.stdin.flush()
        except BrokenPipeError:
            pass  # it already died: reported below as a crash
        _read_until_done(worker, session, stop_reason)
        worker.wait()
    except _Stopped as stop:
        _stop(worker)
        # Messages the worker wrote before it ended may still sit unread in the pipe: one
        # may name the temporary file that SIGKILL left behind.
        session.find_temporary(worker.stdout.read())
        stopped = True
        session.issues.append(stop.issue)
        reporter.issue(stop.issue)
    finally:
        worker.stdin.close()
        worker.stdout.close()
        if worker.poll() is None:  # only when the parent itself failed
            _stop(worker)
        if session.temporary is not None and session.result is None:
            session.temporary.unlink(missing_ok=True)

    if session.result is not None:
        return session.result
    if not stopped:
        crash = Issue(
            IssueCode.INTERNAL_ERROR,
            f"The worker process for this conversion {_ending(worker.returncode)}; "
            "please report this bug",
        )
        session.issues.append(crash)
        reporter.issue(crash)
    return ConversionResult(
        id=planned.id,
        source=planned.source,
        destination=planned.destination,
        outcome=derive_outcome(session.issues),
        issues=session.issues,
        output=None,
        password_source=None,
        pages=session.pages,
        duration=round(time.monotonic() - started, 3),
        ocr=None,
    )


class _Session:
    """What the parent has learnt from one worker's messages so far."""

    def __init__(
        self,
        reporter: Reporter,
        stop_reason: Callable[[], Issue | None],
        answer: Callable[[bytes], None],
    ) -> None:
        self.reporter = reporter
        self._stop_reason = stop_reason
        self._answer = answer
        self.committed = False
        """True once the worker was told to rename its EPUB over the destination: from
        then on it is left to finish, cancelled or not."""
        self.issues: list[Issue] = []
        self.pages: int | None = None
        self.temporary: Path | None = None
        self.result: ConversionResult | None = None
        self._pending = b""

    def feed(self, data: bytes) -> None:
        self._pending += data
        *lines, self._pending = self._pending.split(b"\n")
        for line in lines:
            if line.strip():
                self._handle(json.loads(line))

    def find_temporary(self, data: bytes) -> None:
        """Note the temporary file named in messages that will not be handled (the worker
        was stopped), passing nothing on and ignoring anything malformed."""
        for line in (self._pending + data).split(b"\n"):
            try:
                message = json.loads(line)
                if message["type"] == "temporary":
                    self.temporary = Path(message["path"])
            except (ValueError, KeyError, TypeError):
                continue

    def _handle(self, message: dict[str, Any]) -> None:
        type_ = message.pop("type")
        if type_ == "progress":
            if message["stage"] == "analyse":
                self.pages = int(message["of"])
            self.reporter.progress(**message)
        elif type_ == "issue":
            issue = Issue.from_dict(message["issue"])
            self.issues.append(issue)
            self.reporter.issue(issue)
        elif type_ == "temporary":
            self.temporary = Path(message["path"])
        elif type_ == "commit":
            reason = self._stop_reason()
            self.committed = reason is None
            self._answer(b"y" if self.committed else b"n")
            if reason is not None:
                raise _Stopped(reason)
        elif type_ == "log":
            record = logging.makeLogRecord(
                {
                    "name": message["name"],
                    "levelno": message["level"],
                    "levelname": logging.getLevelName(message["level"]),
                    "msg": message["message"],
                }
            )
            logging.getLogger(record.name).handle(record)
        elif type_ == "result":
            self.result = ConversionResult.from_dict(message["result"])


def _read_until_done(
    worker: subprocess.Popen[bytes],
    session: _Session,
    stop_reason: Callable[[], Issue | None],
) -> None:
    """Pass on the worker's messages until it closes its stdout. Raises ``_Stopped`` when
    ``stop_reason`` gives a reason to stop first, unless the worker was already told to
    rename its EPUB into place."""
    assert worker.stdout is not None
    fd = worker.stdout.fileno()
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        while True:
            if not session.committed and (reason := stop_reason()) is not None:
                raise _Stopped(reason)
            if not selector.select(POLL_INTERVAL):
                continue
            data = os.read(fd, 65536)
            if not data:
                return
            try:
                session.feed(data)
            except (ValueError, KeyError, TypeError) as error:
                raise _Stopped(
                    Issue(
                        IssueCode.INTERNAL_ERROR,
                        f"The worker process for this conversion sent a malformed message "
                        f"({type(error).__name__}: {error}); please report this bug",
                    )
                ) from error


def _stop(worker: subprocess.Popen[bytes]) -> None:
    """End ``worker``: SIGTERM, then SIGKILL if it is still running after ``GRACE``."""
    worker.terminate()
    try:
        worker.wait(GRACE)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait()


def _ending(returncode: int | None) -> str:
    """How a worker ended, in words: "was killed by SIGABRT", "exited with status 3"."""
    if returncode is not None and returncode < 0:
        try:
            name = signal.Signals(-returncode).name
        except ValueError:
            name = f"signal {-returncode}"
        return f"was killed by {name}"
    return f"exited with status {returncode} without a result"
