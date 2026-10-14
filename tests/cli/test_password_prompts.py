"""Password prompts from the command line, run as a subprocess: the no-echo terminal
prompt (CLI-R6), ``--ask-password``, ``--json`` without a prompt (CLI-R12) and
``--json --interactive`` (CLI-R13, API-R23)."""

import fcntl
import json
import os
import pty
import select
import shutil
import struct
import subprocess
import sys
import termios
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

import pytest
from conftest import FIXTURES, PUBLIC_DOMAIN_SAMPLE
from test_json_output import events_of

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")
AES256 = FIXTURES / "encrypted" / "aes256-user.pdf"
PASSWORD = "hunter2"  # the AES-256 fixture's user password
PROMPT = "Password for "
WAIT = 180.0  # generous: the suite runs in parallel, sometimes on a loaded machine


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "PDF2EPUB_PASSWORD"}


@pytest.fixture
def enc(tmp_path: Path) -> Path:
    target = tmp_path / "enc.pdf"
    shutil.copyfile(AES256, target)
    return target


# --- On a terminal ---------------------------------------------------------------------


class Terminal:
    """The CLI running with stdin and stderr on one pseudo-terminal and stdout a pipe.

    A reader thread drains the terminal all the time: the CLI's progress redraws must
    never fill its buffer and block the CLI."""

    def __init__(self, args: list[str], cwd: Path) -> None:
        self.controller, self.terminal = pty.openpty()
        self._output = b""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self.proc = subprocess.Popen(
            [str(PDF2EPUB), *args],
            cwd=cwd,
            env=child_env(),
            stdin=self.terminal,
            stdout=subprocess.PIPE,
            stderr=self.terminal,
        )

    def _read(self) -> None:
        while not self._stop.is_set():
            if not select.select([self.controller], [], [], 0.05)[0]:
                continue
            try:
                data = os.read(self.controller, 4096)
            except OSError:  # the terminal closed (Linux raises EIO)
                return
            if not data:
                return
            with self._lock:
                self._output += data

    @property
    def output(self) -> str:
        with self._lock:
            return self._output.decode("utf-8", errors="replace")

    def read_until(self, text: str, timeout: float = WAIT) -> str:
        """Everything written to the terminal so far, once it contains ``text``."""
        deadline = time.monotonic() + timeout
        while text not in self.output:
            assert time.monotonic() < deadline, f"{text!r} never appeared in {self.output!r}"
            time.sleep(0.05)
        return self.output

    def type(self, text: str) -> None:
        os.write(self.controller, text.encode())

    def unread(self) -> int:
        """How many bytes typed on the terminal the CLI has not read."""
        buffer = fcntl.ioctl(self.terminal, termios.FIONREAD, struct.pack("i", 0))
        return int(struct.unpack("i", buffer)[0])

    def finish(self) -> tuple[int, str, str]:
        """Wait for the CLI; its exit code, stdout, and everything on the terminal."""
        stdout, _ = self.proc.communicate(timeout=WAIT)
        # Let the reader take what the CLI wrote last: wait until the output settles.
        settled = ""
        while settled != (settled := self.output):
            time.sleep(0.2)
        return self.proc.returncode, stdout.decode("utf-8"), self.output

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self._stop.set()
        self._reader.join(timeout=10)
        os.close(self.terminal)
        os.close(self.controller)


@contextmanager
def on_terminal(args: list[str], cwd: Path) -> Iterator[Terminal]:
    terminal = Terminal(args, cwd)
    try:
        yield terminal
    finally:
        terminal.close()


@pytest.mark.ac("CLI-AC10")
def test_json_without_interactive_never_reads_stdin_and_emits_password_required(
    tmp_path: Path, enc: Path
) -> None:
    with on_terminal(["--json", "enc.pdf"], tmp_path) as terminal:
        # Typed ahead: a prompt that read the terminal would get the right password.
        terminal.type(PASSWORD + "\n")
        code, stdout, output = terminal.finish()
        assert terminal.unread() == len(PASSWORD) + 1

    assert code == 1
    assert PROMPT not in output
    events = events_of(stdout)
    [required] = [e for e in events if e["type"] == "password_required"]
    assert required["sources_tried"] == []
    [finished] = [e for e in events if e["type"] == "conversion_finished"]
    assert [i["code"] for i in finished["issues"]] == ["missing_password"]


@pytest.mark.ac("CLI-AC5")
def test_a_single_conversion_on_a_terminal_prompts_without_echo(tmp_path: Path, enc: Path) -> None:
    with on_terminal(["enc.pdf"], tmp_path) as terminal:
        terminal.read_until(PROMPT)
        terminal.type("wrong\n")
        terminal.read_until("attempt 2")
        terminal.type(PASSWORD + "\n")
        code, _, output = terminal.finish()

    assert code == 0, output
    assert "enc.pdf (attempt 1 of 3" in output
    assert PASSWORD not in output
    assert "wrong" not in output
    assert "✓ " in output
    assert (tmp_path / "enc.epub").is_file()


def test_an_answer_typed_ahead_is_kept_for_the_next_attempt(tmp_path: Path, enc: Path) -> None:
    with on_terminal(["enc.pdf"], tmp_path) as terminal:
        terminal.read_until(PROMPT)
        terminal.type("wrong\n" + PASSWORD + "\n")  # pasted together
        code, _, output = terminal.finish()

    assert code == 0, output
    assert "attempt 2 of 3" in output
    assert PASSWORD not in output
    assert (tmp_path / "enc.epub").is_file()


@pytest.mark.ac("CLI-AC5")
def test_a_blank_answer_skips_the_file(tmp_path: Path, enc: Path) -> None:
    with on_terminal(["enc.pdf"], tmp_path) as terminal:
        terminal.read_until(PROMPT)
        terminal.type("\n")
        code, _, output = terminal.finish()

    assert code == 1
    assert "missing_password" in output
    assert output.count(PROMPT) == 1


@pytest.mark.ac("CLI-AC5")
def test_a_batch_on_a_terminal_prompts_only_with_ask_password(tmp_path: Path, enc: Path) -> None:
    shutil.copyfile(PUBLIC_DOMAIN_SAMPLE, tmp_path / "plain.pdf")

    with on_terminal(["-o", "out", "enc.pdf", "plain.pdf"], tmp_path) as terminal:
        terminal.type(PASSWORD + "\n")
        code, _, output = terminal.finish()
        assert terminal.unread() == len(PASSWORD) + 1
    assert code == 1
    assert PROMPT not in output
    assert "missing_password" in output

    with on_terminal(
        ["--ask-password", "-o", "out2", "enc.pdf", "plain.pdf"], tmp_path
    ) as terminal:
        terminal.read_until(PROMPT + "enc.pdf")
        # PWD-R21: the prompt waits until the conversion that needs none has finished.
        assert (tmp_path / "out2" / "plain.epub").is_file()
        terminal.type(PASSWORD + "\n")
        code, _, output = terminal.finish()
    assert code == 0, output
    assert (tmp_path / "out2" / "enc.epub").is_file()


@pytest.mark.ac("CLI-AC5")
def test_a_single_conversion_without_a_terminal_does_not_prompt(tmp_path: Path, enc: Path) -> None:
    proc = subprocess.run(
        [str(PDF2EPUB), "enc.pdf"],
        cwd=tmp_path,
        env=child_env(),
        input=PASSWORD + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=WAIT,
    )

    assert proc.returncode == 1
    assert PROMPT not in proc.stderr
    assert "missing_password" in proc.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["--interactive", "enc.pdf"],
        ["--json", "--interactive", "--files-from", "-"],
        ["--json", "--ask-password", "enc.pdf"],
        ["--ask-password", "enc.pdf"],
    ],
    ids=["interactive-without-json", "interactive-files-from-stdin", "ask-json", "ask-no-tty"],
)
def test_prompt_flags_in_forbidden_combinations_are_usage_errors(
    tmp_path: Path, enc: Path, args: list[str]
) -> None:
    """CLI-R7 (stdin here is a pipe, not a terminal)."""
    proc = subprocess.run(
        [str(PDF2EPUB), *args],
        cwd=tmp_path,
        env=child_env(),
        input="enc.pdf\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=WAIT,
    )

    assert proc.returncode == 2, proc.stderr
    assert proc.stdout == ""
    assert "usage:" in proc.stderr
    assert not (tmp_path / "enc.epub").exists()


# --- --json --interactive --------------------------------------------------------------


class Interactive:
    """``pdf2epub --json --interactive`` with stdin and stdout as pipes."""

    def __init__(self, args: list[str], cwd: Path) -> None:
        self.proc = subprocess.Popen(
            [str(PDF2EPUB), "--json", "--interactive", *args],
            cwd=cwd,
            env=child_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.lines: list[str] = []

    def next_event(self, type_: str) -> dict[str, Any]:
        stdout: IO[bytes] | None = self.proc.stdout
        assert stdout is not None
        while True:
            line = stdout.readline().decode("utf-8")
            assert line, f"no {type_} event before stdout closed: {self.lines}"
            self.lines.append(line)
            event: dict[str, Any] = json.loads(line)
            if event["type"] == type_:
                return event

    def send(self, line: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((line + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def finish(self, close_stdin: bool = True) -> tuple[int, list[dict[str, Any]], str]:
        assert self.proc.stdin is not None
        if close_stdin:
            self.proc.stdin.close()
            self.proc.stdin = None  # communicate() must not touch it again
        stdout, stderr = self.proc.communicate(timeout=WAIT)
        all_stdout = "".join(self.lines) + stdout.decode("utf-8")
        return self.proc.returncode, events_of(all_stdout), stderr.decode("utf-8")


@pytest.mark.ac("API-AC13")
@pytest.mark.ac("CLI-AC11")
def test_interactive_ignores_bad_lines_and_takes_the_matching_answer(
    tmp_path: Path, enc: Path
) -> None:
    cli = Interactive(["--debug", "enc.pdf"], tmp_path)
    request = cli.next_event("password_request")
    assert request["attempt"] == 1
    cli.send("not json")
    cli.send(json.dumps({"type": "password", "request_id": "other", "password": "x"}))
    cli.send(json.dumps({"type": "unknown"}))
    # No "password" field: malformed, not a skip.
    cli.send(json.dumps({"type": "password", "request_id": request["request_id"]}))
    cli.send(
        json.dumps({"type": "password", "request_id": request["request_id"], "password": PASSWORD})
    )
    code, events, stderr = cli.finish()

    assert code == 0, stderr
    [finished] = [e for e in events if e["type"] == "conversion_finished"]
    assert finished["outcome"] == "converted"
    assert finished["password_source"] == "prompt"
    assert [e["type"] for e in events].count("password_request") == 1
    assert PASSWORD not in stderr
    assert '"x"' not in stderr
    assert "DEBUG: " in stderr


@pytest.mark.ac("API-AC13")
@pytest.mark.ac("CLI-AC11")
def test_a_cancel_message_interrupts_the_batch(tmp_path: Path, enc: Path) -> None:
    cli = Interactive(["enc.pdf"], tmp_path)
    cli.next_event("password_request")
    cli.send(json.dumps({"type": "cancel"}))
    code, events, stderr = cli.finish(close_stdin=False)

    assert code == 130, stderr
    assert events[-1]["type"] == "batch_finished"
    assert events[-1]["interrupted"] is True
    assert not (tmp_path / "enc.epub").exists()


def test_a_wrong_answer_gets_a_second_request(tmp_path: Path, enc: Path) -> None:
    cli = Interactive(["enc.pdf"], tmp_path)
    first = cli.next_event("password_request")
    cli.send(json.dumps({"type": "password", "request_id": first["request_id"], "password": "x"}))
    second = cli.next_event("password_request")
    assert second["attempt"] == 2
    assert second["request_id"] != first["request_id"]
    cli.send(json.dumps({"type": "password", "request_id": second["request_id"], "password": None}))
    code, events, _ = cli.finish()

    assert code == 1
    [finished] = [e for e in events if e["type"] == "conversion_finished"]
    assert [i["code"] for i in finished["issues"]] == ["wrong_password"]


@pytest.mark.ac("CLI-AC12")
def test_closing_stdin_instead_of_answering_fails_missing_password(
    tmp_path: Path, enc: Path
) -> None:
    cli = Interactive(["enc.pdf"], tmp_path)
    cli.next_event("password_request")
    code, events, stderr = cli.finish()

    assert code == 1, stderr
    [finished] = [e for e in events if e["type"] == "conversion_finished"]
    assert finished["outcome"] == "failed"
    assert [i["code"] for i in finished["issues"]] == ["missing_password"]
