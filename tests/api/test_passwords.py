"""Opening password-protected PDFs with a supplied password (PWD §1, §2, §5, §7; API §4),
through ``plan_batch`` / ``run_batch`` in-process, with a scripted ``PasswordProvider``
or the core's ``SourcePasswordProvider``."""

import json
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import worker_hooks
from conftest import FIXTURES, RecordingSink

from pdf2epub import (
    BatchOptions,
    BatchReport,
    Candidate,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    Outcome,
    PasswordProvider,
    PasswordSources,
    Secret,
    SourcePasswordProvider,
    UsageError,
    plan_batch,
    run_batch,
)
from pdf2epub.events import encode_event

ENCRYPTED = FIXTURES / "encrypted"
AES256 = ENCRYPTED / "aes256-user.pdf"
AES128 = ENCRYPTED / "aes128-user.pdf"
RC4_128 = ENCRYPTED / "rc4-128-user.pdf"

# The fixtures' user passwords, as published in tests/fixtures/fixturegen/encrypted.py.
USER_PASSWORD = {AES256: "hunter2", AES128: "aes128-user", RC4_128: "rc4-user"}


class ScriptedProvider:
    """A provider that hands out fixed candidates and records each call (the
    ``PasswordProvider`` seam)."""

    prompt: Callable[[Path, int], Secret | None] | None = None

    def __init__(self, *candidates: tuple[str, str]) -> None:
        self._candidates = [Candidate(Secret(value), label) for value, label in candidates]
        self.calls: list[Path] = []

    def candidates(self, path: Path) -> list[Candidate]:
        self.calls.append(path)
        return list(self._candidates)


def run(
    sources: list[Path], passwords: PasswordProvider | None = None
) -> tuple[BatchReport, RecordingSink]:
    sink = RecordingSink()
    plan = plan_batch([InputSpec(source) for source in sources], DiscoveryOptions())
    report = run_batch(
        plan, BatchOptions(isolation="inprocess"), ConversionOptions(), sink, passwords=passwords
    )
    return report, sink


def copy(fixture: Path, folder: Path, name: str | None = None) -> Path:
    target = folder / (name or fixture.name)
    shutil.copyfile(fixture, target)
    return target


@pytest.mark.ac("PWD-AC1")
@pytest.mark.parametrize("fixture", [AES256, RC4_128, AES128], ids=lambda p: p.stem)
def test_the_right_password_from_the_environment_opens_the_file(
    tmp_path: Path, fixture: Path
) -> None:
    pdf = copy(fixture, tmp_path)

    report, sink = run([pdf], ScriptedProvider((USER_PASSWORD[fixture], "env")))

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert result.password_source == "env"
    assert (tmp_path / f"{fixture.stem}.epub").is_file()
    [finished] = sink.of_type("conversion_finished")
    assert finished["password_source"] == "env"


@pytest.mark.ac("PWD-AC2")
@pytest.mark.parametrize("provider", [None, ScriptedProvider()], ids=["no-provider", "empty"])
def test_no_password_sources_fail_missing_password(
    tmp_path: Path, provider: PasswordProvider | None
) -> None:
    pdf = copy(AES256, tmp_path)

    report, _ = run([pdf], provider)

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [(i.code, i.severity) for i in result.issues] == [("missing_password", "error")]
    assert result.issues[0].hint == "supply the password for this file"
    assert result.password_source is None
    assert not (tmp_path / "aes256-user.epub").exists()


def password_file(folder: Path, *lines: str) -> Path:
    path = folder / "passwords.txt"
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


@pytest.mark.ac("PWD-AC3")
def test_wrong_passwords_fail_naming_the_sources_tried_in_order(tmp_path: Path) -> None:
    pdf = copy(AES256, tmp_path)
    provider = SourcePasswordProvider(
        PasswordSources(values=[Secret("nope")], password_file=password_file(tmp_path, "alsonope"))
    )

    report, _ = run([pdf], provider)

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    [issue] = result.issues
    assert issue.code == "wrong_password"
    assert "cli #1" in issue.message
    assert issue.message.index("cli #1") < issue.message.index("file:line 1")
    assert "nope" not in issue.message.replace("cli #1", "")
    assert not (tmp_path / "aes256-user.epub").exists()


@pytest.mark.ac("PWD-AC11")
def test_a_repeated_password_is_tried_once_under_its_first_label(tmp_path: Path) -> None:
    provider = SourcePasswordProvider(
        PasswordSources(values=[Secret("same")], env_value=Secret("same"))
    )

    candidates = provider.candidates(tmp_path / "a.pdf")

    assert [(c.secret, c.source) for c in candidates] == [(Secret("same"), "cli #1")]


@pytest.mark.ac("PWD-AC15")
def test_source_provider_applies_trial_order_and_labels_in_the_core(tmp_path: Path) -> None:
    pdf = copy(AES256, tmp_path, "book.pdf")
    password_map = tmp_path / "passwords.toml"
    password_map.write_text('"book.pdf" = "m"\n', encoding="utf-8")
    provider = SourcePasswordProvider(
        PasswordSources(
            map_file=password_map,
            values=[Secret("v")],
            env_value=Secret("e"),
            password_file=password_file(tmp_path, "f"),
        )
    )

    report, _ = run([pdf], provider)

    [result] = report.conversions
    [issue] = result.issues
    assert issue.code == "wrong_password"
    assert (
        issue.hint == 'check the password; sources tried: map:"book.pdf", cli #1, env, file:line 1'
    )
    assert provider.prompt is None

    # The right password, last in the order, opens the file under its own label.
    provider = SourcePasswordProvider(
        PasswordSources(
            map_file=password_map,
            values=[Secret("v")],
            env_value=Secret("e"),
            password_file=password_file(tmp_path, "f", "", "hunter2"),
        )
    )
    report, _ = run([pdf], provider)
    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert result.password_source == "file:line 3"


@pytest.mark.ac("PWD-AC15")
def test_source_provider_cap_is_checked_in_the_preflight(tmp_path: Path) -> None:
    pdfs = [copy(AES256, tmp_path, "a.pdf"), copy(AES256, tmp_path, "b.pdf")]
    lines = [f"pw{n}" for n in range(26)]
    provider = SourcePasswordProvider(
        PasswordSources(password_file=password_file(tmp_path, *lines))
    )
    sink = RecordingSink()
    plan = plan_batch([InputSpec(pdf) for pdf in pdfs], DiscoveryOptions())

    with pytest.raises(UsageError, match="25") as raised:
        run_batch(
            plan, BatchOptions(isolation="inprocess"), ConversionOptions(), sink, passwords=provider
        )

    assert str(pdfs[0]) in str(raised.value)
    assert sink.events == []
    assert not list(tmp_path.glob("*.epub"))

    # 25 distinct candidates, plus repeats, are within the cap.
    provider = SourcePasswordProvider(
        PasswordSources(password_file=password_file(tmp_path, *lines[:25], *lines[:25]))
    )
    report, _ = run(pdfs, provider)
    assert [r.issues[0].code for r in report.conversions] == ["wrong_password"] * 2


@pytest.mark.ac("API-AC5")
def test_secret_prints_as_stars_and_refuses_json() -> None:
    secret = Secret("hunter2")

    assert str(secret) == "***"
    assert repr(secret) == "***"
    assert f"{secret}" == "***"
    assert repr([secret]) == "[***]"
    with pytest.raises(TypeError):
        json.dumps(secret)
    with pytest.raises(TypeError):
        encode_event({"type": "issue", "password": secret})
    assert secret.reveal() == "hunter2"


@pytest.mark.ac("API-AC5")
def test_the_password_appears_in_no_event_report_or_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # hunter2 opens the AES-256 fixture and is wrong for the RC4 one.
    pdfs = [copy(AES256, tmp_path), copy(RC4_128, tmp_path)]
    caplog.set_level(logging.DEBUG)

    report, sink = run(pdfs, ScriptedProvider(("hunter2", "cli #1")))

    finished = sink.of_type("conversion_finished")
    assert [e["password_source"] for e in finished] == ["cli #1", None]
    assert [r.outcome for r in report.conversions] == [Outcome.CONVERTED, Outcome.FAILED]
    assert report.conversions[1].issues[0].code == "wrong_password"
    wire = "".join(encode_event(event) for event in sink.events)
    assert "cli #1" in wire
    assert "hunter2" not in wire
    assert "hunter2" not in json.dumps(report.to_dict())
    assert caplog.records, "nothing was logged at DEBUG"
    for record in caplog.records:
        assert "hunter2" not in record.getMessage()
        assert "hunter2" not in caplog.text


@pytest.mark.ac("PWD-AC15")
def test_password_file_lines_end_only_at_line_breaks(tmp_path: Path) -> None:
    path = tmp_path / "passwords.txt"
    path.write_bytes(b"first\r\nsec\x0cond\n\n  \nthird")

    provider = SourcePasswordProvider(PasswordSources(password_file=path))

    candidates = provider.candidates(tmp_path / "a.pdf")
    assert [(c.secret, c.source) for c in candidates] == [
        (Secret("first"), "file:line 1"),
        (Secret("sec\x0cond"), "file:line 2"),
        (Secret("  "), "file:line 4"),
        (Secret("third"), "file:line 5"),
    ]


@pytest.mark.ac("PWD-AC15")
def test_unreadable_password_sources_are_usage_errors(tmp_path: Path) -> None:
    bad_map = tmp_path / "map.toml"
    bad_map.write_bytes(b'"a.pdf" = "\xff"\n')
    bad_file = tmp_path / "passwords.txt"
    bad_file.write_bytes(b"\xff\n")

    with pytest.raises(UsageError, match=r"map\.toml"):
        SourcePasswordProvider(PasswordSources(map_file=bad_map))
    with pytest.raises(UsageError, match=r"passwords\.txt"):
        SourcePasswordProvider(PasswordSources(password_file=bad_file))


def restricted_copy(target: Path, user: str, owner: str) -> Path:
    """The two-page book encrypted with copy/extract forbidden (``/P`` bit 5 clear).
    #32 brings the committed restricted fixtures; this stand-in is built per test."""
    from pypdf import PdfWriter
    from pypdf.constants import UserAccessPermissions

    writer = PdfWriter(clone_from=FIXTURES / "born-digital" / "two-pages.pdf")
    permissions = UserAccessPermissions.all() & ~UserAccessPermissions.EXTRACT
    writer.encrypt(user, owner, permissions_flag=permissions, algorithm="AES-256")
    with target.open("wb") as file:
        writer.write(file)
    return target


@pytest.mark.parametrize(
    ("user", "values"),
    [("u", ["u"]), ("", []), ("", ["wrong"])],
    ids=["user-password", "owner-only", "owner-only-wrong"],
)
def test_copy_restricted_file_without_its_owner_password_fails_restricted(
    tmp_path: Path, user: str, values: list[str]
) -> None:
    pdf = restricted_copy(tmp_path / "locked.pdf", user, "o")

    report, _ = run(
        [pdf], SourcePasswordProvider(PasswordSources(values=[Secret(v) for v in values]))
    )

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [(i.code, i.hint) for i in result.issues] == [
        ("restricted", "supply the owner password")
    ]
    assert not (tmp_path / "locked.epub").exists()


@pytest.mark.parametrize(
    ("values", "label"), [(["u", "o"], "cli #2"), (["o"], "cli #1")], ids=["after-user", "alone"]
)
def test_owner_password_lifts_the_restriction(
    tmp_path: Path, values: list[str], label: str
) -> None:
    pdf = restricted_copy(tmp_path / "locked.pdf", "u", "o")
    provider = SourcePasswordProvider(PasswordSources(values=[Secret(v) for v in values]))

    report, _ = run([pdf], provider)

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert [(i.code, i.severity) for i in result.issues] == [("owner_password_used", "info")]
    assert result.issues[0].message == f"converted using owner password from {label}"
    assert result.password_source == label
    assert (tmp_path / "locked.epub").is_file()


@pytest.mark.ac("PWD-AC10")
def test_candidates_follow_the_trial_order_exact_map_key_before_globs(tmp_path: Path) -> None:
    password_map = tmp_path / "passwords.toml"
    password_map.write_text('"*.pdf" = "g"\n"a.pdf" = "x"\n', encoding="utf-8")
    calls: list[tuple[Path, int]] = []

    def prompt(path: Path, attempt: int) -> Secret | None:
        calls.append((path, attempt))
        return None

    provider = SourcePasswordProvider(
        PasswordSources(
            map_file=password_map,
            values=[Secret("v")],
            env_value=Secret("e"),
            password_file=password_file(tmp_path, "f1", "f2"),
            prompt=prompt,
        )
    )

    candidates = provider.candidates(tmp_path / "a.pdf")

    assert [c.source for c in candidates] == [
        'map:"a.pdf"',
        'map:"*.pdf"',
        "cli #1",
        "env",
        "file:line 1",
        "file:line 2",
    ]
    assert [c.secret for c in candidates] == [Secret(v) for v in ("x", "g", "v", "e", "f1", "f2")]
    # The prompt comes after every candidate: listing them never prompts.
    assert provider.prompt is prompt
    assert calls == []


def use_hooks(monkeypatch: pytest.MonkeyPatch, rules: worker_hooks.Rules) -> None:
    """Install ``rules`` in every worker this test starts."""
    for name, value in worker_hooks.environment(rules).items():
        monkeypatch.setenv(name, value)


def run_in_workers(sources: list[Path], passwords: PasswordProvider) -> BatchReport:
    plan = plan_batch([InputSpec(source) for source in sources], DiscoveryOptions())
    return run_batch(
        plan,
        BatchOptions(isolation="subprocess"),
        ConversionOptions(),
        RecordingSink(),
        passwords=passwords,
    )


@pytest.mark.ac("BAT-AC15")
def test_the_password_reaches_the_worker_over_its_pipe_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = copy(AES256, tmp_path)
    record = tmp_path / "worker.json"
    use_hooks(monkeypatch, {pdf.name: {"action": "record", "path": str(record)}})
    monkeypatch.setenv("PDF2EPUB_PASSWORD", "hunter2")
    provider = SourcePasswordProvider(PasswordSources(env_value=Secret("hunter2")))

    report = run_in_workers([pdf], provider)

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert result.password_source == "env"
    started = json.loads(record.read_text(encoding="utf-8"))
    assert started["argv"], "the hook recorded no argv"
    assert not any("hunter2" in arg for arg in started["argv"])
    assert "PDF2EPUB_PASSWORD" not in started["env"]
    assert not any("hunter2" in value for value in started["env"].values())


@pytest.mark.ac("PWD-AC20")
@pytest.mark.parametrize("action", ["abort", "raise"])
def test_a_worker_crash_holding_the_password_leaks_it_nowhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    action: str,
) -> None:
    pdf = copy(AES256, tmp_path)
    use_hooks(monkeypatch, {pdf.name: {"action": action}})
    caplog.set_level(logging.DEBUG)

    report = run_in_workers([pdf], ScriptedProvider(("hunter2", "cli #1")))

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [i.code for i in result.issues] == ["internal_error"]
    captured = capfd.readouterr()
    for text in (
        result.issues[0].message,
        captured.out,
        captured.err,
        caplog.text,
        json.dumps(report.to_dict()),
    ):
        assert "hunter2" not in text
