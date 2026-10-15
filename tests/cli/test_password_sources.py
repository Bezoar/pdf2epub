"""Password sources on the command line, run as a subprocess: ``--password``,
``PDF2EPUB_PASSWORD``, ``--password-file`` and ``--password-map`` (CLI-R6, CLI-R10,
MAIN-AC-C)."""

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from conftest import FIXTURES
from pypdf import PdfReader
from pypdf.generic import DictionaryObject
from test_json_output import events_of

PDF2EPUB = Path(sys.executable).with_name("pdf2epub")
AES256 = FIXTURES / "encrypted" / "aes256-user.pdf"
PASSWORD = "hunter2"  # the AES-256 fixture's user password
WARNING = (
    "warning: --password values are visible to other processes on this machine; "
    "prefer --password-map, --password-file or PDF2EPUB_PASSWORD."
)


def run(
    args: list[str],
    cwd: Path,
    env_password: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PDF2EPUB_PASSWORD"}
    if env_password is not None:
        env["PDF2EPUB_PASSWORD"] = env_password
    env.update(extra_env or {})
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


def encrypted_copies(folder: Path, *names: str) -> None:
    for name in names:
        shutil.copyfile(AES256, folder / name)


def assert_nothing_ran(proc: subprocess.CompletedProcess[str], folder: Path) -> None:
    """A usage error: exit 2, a reason on stderr, no event and no EPUB."""
    assert proc.returncode == 2, proc.stderr
    assert "error:" in proc.stderr
    assert proc.stdout == ""
    assert not list(folder.rglob("*.epub"))


@pytest.mark.ac("PWD-AC12")
def test_more_than_25_candidates_for_a_file_is_a_usage_error(tmp_path: Path) -> None:
    encrypted_copies(tmp_path, "a.pdf", "b.pdf")
    lines = "".join(f"guess{n}\n" for n in range(26))
    (tmp_path / "pw.txt").write_text(lines, encoding="utf-8")
    (tmp_path / "pw.txt").chmod(0o600)

    proc = run(["--json", "--password-file", "pw.txt", "a.pdf", "b.pdf"], tmp_path)

    assert_nothing_ran(proc, tmp_path)
    assert "cap of 25" in proc.stderr
    assert "guess" not in proc.stderr


@pytest.mark.ac("PWD-AC13")
@pytest.mark.parametrize(
    ("flag", "name", "content"),
    [
        ("--password-map", "map.toml", '"book.pdf" = "unterminated\n'),
        ("--password-map", "map.toml", '"book.pdf" = 42\n'),
        ("--password-file", "missing.txt", None),
    ],
    ids=["map-not-toml", "map-value-42", "file-missing"],
)
def test_an_invalid_password_source_is_a_usage_error(
    tmp_path: Path, book: Path, flag: str, name: str, content: str | None
) -> None:
    if content is not None:
        (tmp_path / name).write_text(content, encoding="utf-8")

    proc = run(["--json", flag, name, "book.pdf"], tmp_path)

    assert_nothing_ran(proc, tmp_path)
    assert name in proc.stderr


@pytest.mark.ac("PWD-AC14")
@pytest.mark.parametrize(
    ("flag", "name", "content"),
    [
        ("--password-file", "pw.txt", f"{PASSWORD}\n"),
        ("--password-map", "map.toml", f'"book.pdf" = "{PASSWORD}"\n'),
    ],
    ids=["file", "map"],
)
def test_a_password_source_others_can_read_triggers_a_chmod_warning(
    tmp_path: Path, book: Path, flag: str, name: str, content: str
) -> None:
    source = tmp_path / name
    source.write_text(content, encoding="utf-8")
    source.chmod(0o644)

    proc = run(["--json", flag, name, "book.pdf"], tmp_path)

    assert proc.returncode == 0, proc.stderr
    [finished] = [e for e in events_of(proc.stdout) if e["type"] == "conversion_finished"]
    assert finished["outcome"] == "converted"
    [warning] = [line for line in proc.stderr.splitlines() if "chmod 600" in line]
    assert name in warning
    assert warning.startswith("WARNING:")

    source.chmod(0o600)
    proc = run(["--json", "--overwrite", flag, name, "book.pdf"], tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "chmod" not in proc.stderr


@pytest.mark.ac("PWD-AC19")
def test_the_canary_password_appears_in_no_output_while_its_label_does(tmp_path: Path) -> None:
    # The map's glob gives the canary to both files: it opens the AES-256 fixture and is
    # wrong for the RC4 one.
    shutil.copyfile(AES256, tmp_path / "a.pdf")
    shutil.copyfile(FIXTURES / "encrypted" / "rc4-128-user.pdf", tmp_path / "b.pdf")
    password_map = tmp_path / "map.toml"
    password_map.write_text(f'"*.pdf" = "{PASSWORD}"\n', encoding="utf-8")
    password_map.chmod(0o600)

    proc = run(
        ["--debug", "--json", "--report", "r.json", "--password-map", "map.toml", "a.pdf", "b.pdf"],
        tmp_path,
    )

    assert proc.returncode == 1, proc.stderr
    finished = [e for e in events_of(proc.stdout) if e["type"] == "conversion_finished"]
    assert [(e["outcome"], e["password_source"]) for e in finished] == [
        ("converted", 'map:"*.pdf"'),
        ("failed", None),
    ]
    assert "DEBUG: " in proc.stderr
    report = (tmp_path / "r.json").read_text(encoding="utf-8")
    assert 'map:\\"*.pdf\\"' in report
    for output in (proc.stdout, proc.stderr, report):
        assert PASSWORD not in output


def snapshot(*folders: Path) -> set[Path]:
    return {path for folder in folders for path in folder.rglob("*") if path.is_file()}


@pytest.mark.ac("PWD-AC22")
def test_no_file_written_during_a_run_holds_the_password_or_its_label(tmp_path: Path) -> None:
    out, home, temp = tmp_path / "out", tmp_path / "home", tmp_path / "tmp"
    for folder in (out, home, temp):
        folder.mkdir()
    shutil.copyfile(AES256, out / "book.pdf")
    (out / "map.toml").write_text(f'"book.pdf" = "{PASSWORD}"\n', encoding="utf-8")
    (out / "map.toml").chmod(0o600)
    before = snapshot(out, home, temp)
    # The fixture's /P permission flags, as an unsigned and a signed 32-bit number.
    encrypt = PdfReader(AES256).trailer["/Encrypt"].get_object()
    assert isinstance(encrypt, DictionaryObject)
    permissions = encrypt["/P"]
    assert isinstance(permissions, int)
    flags = permissions & 0xFFFFFFFF
    flag_values = {str(flags), str(flags - (1 << 32))}

    proc = run(
        ["--debug", "--password-map", "map.toml", "book.pdf"],
        out,
        extra_env={"HOME": str(home), "TMPDIR": str(temp), "XDG_CACHE_HOME": str(home / ".cache")},
    )

    assert proc.returncode == 0, proc.stderr
    epub = out / "book.epub"
    assert snapshot(out, home, temp) - before == {epub}
    with zipfile.ZipFile(epub) as archive:
        assert "META-INF/encryption.xml" not in archive.namelist()
        assert not any(info.flag_bits & 0x1 for info in archive.infolist())  # not encrypted
    text = epub_text(epub)
    assert "<p" in text, "the EPUB has no text to search"
    for secret in (PASSWORD, 'map:"book.pdf"', "map:&quot;book.pdf&quot;"):
        assert secret not in text
    for value in flag_values:
        assert not re.search(rf"(?<![\w-]){re.escape(value)}(?!\d)", text), value


# The owner-only restricted fixture with /O and /U zero-padded to 127 bytes, as qpdf
# writes smoke entry S11 (#87); its owner password, from tests/fixtures/fixturegen.
OWNER_PADDED = FIXTURES / "encrypted" / "owner-only-padded.pdf"
OWNER_PADDED_OWNER = "padded-owner"


@pytest.mark.ac("PWD-AC8")
def test_owner_password_opens_an_owner_only_file_with_padded_hash_strings(
    tmp_path: Path,
) -> None:
    # As scripts/smoke.py runs it: a folder of inputs, a password map keyed by path and
    # an output folder.
    (tmp_path / "inputs").mkdir()
    shutil.copyfile(OWNER_PADDED, tmp_path / "inputs" / "book.pdf")
    password_map = tmp_path / "passwords.toml"
    password_map.write_text(f'"inputs/book.pdf" = "{OWNER_PADDED_OWNER}"\n', encoding="utf-8")
    password_map.chmod(0o600)

    proc = run(
        ["--json", "--password-map", str(password_map), "-o", "epub", "inputs"],
        tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    [finished] = [e for e in events_of(proc.stdout) if e["type"] == "conversion_finished"]
    assert finished["outcome"] == "converted", finished["issues"]
    assert [(i["code"], i["severity"]) for i in finished["issues"]] == [
        ("owner_password_used", "info")
    ]
    assert finished["password_source"] == 'map:"inputs/book.pdf"'
    # The text comes from the decrypted file (the two-page book's first sentence).
    assert "The ferry left the harbour before dawn" in epub_text(tmp_path / "epub" / "book.epub")
