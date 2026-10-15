"""Test hooks that make a conversion crash, hang or run slowly (BAT-AC13, BAT-AC14,
BAT-AC12, CLI-AC17), or record how its process was started (BAT-AC15).

They live in the test suite only: nothing in the ``pdf2epub`` package knows of them. A
test reaches a worker subprocess by putting this folder on ``PYTHONPATH`` (see
``environment``): Python then runs ``sitecustomize.py`` from here at start-up, which calls
``install_from_environment`` before the worker imports anything else. An in-process test
calls ``wrap`` itself.

The rules are keyed by the source PDF's file name; a conversion of any other file runs
normally. Each rule is a dict:

- ``{"action": "kill"}``: the process is killed by SIGKILL, as a crashing library or the
  operating system's out-of-memory killer would end it. Not SIGABRT (``os.abort()``):
  macOS's crash reporter would show a "Python quit unexpectedly" dialog for each one.
- ``{"action": "raise"}``: an unexpected ``RuntimeError`` is raised.
- ``{"action": "sleep", "seconds": S}``: the conversion sleeps for ``S`` seconds, then goes
  on normally. With ``"started": PATH`` it first creates the file ``PATH``, so a test can
  wait for the conversion to be running rather than guess with a sleep. With
  ``"on_term": PATH`` the process ignores SIGTERM, creating ``PATH`` when one arrives, so
  that it outlives the grace period of BAT-R17 until it is killed.
- ``{"action": "record", "path": PATH}``: the process's argv and environment are written
  to ``PATH`` as JSON (``{"argv": [...], "env": {...}}``), then the conversion goes on
  normally.

A separate hook captures the options the CLI hands the core (CLI-AC3): with
``PDF2EPUB_TEST_CAPTURE`` set to a file path (see ``capture_environment``), the CLI
process pickles the options objects it passes to ``plan_batch`` and ``run_batch`` to that
file, as ``{"discovery": ..., "batch": ..., "conversion": ...}``, and exits with code 0
instead of running the batch.
"""

import json
import os
import signal
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

VARIABLE = "PDF2EPUB_TEST_HOOKS"
CAPTURE_VARIABLE = "PDF2EPUB_TEST_CAPTURE"
HERE = Path(__file__).resolve().parent

Rules = Mapping[str, Mapping[str, Any]]


def environment(rules: Rules, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of ``base`` (default ``os.environ``) under which every Python process, and
    so every worker, runs with ``rules`` installed."""
    env = dict(os.environ if base is None else base)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(HERE), env.get("PYTHONPATH")]))
    env[VARIABLE] = json.dumps(rules)
    return env


def capture_environment(path: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of ``base`` (default ``os.environ``) under which the CLI writes the options
    it passes to the core to ``path`` and stops before running the batch."""
    env = environment({}, base)
    del env[VARIABLE]
    env[CAPTURE_VARIABLE] = str(path)
    return env


def wrap(open_source: Callable[..., Any], rules: Rules) -> Callable[..., Any]:
    """``open_source`` with ``rules`` applied before each call."""

    def hooked(path: Path, *args: Any) -> Any:
        rule = rules.get(Path(path).name)
        if rule is not None:
            _apply(rule)
        return open_source(path, *args)

    return hooked


def install_from_environment() -> None:
    """Apply the rules in ``PDF2EPUB_TEST_HOOKS``, if set, to this process's conversions."""
    capture = os.environ.get(CAPTURE_VARIABLE)
    if capture:
        _install_capture(Path(capture))
    text = os.environ.get(VARIABLE)
    if not text:
        return
    from pdf2epub import conversion
    from pdf2epub.reflow.source import open_source

    # pdf2epub.conversion looks open_source up each time it converts a PDF.
    setattr(conversion, "open_source", wrap(open_source, json.loads(text)))  # noqa: B010


def _install_capture(path: Path) -> None:
    """Make the CLI record the options objects it passes to the core, then stop."""
    import pickle

    from pdf2epub import cli

    captured: dict[str, Any] = {}
    real_plan_batch = getattr(cli, "plan_batch")  # noqa: B009 - imported, not exported

    def plan_batch(inputs: Any, options: Any) -> Any:
        captured["discovery"] = options
        return real_plan_batch(inputs, options)

    def run_batch(plan: Any, options: Any, conversion_options: Any, *args: Any, **kw: Any) -> Any:
        captured["batch"] = options
        captured["conversion"] = conversion_options
        path.write_bytes(pickle.dumps(captured))
        raise SystemExit(0)

    # pdf2epub.cli looks both names up each time it runs.
    setattr(cli, "plan_batch", plan_batch)  # noqa: B010
    setattr(cli, "run_batch", run_batch)  # noqa: B010


def _apply(rule: Mapping[str, Any]) -> None:
    action = rule["action"]
    if action == "kill":
        os.kill(os.getpid(), signal.SIGKILL)
    if action == "raise":
        raise RuntimeError("test hook: unexpected failure")
    if action == "sleep":
        if "on_term" in rule:
            marker = Path(rule["on_term"])
            signal.signal(signal.SIGTERM, lambda signum, frame: marker.touch())
        if "started" in rule:
            Path(rule["started"]).touch()
        deadline = time.monotonic() + float(rule["seconds"])
        while (left := deadline - time.monotonic()) > 0:
            time.sleep(left)  # a handled signal may cut a sleep short
        return
    if action == "record":
        record = {"argv": sys.argv, "env": dict(os.environ)}
        Path(rule["path"]).write_text(json.dumps(record), encoding="utf-8")
        return
    raise ValueError(f"unknown test hook action {action!r}")
