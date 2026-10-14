"""Password sources on the command line, run as a subprocess: ``--password``,
``PDF2EPUB_PASSWORD``, ``--password-file`` and ``--password-map`` (CLI-R6, CLI-R10,
MAIN-AC-C)."""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from conftest import FIXTURES
from test_json_output import events_of

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")
AES256 = FIXTURES / "encrypted" / "aes256-user.pdf"
PASSWORD = "hunter2"  # the AES-256 fixture's user password
WARNING = (
    "warning: --password values are visible to other processes on this machine; "
    "prefer --password-map, --password-file or PDF2EPUB_PASSWORD."
)


def run(
    args: list[str], cwd: Path, env_password: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PDF2EPUB_PASSWORD"}
    if env_password is not None:
        env["PDF2EPUB_PASSWORD"] = env_password
    return subprocess.run(
        [str(PDF2EPUB), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture
def book(tmp_path: Path) -> Path:
    target = tmp_path / "book.pdf"
    shutil.copyfile(AES256, target)
    return target


def epub_text(epub: Path) -> str:
    """Every member of the EPUB, decompressed, as one string."""
    with zipfile.ZipFile(epub) as archive:
        return "".join(
            archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist()
        )


@pytest.mark.ac("MAIN-AC-C")
@pytest.mark.parametrize("via", ["env", "flag"])
def test_encrypted_file_converts_and_the_password_appears_in_no_output(
    tmp_path: Path, book: Path, via: str
) -> None:
    args = ["--json", "--debug", "--report", "report.json", "book.pdf"]
    if via == "flag":
        args = ["--password", PASSWORD, *args]
    proc = run(args, tmp_path, env_password=PASSWORD if via == "env" else None)

    assert proc.returncode == 0, proc.stderr
    [finished] = [e for e in events_of(proc.stdout) if e["type"] == "conversion_finished"]
    assert finished["outcome"] == "converted"
    assert finished["password_source"] == ("env" if via == "env" else "cli #1")
    assert "DEBUG: " in proc.stderr
    report = (tmp_path / "report.json").read_text(encoding="utf-8")
    for output in (proc.stdout, proc.stderr, report, epub_text(tmp_path / "book.epub")):
        assert PASSWORD not in output


@pytest.mark.ac("CLI-AC5")
def test_every_raw_source_reaches_the_provider_in_trial_order(tmp_path: Path, book: Path) -> None:
    (tmp_path / "f.txt").write_text("from-file\n", encoding="utf-8")
    (tmp_path / "m.toml").write_text('"book.pdf" = "from-map"\n', encoding="utf-8")

    proc = run(
        [
            "--json",
            "--password",
            "a",
            "--password",
            "b",
            "--password-file",
            "f.txt",
            "--password-map",
            "m.toml",
            "book.pdf",
        ],
        tmp_path,
        env_password="e",
    )

    assert proc.returncode == 1, proc.stderr
    [finished] = [e for e in events_of(proc.stdout) if e["type"] == "conversion_finished"]
    [issue] = finished["issues"]
    assert issue["code"] == "wrong_password"
    assert issue["hint"] == (
        'check the password; sources tried: map:"book.pdf", cli #1, cli #2, env, file:line 1'
    )

    # The last source holds the right password: the file opens with it.
    (tmp_path / "f.txt").write_text(f"{PASSWORD}\n", encoding="utf-8")
    proc = run(
        ["--json", "--password-file", "f.txt", "--password-map", "m.toml", "book.pdf"],
        tmp_path,
        env_password="e",
    )
    assert proc.returncode == 0, proc.stderr
    [finished] = [e for e in events_of(proc.stdout) if e["type"] == "conversion_finished"]
    assert finished["password_source"] == "file:line 1"


@pytest.mark.ac("CLI-AC9")
def test_password_flag_prints_the_visibility_warning_once(tmp_path: Path, book: Path) -> None:
    proc = run(["--password", PASSWORD, "-q", "book.pdf"], tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.splitlines().count(WARNING) == 1
    assert (tmp_path / "book.epub").is_file()

    proc = run(["--overwrite", "-q", "book.pdf"], tmp_path, env_password=PASSWORD)

    assert proc.returncode == 0, proc.stderr
    assert "--password values are visible" not in proc.stderr
