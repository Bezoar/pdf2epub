"""The worker subprocess that runs one conversion in subprocess isolation (BAT-R19):
``python -m pdf2epub.worker``.

The parent (``pdf2epub.isolation``) writes one pickled request to the worker's stdin and
keeps stdin open; end of stdin means the parent is gone, and the worker exits at once.
The request is a dict, so later fields (candidate passwords, BAT-R22) can join it without
touching argv or the environment:

- ``planned``: the ``PlannedConversion``;
- ``options``: the ``ConversionOptions``;
- ``log_level``: the level of the parent's ``pdf2epub`` logger;
- ``candidates``: the password candidates as (value, source label) pairs, each value
  wrapped in a ``Secret`` again as soon as the request is read.

The worker answers on its stdout with JSON Lines messages, one per line, which the parent
turns into events and log records:

- ``{"type": "progress", "stage", "done", "of", ...}`` and ``{"type": "issue", "issue"}``,
  as the conversion's ``Reporter`` receives them;
- ``{"type": "temporary", "path"}``, before the EPUB's temporary file is written;
- ``{"type": "commit"}``, when the EPUB is complete in that file: the worker then waits for
  one byte on stdin, ``y`` to rename it over the destination or ``n`` to abandon the
  conversion. The parent answers ``n`` once the batch is cancelled or the time limit has
  run out, and never stops a worker it has answered ``y``, so an EPUB is never left at
  its destination by a conversion reported as stopped (BAT-R13, BAT-R17);
- ``{"type": "log", "name", "level", "message"}``, for each log record;
- ``{"type": "result", "result"}``, last: the ``ConversionResult`` wire form.

Anything else the conversion writes to stdout goes to stderr instead, so it can't corrupt
the messages. The worker ignores SIGINT (a Ctrl-C in the terminal reaches the whole
process group; the parent decides what it means) and turns SIGTERM into an orderly exit
that deletes its temporary file (BAT-R17).
"""

import json
import logging
import os
import pickle
import queue
import signal
import sys
import threading
from pathlib import Path
from types import FrameType
from typing import Any, BinaryIO

from pdf2epub.conversion import convert
from pdf2epub.issues import Issue
from pdf2epub.passwords import Candidate, Secret

# The exit status after SIGTERM, as a shell reports a process that SIGTERM ended.
TERMINATED = 128 + signal.SIGTERM


class _Channel:
    """The message pipe to the parent."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, type_: str, **fields: Any) -> None:
        line = json.dumps({"type": type_, **fields}, ensure_ascii=False, allow_nan=False)
        with self._lock:
            self._stream.write(line.encode("utf-8") + b"\n")
            self._stream.flush()


class _PipeReporter:
    def __init__(self, channel: _Channel) -> None:
        self._channel = channel

    def progress(self, stage: str, done: int, of: int, **fields: Any) -> None:
        self._channel.send("progress", stage=stage, done=done, of=of, **fields)

    def issue(self, issue: Issue) -> None:
        self._channel.send("issue", issue=issue.to_dict())

    def temporary(self, path: Path) -> None:
        self._channel.send("temporary", path=str(path))

    def commit(self) -> bool:
        self._channel.send("commit")
        return _ANSWERS.get() == b"y"


# The parent's one-byte answers, read from stdin by the watcher thread.
_ANSWERS: "queue.SimpleQueue[bytes]" = queue.SimpleQueue()


class _PipeHandler(logging.Handler):
    """Sends each log record to the parent, which logs it through its own handlers."""

    def __init__(self, channel: _Channel) -> None:
        super().__init__()
        self._channel = channel
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self._channel.send(
            "log", name=record.name, level=record.levelno, message=self.format(record)
        )


def _terminate(signum: int, frame: FrameType | None) -> None:
    raise SystemExit(TERMINATED)


def _watch_stdin(fd: int) -> None:
    """Queue each byte the parent sends, until end of stdin, which comes only when the
    parent closes it or exits; then end this process at once. It reads the file
    descriptor, not ``sys.stdin``, so it holds no lock that would stop the interpreter
    from shutting down while it waits."""
    while data := os.read(fd, 65536):
        for answer in data:
            _ANSWERS.put(bytes([answer]))
    os._exit(1)


def main() -> int:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, _terminate)

    channel = _Channel(os.fdopen(os.dup(sys.stdout.fileno()), "wb"))
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    stdin = sys.stdin.buffer
    request: dict[str, Any] = pickle.load(stdin)
    # The parent writes nothing after the request, so the buffer holds nothing more.
    watcher = threading.Thread(target=_watch_stdin, args=(stdin.fileno(),))
    watcher.daemon = True
    watcher.start()

    root = logging.getLogger()
    root.handlers[:] = [_PipeHandler(channel)]
    root.setLevel(logging.WARNING)
    logging.getLogger("pdf2epub").setLevel(request["log_level"])

    candidates = [Candidate(Secret(value), source) for value, source in request.pop("candidates")]
    result = convert(
        request["planned"], request["options"], _PipeReporter(channel), None, candidates
    )
    channel.send("result", result=result.to_dict())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
