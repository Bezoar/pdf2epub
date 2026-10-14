"""``pdf2epub --json``, ``--report`` and logging, run as a subprocess (CLI-R2, CLI-R8,
CLI-R11, CLI-R18, API-R13 to API-R15, API-R19, API-R20, API-R28)."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import NOVEL, PUBLIC_DOMAIN_SAMPLE, validate_event

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")

CONVERSION_RESULT_FIELDS = {
    "id",
    "source",
    "destination",
    "outcome",
    "issues",
    "output",
    "password_source",
    "pages",
    "duration",
    "ocr",
}
# Fields whose values depend on when or how fast the run went.
TIMING_FIELDS = {"t", "started_at", "duration"}
# A line written by Python logging in the CLI's format, e.g. "DEBUG: ...".
LOG_LINE = re.compile(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL): ", re.MULTILINE)


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PDF2EPUB), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def events_of(stdout: str) -> list[dict[str, Any]]:
    """Every stdout line parsed as one JSON object, each validated against the schema."""
    assert stdout.endswith("\n"), stdout[-200:]
    events = []
    for line in stdout.split("\n")[:-1]:
        event = json.loads(line)
        assert isinstance(event, dict), line
        validate_event(event)
        events.append(event)
    return events


def two_pdfs(folder: Path, names: tuple[str, str] = ("a.pdf", "b.pdf")) -> None:
    shutil.copyfile(PUBLIC_DOMAIN_SAMPLE, folder / names[0])
    shutil.copyfile(NOVEL, folder / names[1])


def without_timing(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: without_timing(v) for k, v in value.items() if k not in TIMING_FIELDS}
    if isinstance(value, list):
        return [without_timing(v) for v in value]
    return value


def path_fields(value: Any) -> list[str]:
    """Every value of a path-valued field (``source``, ``destination``, ``output``)."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source", "destination", "output"} and isinstance(item, str):
                found.append(item)
            else:
                found.extend(path_fields(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(path_fields(item))
    return found


@pytest.mark.ac("CLI-AC2")
def test_json_streams_schema_valid_events_from_batch_started_to_batch_finished(
    tmp_path: Path,
) -> None:
    two_pdfs(tmp_path)

    proc = run(["--json", "a.pdf", "b.pdf"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    events = events_of(proc.stdout)
    assert events[0]["type"] == "batch_started"
    assert events[-1]["type"] == "batch_finished"
    assert [e["id"] for e in events if e["type"] == "conversion_finished"] == [0, 1]
    assert "Converted:" not in proc.stderr
    assert "✗" not in proc.stderr
    assert "! " not in proc.stderr


@pytest.mark.ac("API-AC9")
def test_report_file_is_the_last_event_in_plan_order_with_absolute_paths(
    tmp_path: Path,
) -> None:
    two_pdfs(tmp_path, ("b.pdf", "a.pdf"))

    proc = run(["--json", "--report", "report.json", "b.pdf", "a.pdf"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    events = events_of(proc.stdout)
    report_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    report = json.loads(report_text)
    validate_event(report)
    assert report == events[-1]
    assert report_text == proc.stdout.split("\n")[-2] + "\n"
    assert report["conversions"][0]["source"].endswith("b.pdf")
    assert report["conversions"][1]["source"].endswith("a.pdf")
    assert [c["id"] for c in report["conversions"]] == [0, 1]
    for conversion in report["conversions"]:
        assert set(conversion) == CONVERSION_RESULT_FIELDS
    paths = path_fields(events) + path_fields(report)
    assert len(paths) > 10
    assert all(Path(path).is_absolute() for path in paths), paths


@pytest.mark.ac("CLI-AC16")
def test_report_in_human_and_json_modes_equals_the_json_batch_finished(tmp_path: Path) -> None:
    two_pdfs(tmp_path)

    human = run(["--report", "r.json", "--overwrite", "a.pdf", "b.pdf"], cwd=tmp_path)
    assert human.returncode == 0, human.stderr
    assert human.stdout == ""
    assert "Converted: 2" in human.stderr
    human_report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    validate_event(human_report)

    machine = run(["--json", "--report", "r.json", "--overwrite", "a.pdf", "b.pdf"], cwd=tmp_path)
    assert machine.returncode == 0, machine.stderr
    finished = events_of(machine.stdout)[-1]
    machine_report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))

    assert finished["type"] == "batch_finished"
    assert machine_report == finished
    assert without_timing(human_report) == without_timing(finished)


@pytest.mark.ac("CLI-AC16")
def test_unwritable_report_is_logged_and_leaves_the_exit_code(tmp_path: Path) -> None:
    two_pdfs(tmp_path)

    proc = run(["--report", "missing-dir/r.json", "a.pdf", "b.pdf"], cwd=tmp_path)

    assert proc.returncode == 0
    assert "ERROR: " in proc.stderr
    assert "r.json" in proc.stderr
    assert not (tmp_path / "missing-dir").exists()


@pytest.mark.ac("API-AC10")
@pytest.mark.ac("CLI-AC7")
def test_json_debug_keeps_stdout_to_events_and_logs_to_stderr(tmp_path: Path) -> None:
    two_pdfs(tmp_path)

    proc = run(["--json", "--debug", "a.pdf", "b.pdf"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    events = events_of(proc.stdout)
    assert all(event["v"] == 1 for event in events)
    assert events[-1]["type"] == "batch_finished"
    assert not LOG_LINE.search(proc.stdout)
    assert re.search(r"^DEBUG: ", proc.stderr, re.MULTILINE), proc.stderr


@pytest.mark.ac("CLI-AC7")
def test_logging_level_follows_verbose_and_debug(sample_pdf: Path, tmp_path: Path) -> None:
    quiet = run(["--overwrite", "sample.pdf"], cwd=tmp_path)
    verbose = run(["-v", "--overwrite", "sample.pdf"], cwd=tmp_path)
    debug = run(["--debug", "--overwrite", "sample.pdf"], cwd=tmp_path)

    for proc in (quiet, verbose, debug):
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == ""
    assert not re.search(r"^(INFO|DEBUG): ", quiet.stderr, re.MULTILINE), quiet.stderr
    assert re.search(r"^INFO: ", verbose.stderr, re.MULTILINE), verbose.stderr
    assert not re.search(r"^DEBUG: ", verbose.stderr, re.MULTILINE), verbose.stderr
    assert re.search(r"^DEBUG: ", debug.stderr, re.MULTILINE), debug.stderr


@pytest.mark.ac("API-AC16")
def test_installed_cli_json_output_validates_against_the_shipped_schema(
    novel_pdf: Path, tmp_path: Path
) -> None:
    proc = run(["--json", "novel.pdf"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    events = events_of(proc.stdout)
    assert [e["type"] for e in events][:2] == ["batch_started", "conversion_started"]
    assert events[-1]["type"] == "batch_finished"
    assert events[-1]["conversions"][0]["outcome"] == "converted"
