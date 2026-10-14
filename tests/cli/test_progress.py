"""Progress on stderr (CLI-R14): one redrawn line on a terminal, at most about 10 redraws
a second, and no redraws when stderr is not a terminal."""

import itertools
import os
import pty
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")


@pytest.mark.ac("CLI-AC13")
def test_no_redraws_when_stderr_is_a_pipe(sample_pdf: Path, tmp_path: Path) -> None:
    proc = subprocess.run(
        [str(PDF2EPUB), "sample.pdf"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "\r" not in proc.stderr
    assert (tmp_path / "sample.epub").is_file()


def run_on_terminal(args: list[str], cwd: Path) -> tuple[int, list[tuple[float, bytes]]]:
    """Run the CLI with stderr on a pseudo-terminal; return its exit code and each chunk
    read from the terminal with the time it arrived."""
    controller, terminal = pty.openpty()
    chunks: list[tuple[float, bytes]] = []

    def read() -> None:
        while True:
            try:
                data = os.read(controller, 4096)
            except OSError:  # the terminal closed (Linux raises EIO)
                return
            if not data:
                return
            chunks.append((time.monotonic(), data))

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        proc = subprocess.run(
            [str(PDF2EPUB), *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=terminal,
            check=False,
            timeout=120,
        )
    finally:
        os.close(terminal)
    reader.join(timeout=10)
    os.close(controller)
    return proc.returncode, chunks


@pytest.mark.ac("CLI-AC13")
def test_redraws_on_a_terminal_are_spaced_at_least_about_100_ms(
    sample_pdf: Path, tmp_path: Path
) -> None:
    code, chunks = run_on_terminal(["sample.pdf"], tmp_path)

    assert code == 0
    output = b"".join(data for _, data in chunks).decode("utf-8")
    frame = "\r[1/1] sample.pdf · "
    assert output.count(frame) >= 1, output
    # The result line is still printed once the progress line is done.
    assert "✓ " in output.rsplit(frame, 1)[-1], output
    # Each redraw arrives on its own, about 100 ms or more after the one before.
    draws = [at for at, data in chunks for _ in range(data.count(frame.encode()))]
    gaps = [later - earlier for earlier, later in itertools.pairwise(draws)]
    assert all(gap >= 0.08 for gap in gaps), gaps


@pytest.mark.ac("CLI-AC13")
def test_log_lines_on_a_terminal_start_on_a_cleared_line(sample_pdf: Path, tmp_path: Path) -> None:
    code, chunks = run_on_terminal(["--debug", "sample.pdf"], tmp_path)

    assert code == 0
    output = b"".join(data for _, data in chunks).decode("utf-8")
    logged = [line for line in output.split("\n") if "DEBUG: " in line or "INFO: " in line]
    assert logged, output
    for line in logged:
        before = line[: min(i for i in (line.find("DEBUG: "), line.find("INFO: ")) if i >= 0)]
        # Whatever progress frame was on the line has been cleared first.
        assert before.rsplit("\r", 1)[-1] in ("", "\x1b[K"), repr(line)
