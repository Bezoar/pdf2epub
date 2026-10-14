"""Usage errors end the run with exit code 2 before any conversion starts (BAT-R25,
CLI-R3)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import NOVEL

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PDF2EPUB), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.ac("BAT-AC18")
@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (["--no-such-flag", "a.pdf"], "--no-such-flag"),
        (["--files-from", "missing-list.txt"], "missing-list.txt"),
        (["a.pdf", "b.pdf", "-o", "existing.txt"], "existing.txt"),
        ([], "no inputs"),
        (["--timeout", "0", "a.pdf"], "--timeout"),
    ],
    ids=["unknown-flag", "missing-files-from", "output-is-a-file", "no-inputs", "timeout-0"],
)
@pytest.mark.parametrize("mode", [[], ["--json"]], ids=["human", "json"])
def test_usage_error_exits_2_with_a_reason_and_converts_nothing(
    tmp_path: Path, args: list[str], reason: str, mode: list[str]
) -> None:
    shutil.copyfile(NOVEL, tmp_path / "a.pdf")
    shutil.copyfile(NOVEL, tmp_path / "b.pdf")
    (tmp_path / "existing.txt").write_bytes(b"not touched")

    proc = run([*mode, *args], tmp_path)

    assert proc.returncode == 2, proc.stderr
    assert reason in proc.stderr
    assert proc.stdout == ""  # in --json mode: no events at all, so no batch_started
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf", "b.pdf", "existing.txt"]
    assert (tmp_path / "existing.txt").read_bytes() == b"not touched"


def test_an_empty_files_from_list_is_an_empty_batch_not_a_usage_error(tmp_path: Path) -> None:
    # CLI-R7: only "no INPUT and no --files-from" is a usage error.
    (tmp_path / "list.txt").write_text("# nothing to convert yet\n", encoding="utf-8")

    proc = run(["--files-from", "list.txt"], tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.splitlines()[0] == "Converted: 0  Skipped: 0  Failed: 0"


def planned(proc: subprocess.CompletedProcess[str]) -> list[tuple[str, str | None]]:
    first = json.loads(proc.stdout.splitlines()[0])
    assert first["type"] == "batch_started"
    return [(p["source"], p["destination"]) for p in first["planned"]]


def test_cli_forwards_recursive_files_from_and_output(tmp_path: Path) -> None:
    (tmp_path / "books" / "sub").mkdir(parents=True)
    shutil.copyfile(NOVEL, tmp_path / "books" / "sub" / "deep.pdf")
    shutil.copyfile(NOVEL, tmp_path / "listed.pdf")
    (tmp_path / "list.txt").write_text("listed.pdf\n", encoding="utf-8")

    recursive = run(["--json", "-r", "books", "--files-from", "list.txt"], tmp_path)
    single = run(["--json", "listed.pdf", "-o", "out/Named.epub"], tmp_path)

    assert planned(recursive) == [
        (str(tmp_path / "books" / "sub" / "deep.pdf"), str(tmp_path / "books/sub/deep.epub")),
        (str(tmp_path / "listed.pdf"), str(tmp_path / "listed.epub")),
    ]
    assert planned(single) == [(str(tmp_path / "listed.pdf"), str(tmp_path / "out/Named.epub"))]
    assert (tmp_path / "out" / "Named.epub").is_file()
