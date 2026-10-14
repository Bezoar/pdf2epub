"""The CLI's two prompt functions (CLI-R6): a no-echo prompt on the terminal, and the
``--json --interactive`` prompt, which writes a ``password_request`` event and waits for
the answer on stdin (CLI-R13, API-R23).

Both are ``(path, attempt) -> Secret | None`` functions for ``PasswordSources.prompt``;
the core calls them from the thread that runs the batch, never from a worker. Each
returns None, a skip, as soon as the batch is cancelled while it waits.
"""

import json
import logging
import os
import queue
import select
import termios
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from pdf2epub.access import PROMPT_ATTEMPTS
from pdf2epub.cancel import CancelToken
from pdf2epub.events import PROTOCOL_VERSION, Event, EventSink
from pdf2epub.passwords import Secret

log = logging.getLogger(__name__)

# How often a waiting prompt looks at the cancel token.
POLL_INTERVAL = 0.1


class TerminalPrompt:
    """Asks for a password on the terminal: the question on ``stream`` (stderr), the
    answer read from ``fd`` (stdin, a terminal) with echo turned off (PWD-R19). A blank
    line or end of input skips the file. ``before`` runs first, to clear a progress
    line."""

    def __init__(
        self,
        fd: int,
        stream: TextIO,
        cancel: CancelToken,
        before: Callable[[], object] | None = None,
    ) -> None:
        self._fd = fd
        self._stream = stream
        self._cancel = cancel
        self._before = before

    def __call__(self, path: Path, attempt: int) -> Secret | None:
        if self._cancel.cancelled:
            return None
        if self._before is not None:
            self._before()
        saved = termios.tcgetattr(self._fd)
        quiet = list(saved)
        quiet[3] &= ~termios.ECHO  # lflags
        termios.tcsetattr(self._fd, termios.TCSAFLUSH, quiet)
        try:
            self._stream.write(
                f"Password for {path.name} (attempt {attempt} of {PROMPT_ATTEMPTS}; "
                "Enter to skip): "
            )
            self._stream.flush()
            line = self._read_line()
        finally:
            termios.tcsetattr(self._fd, termios.TCSAFLUSH, saved)
            self._stream.write("\n")  # the Enter key was not echoed
            self._stream.flush()
        if not line:
            return None
        return Secret(line.decode("utf-8", errors="replace"))

    def _read_line(self) -> bytes | None:
        """One line typed on the terminal, without its line ending; None at end of input
        or once the batch is cancelled."""
        typed = b""
        while b"\n" not in typed:
            if self._cancel.cancelled:
                return None
            if not select.select([self._fd], [], [], POLL_INTERVAL)[0]:
                continue
            data = os.read(self._fd, 1024)
            if not data:
                return None
            typed += data
        return typed.split(b"\n", 1)[0].removesuffix(b"\r")


def _read_some(fd: int) -> bytes:
    """The next bytes on ``fd``; nothing at end of input or when it can't be read."""
    try:
        return os.read(fd, 65536)
    except OSError:
        log.debug("could not read stdin", exc_info=True)
        return b""


# What the stdin reader hands to a waiting prompt: an answer, or end of input.
_Answer = tuple[str, Secret | None]
_END = None


class InteractivePrompt:
    """The ``--json --interactive`` prompt (CLI-R13, API-R23).

    A reader thread reads JSON Lines from ``fd`` (stdin) for the whole run: a ``cancel``
    message cancels the batch at once, as SIGINT does; a ``password`` message is handed
    to the waiting prompt, its value a ``Secret`` as soon as it is read; anything else
    is ignored with a DEBUG log that never quotes the line. Each prompt writes a
    ``password_request`` event through ``sink`` and waits for the answer with the same
    ``request_id``. End of input counts as a skip, for this request and every later one.

    Call ``observe`` with every event the core emits, before ``sink`` gets it: the
    prompt learns each conversion's id from ``batch_started``, and keeps the time ``t``
    of its own events in step with the core's."""

    def __init__(self, fd: int, sink: EventSink, cancel: CancelToken) -> None:
        self._sink = sink
        self._cancel = cancel
        self._answers: queue.SimpleQueue[_Answer | None] = queue.SimpleQueue()
        self._ended = False
        self._ids: dict[str, int] = {}
        self._clock = (0.0, time.monotonic())
        reader = threading.Thread(target=self._read, args=(fd,), daemon=True)
        reader.start()

    def observe(self, event: Event) -> None:
        self._clock = (event["t"], time.monotonic())
        if event["type"] == "batch_started":
            self._ids = {planned["source"]: planned["id"] for planned in event["planned"]}

    def __call__(self, path: Path, attempt: int) -> Secret | None:
        if self._cancel.cancelled or self._ended:
            return None
        request_id = uuid.uuid4().hex
        last_t, seen_at = self._clock
        t = round(last_t + (time.monotonic() - seen_at), 6)
        event: Event = {
            "v": PROTOCOL_VERSION,
            "type": "password_request",
            "t": t,
            "id": self._ids[str(path)],
            "request_id": request_id,
            "attempt": attempt,
        }
        self.observe(event)
        self._sink(event)
        while not self._cancel.cancelled:
            try:
                answer = self._answers.get(timeout=POLL_INTERVAL)
            except queue.Empty:
                continue
            if answer is _END:
                self._ended = True
                return None
            if answer[0] == request_id:
                return answer[1]
            log.debug("ignored a password answer whose request_id matches no pending request")
        return None

    def _read(self, fd: int) -> None:
        pending = b""
        while data := _read_some(fd):
            *lines, pending = (pending + data).split(b"\n")
            for line in lines:
                self._handle(line)
        if pending.strip():
            self._handle(pending)
        self._answers.put(_END)

    def _handle(self, line: bytes) -> None:
        if not line.strip():
            return
        try:
            message: Any = json.loads(line)
        except ValueError:
            log.debug("ignored a stdin line that is not JSON")
            return
        kind = message.get("type") if isinstance(message, dict) else None
        if kind == "cancel":
            log.debug("cancel message on stdin: cancelling the batch")
            self._cancel.cancel()
            return
        if kind == "password":
            request_id, value = message.get("request_id"), message.get("password")
            # Only an explicit null skips: a message without "password" is malformed.
            if (
                isinstance(request_id, str)
                and "password" in message
                and (value is None or isinstance(value, str))
            ):
                self._answers.put((request_id, None if value is None else Secret(value)))
                return
            log.debug("ignored a malformed password message on stdin")
            return
        log.debug("ignored a stdin message of unknown type")
