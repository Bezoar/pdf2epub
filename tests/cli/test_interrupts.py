"""SIGINT and SIGTERM to the CLI in the middle of a batch (CLI-R19, BAT-R18).

The first conversion is made slow by a test hook (``tests/hooks``) that also creates a
marker file once that conversion is running, so each signal is sent at a known point
rather than after a guessed delay.
"""

import json
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import worker_hooks
from conftest import NOVEL

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")
NAMES = ("a.pdf", "b.pdf", "c.pdf")
# Generous upper bounds: each wait ends as soon as its condition holds.
WAIT = 60.0


def wait_for(path: Path, proc: subprocess.Popen[str]) -> None:
    """Return once ``path`` exists; fail if ``proc`` ends or ``WAIT`` passes first."""
    deadline = time.monotonic() + WAIT
    while not path.exists():
        if proc.poll() is not None:
            pytest.fail(f"pdf2epub exited early ({proc.returncode}): {proc.communicate()}")
        if time.monotonic() > deadline:
            proc.kill()
            pytest.fail(f"{path.name} never appeared")
        time.sleep(0.02)


def start(tmp_path: Path, rule: dict[str, object], *args: str) -> subprocess.Popen[str]:
    for name in NAMES:
        shutil.copyfile(NOVEL, tmp_path / name)
    return subprocess.Popen(
        [str(PDF2EPUB), *args, *NAMES],
        cwd=tmp_path,
        env=worker_hooks.environment({"a.pdf": rule}),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def hidden(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.startswith("."))


@pytest.mark.ac("CLI-AC17")
@pytest.mark.ac("BAT-AC12")
def test_one_sigint_prints_the_report_and_exits_130(tmp_path: Path) -> None:
    started = tmp_path / "started"
    rule = {"action": "sleep", "seconds": 60, "started": str(started)}
    proc = start(tmp_path, rule, "-v", "--report", "r.json")
    wait_for(started, proc)

    proc.send_signal(signal.SIGINT)
    _, stderr = proc.communicate(timeout=WAIT)

    assert proc.returncode == 130, stderr
    lines = stderr.splitlines()
    assert "Converted: 0  Skipped: 3  Failed: 0  (interrupted)" in lines
    for name in NAMES[1:]:
        assert f"- {tmp_path / name}: not_attempted" in lines
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["interrupted"] is True
    assert report["exit_code"] == 130
    assert [c["issues"][0]["code"] for c in report["conversions"]] == ["not_attempted"] * 3
    started.unlink()
    assert hidden(tmp_path) == []
    assert not list(tmp_path.glob("*.epub"))


@pytest.mark.ac("CLI-AC17")
def test_sigterm_cancels_like_sigint_with_json_output(tmp_path: Path) -> None:
    started = tmp_path / "started"
    rule = {"action": "sleep", "seconds": 60, "started": str(started)}
    proc = start(tmp_path, rule, "--json")
    wait_for(started, proc)

    proc.send_signal(signal.SIGTERM)
    stdout, stderr = proc.communicate(timeout=WAIT)

    assert proc.returncode == 130, stderr
    last = json.loads(stdout.splitlines()[-1])
    assert last["type"] == "batch_finished"
    assert last["interrupted"] is True
    assert [c["outcome"] for c in last["conversions"]] == ["skipped"] * 3


@pytest.mark.ac("BAT-AC12")
def test_a_second_sigint_exits_at_once_without_a_report(tmp_path: Path) -> None:
    started, terminated = tmp_path / "started", tmp_path / "terminated"
    # The worker shrugs off SIGTERM, so the batch is still stopping it at the second SIGINT.
    rule = {"action": "sleep", "seconds": 60, "started": str(started), "on_term": str(terminated)}
    proc = start(tmp_path, rule)
    wait_for(started, proc)

    proc.send_signal(signal.SIGINT)
    wait_for(terminated, proc)
    proc.send_signal(signal.SIGINT)
    stopped = time.monotonic()
    _, stderr = proc.communicate(timeout=WAIT)

    assert proc.returncode == 130, stderr
    assert time.monotonic() - stopped < 4, "it waited out the worker's grace period"
    assert "Converted:" not in stderr


def test_timeout_flag_stops_a_hung_conversion(tmp_path: Path) -> None:
    """``--timeout`` sets ``BatchOptions.timeout`` (the cli spec's flag table)."""
    shutil.copyfile(NOVEL, tmp_path / "a.pdf")
    rules = {"a.pdf": {"action": "sleep", "seconds": 60}}

    started = time.monotonic()
    proc = subprocess.run(
        [str(PDF2EPUB), "--json", "--timeout", "1", "a.pdf"],
        cwd=tmp_path,
        env=worker_hooks.environment(rules),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=WAIT,
        check=False,
    )

    assert proc.returncode == 1, proc.stderr
    assert time.monotonic() - started < 15
    last = json.loads(proc.stdout.splitlines()[-1])
    [conversion] = last["conversions"]
    assert [issue["code"] for issue in conversion["issues"]] == ["timeout"]
