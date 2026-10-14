"""Opening password-protected PDFs with a supplied password (PWD §1, §2, §5, §7; API §4),
through ``plan_batch`` / ``run_batch`` in-process, with a scripted ``PasswordProvider``
or the core's ``SourcePasswordProvider``."""

import json
import logging
import shutil
import zipfile
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
@pytest.mark.ac("API-AC17")
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


# --- Permission restrictions (PWD-R9 to PWD-R11) ------------------------------------------

# The permission fixtures and their passwords, as published in
# tests/fixtures/fixturegen/encrypted.py. Copy/extract is forbidden in both restricted ones.
OWNER_RESTRICTED = ENCRYPTED / "owner-only-restricted.pdf"
OWNER_RESTRICTED_OWNER = "restricted-owner"
OWNER_ALL = ENCRYPTED / "owner-only-all-permissions.pdf"
USER_OWNER_RESTRICTED = ENCRYPTED / "user-owner-restricted.pdf"
USER, OWNER = "locked-user", "locked-owner"
RESTRICTED = [("restricted", "supply the owner password")]


def values(*passwords: str) -> SourcePasswordProvider:
    return SourcePasswordProvider(PasswordSources(values=[Secret(v) for v in passwords]))


@pytest.mark.ac("PWD-AC7")
@pytest.mark.parametrize("provider", [None, values()], ids=["no-provider", "no-candidates"])
def test_owner_only_restricted_file_without_candidates_fails_restricted(
    tmp_path: Path, provider: PasswordProvider | None
) -> None:
    pdf = copy(OWNER_RESTRICTED, tmp_path)

    report, _ = run([pdf], provider)

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [(i.code, i.hint) for i in result.issues] == RESTRICTED
    assert result.output is None
    assert list(tmp_path.glob("*.epub")) == []


def test_owner_only_file_with_every_permission_converts_without_a_password(
    tmp_path: Path,
) -> None:
    # PWD-R10 applies only when copying is forbidden: the empty password is enough here.
    pdf = copy(OWNER_ALL, tmp_path)

    report, _ = run([pdf], values())

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert result.issues == []
    assert result.password_source is None
    assert (tmp_path / "owner-only-all-permissions.epub").is_file()


@pytest.mark.ac("PWD-AC8")
def test_owner_password_from_the_map_lifts_the_restriction(tmp_path: Path) -> None:
    pdf = copy(OWNER_RESTRICTED, tmp_path)
    password_map = tmp_path / "passwords.toml"
    password_map.write_text(
        f'"owner-only-restricted.pdf" = ["wrong", "{OWNER_RESTRICTED_OWNER}"]\n',
        encoding="utf-8",
    )
    label = 'map:"owner-only-restricted.pdf"'

    report, _ = run([pdf], SourcePasswordProvider(PasswordSources(map_file=password_map)))

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert [(i.code, i.severity, i.message) for i in result.issues] == [
        ("owner_password_used", "info", f"converted using owner password from {label}")
    ]
    assert result.password_source == label
    assert (tmp_path / "owner-only-restricted.epub").is_file()


@pytest.mark.ac("PWD-AC9")
def test_user_password_alone_leaves_the_file_restricted(tmp_path: Path) -> None:
    pdf = copy(USER_OWNER_RESTRICTED, tmp_path)

    report, _ = run([pdf], values(USER))

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [(i.code, i.hint) for i in result.issues] == RESTRICTED
    assert list(tmp_path.glob("*.epub")) == []


@pytest.mark.ac("PWD-AC9")
def test_owner_password_after_the_user_password_converts(tmp_path: Path) -> None:
    pdf = copy(USER_OWNER_RESTRICTED, tmp_path)

    report, _ = run([pdf], values(USER, OWNER))

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert [(i.code, i.severity, i.message) for i in result.issues] == [
        ("owner_password_used", "info", "converted using owner password from cli #2")
    ]
    assert result.password_source == "cli #2"
    assert (tmp_path / "user-owner-restricted.epub").is_file()


@pytest.mark.parametrize(
    ("fixture", "passwords"),
    [(USER_OWNER_RESTRICTED, ["wrong", USER]), (OWNER_RESTRICTED, ["wrong"])],
    ids=["user-password", "owner-only-wrong"],
)
def test_copy_restricted_file_without_its_owner_password_fails_restricted(
    tmp_path: Path, fixture: Path, passwords: list[str]
) -> None:
    pdf = copy(fixture, tmp_path)

    report, _ = run([pdf], values(*passwords))

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [(i.code, i.hint) for i in result.issues] == RESTRICTED
    assert list(tmp_path.glob("*.epub")) == []


@pytest.mark.parametrize(
    ("passwords", "label"), [([OWNER, USER], "cli #1"), ([OWNER], "cli #1")], ids=["first", "alone"]
)
def test_owner_password_alone_opens_and_lifts_the_restriction(
    tmp_path: Path, passwords: list[str], label: str
) -> None:
    pdf = copy(USER_OWNER_RESTRICTED, tmp_path)

    report, _ = run([pdf], values(*passwords))

    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert [(i.code, i.message) for i in result.issues] == [
        ("owner_password_used", f"converted using owner password from {label}")
    ]
    assert result.password_source == label


# --- Refused before any password is tried (PWD-R2 to PWD-R4) -----------------------------

DRM_HINT = "open it in the vendor's reader; pdf2epub will not bypass DRM"
UNSUPPORTED_HINT = "this PDF's encryption is not supported"
VENDOR_HANDLERS = [
    ENCRYPTED / f"{name}.pdf" for name in ("ebx-handler", "adobe-pubsec", "fopn-foweb")
]
UNKNOWN_CRYPT_FILTER = ENCRYPTED / "unknown-crypt-filter.pdf"
LCP = FIXTURES / "drm-wrappers" / "sample.lcpdf"
ACSM = FIXTURES / "drm-wrappers" / "sample.acsm"


@pytest.mark.ac("PWD-AC4")
@pytest.mark.parametrize("fixture", VENDOR_HANDLERS, ids=lambda p: p.stem)
def test_a_vendor_security_handler_is_refused_before_any_password(
    tmp_path: Path, fixture: Path
) -> None:
    pdf = copy(fixture, tmp_path)
    provider = ScriptedProvider(("hunter2", "env"))

    report, sink = run([pdf], provider)

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [(i.code, i.severity, i.hint) for i in result.issues] == [
        ("drm_protected", "error", DRM_HINT)
    ]
    assert provider.calls == []
    assert result.password_source is None
    assert not (tmp_path / f"{fixture.stem}.epub").exists()
    assert [e["issue"]["code"] for e in sink.of_type("issue")] == ["drm_protected"]


@pytest.mark.ac("PWD-AC5")
@pytest.mark.parametrize("fixture", [LCP, ACSM], ids=["lcp", "acsm"])
@pytest.mark.parametrize("from_list", [False, True], ids=["named", "listed"])
def test_an_explicitly_named_drm_wrapper_is_refused_drm_protected(
    tmp_path: Path, fixture: Path, from_list: bool
) -> None:
    wrapper = copy(fixture, tmp_path)
    provider = ScriptedProvider(("hunter2", "env"))

    plan = plan_batch([InputSpec(wrapper, from_list=from_list)], DiscoveryOptions())
    report = run_batch(
        plan,
        BatchOptions(isolation="inprocess"),
        ConversionOptions(),
        RecordingSink(),
        passwords=provider,
    )

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [(i.code, i.hint) for i in result.issues] == [("drm_protected", DRM_HINT)]
    assert provider.calls == []
    assert not (tmp_path / f"{fixture.stem}.epub").exists()


def test_a_wrapper_found_by_a_folder_scan_is_still_not_a_pdf(tmp_path: Path) -> None:
    # BAT-R4: only an explicitly named wrapper is passed on to be refused drm_protected.
    copy(LCP, tmp_path, "renamed.pdf")

    report, _ = run([tmp_path])

    [result] = report.conversions
    assert [i.code for i in result.issues] == ["not_a_pdf"]


def test_a_scanned_wrapper_holding_pdf_magic_is_still_not_a_pdf(tmp_path: Path) -> None:
    # A wrapper is never a PDF, even with %PDF- in its first 1024 bytes (BAT-R4).
    with zipfile.ZipFile(tmp_path / "book.pdf", "w") as archive:
        archive.writestr("a.pdf", b"%PDF-1.7\n")
        archive.writestr("META-INF/license.lcpl", b"{}")

    report, _ = run([tmp_path])

    [result] = report.conversions
    assert [i.code for i in result.issues] == ["not_a_pdf"]


@pytest.mark.parametrize(
    "xml",
    [
        b'<?xml version="1.0"?><other xmlns:a="http://ns.adobe.com/adept">'
        b"<a:fulfillmentToken/></other>",
        b'<fulfillmentToken xmlns="http://example.invalid/not-adept"/>',
        b'<?xml version="1.0"?><!DOCTYPE fulfillmentToken [<!ENTITY e "x">]>'
        b'<fulfillmentToken xmlns="http://ns.adobe.com/adept" a="&e;"/>',
    ],
    ids=["nested-token", "other-namespace", "with-dtd"],
)
def test_xml_that_is_not_an_adept_token_is_not_a_pdf(tmp_path: Path, xml: bytes) -> None:
    named = tmp_path / "token.acsm"
    named.write_bytes(xml)

    report, _ = run([named])

    [result] = report.conversions
    assert [i.code for i in result.issues] == ["not_a_pdf"]


TOKEN = (FIXTURES / "drm-wrappers" / "sample.acsm").read_bytes()
XML_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>\n'


@pytest.mark.ac("PWD-AC5")
@pytest.mark.parametrize(
    "prolog",
    [b"<!-- not a <!DOCTYPE here, nor an <!ENTITY -->\n", b"<!--" + b" " * 8192 + b"-->\n"],
    ids=["dtd-words-in-a-comment", "long-prolog"],
)
def test_an_adept_token_after_any_prolog_is_refused_drm_protected(
    tmp_path: Path, prolog: bytes
) -> None:
    token = tmp_path / "token.acsm"
    token.write_bytes(TOKEN.replace(XML_DECLARATION, XML_DECLARATION + prolog, 1))

    report, _ = run([token])

    [result] = report.conversions
    assert [i.code for i in result.issues] == ["drm_protected"]


@pytest.mark.ac("PWD-AC5")
@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_a_utf16_adept_token_is_refused_drm_protected(tmp_path: Path, encoding: str) -> None:
    token = tmp_path / "token.acsm"
    text = TOKEN.decode("utf-8").replace('encoding="UTF-8"', 'encoding="UTF-16"')
    token.write_bytes("﻿".encode(encoding) + text.encode(encoding))

    report, _ = run([token])

    [result] = report.conversions
    assert [i.code for i in result.issues] == ["drm_protected"]


def test_a_zip_without_an_lcp_licence_is_not_a_pdf(tmp_path: Path) -> None:
    archive = tmp_path / "book.lcpdf"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr("META-INF/container.xml", "<container/>")

    report, _ = run([archive])

    [result] = report.conversions
    assert [i.code for i in result.issues] == ["not_a_pdf"]


@pytest.mark.ac("PWD-AC6")
def test_an_unknown_crypt_filter_fails_unsupported_encryption_untried(tmp_path: Path) -> None:
    pdf = copy(UNKNOWN_CRYPT_FILTER, tmp_path)
    provider = ScriptedProvider(("hunter2", "env"))

    report, _ = run([pdf], provider)

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [(i.code, i.severity, i.hint) for i in result.issues] == [
        ("unsupported_encryption", "error", UNSUPPORTED_HINT)
    ]
    assert provider.calls == []
    assert not (tmp_path / "unknown-crypt-filter.epub").exists()


@pytest.mark.ac("PWD-AC6")
def test_a_crypt_filter_name_missing_from_cf_fails_unsupported_untried(tmp_path: Path) -> None:
    # The fixture with /StmF and /StrF naming a filter /CF doesn't hold (same length, so
    # the cross-reference offsets still hold).
    data = UNKNOWN_CRYPT_FILTER.read_bytes()
    assert data.count(b"/StmF /StdCF /StrF /StdCF") == 1
    pdf = tmp_path / "missing-crypt-filter.pdf"
    pdf.write_bytes(data.replace(b"/StmF /StdCF /StrF /StdCF", b"/StmF /NoXCF /StrF /NoXCF"))
    provider = ScriptedProvider(("hunter2", "env"))

    report, _ = run([pdf], provider)

    [result] = report.conversions
    assert [(i.code, i.hint) for i in result.issues] == [
        ("unsupported_encryption", UNSUPPORTED_HINT)
    ]
    assert provider.calls == []


@pytest.mark.ac("PWD-AC23")
def test_each_access_issue_carries_its_hint(tmp_path: Path) -> None:
    # One batch, one file per access issue. The restricted file gets its user password,
    # the others two wrong ones, so no file gets past its access check.
    missing = copy(AES128, tmp_path)
    wrong = copy(AES256, tmp_path)
    restricted = copy(USER_OWNER_RESTRICTED, tmp_path, "locked.pdf")
    drm = copy(VENDOR_HANDLERS[0], tmp_path)
    unsupported = copy(UNKNOWN_CRYPT_FILTER, tmp_path)

    class PerFile:
        prompt: Callable[[Path, int], Secret | None] | None = None

        def candidates(self, path: Path) -> list[Candidate]:
            if path == missing:
                return []
            if path == restricted:
                return [Candidate(Secret(USER), "cli #1")]
            return [Candidate(Secret("nope"), "cli #1"), Candidate(Secret("nah"), "env")]

    report, _ = run([missing, wrong, restricted, drm, unsupported], PerFile())

    hints = {Path(r.source).name: [(i.code, i.hint) for i in r.issues] for r in report.conversions}
    assert hints == {
        "aes128-user.pdf": [("missing_password", "supply the password for this file")],
        "aes256-user.pdf": [("wrong_password", "check the password; sources tried: cli #1, env")],
        "locked.pdf": [("restricted", "supply the owner password")],
        "ebx-handler.pdf": [("drm_protected", DRM_HINT)],
        "unknown-crypt-filter.pdf": [("unsupported_encryption", UNSUPPORTED_HINT)],
    }


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


@pytest.mark.ac("MAIN-AC-D")
def test_a_mixed_batch_converts_only_the_good_file_and_reports_each_one(
    tmp_path: Path,
) -> None:
    corrupt = copy(FIXTURES / "damaged" / "truncated.pdf", tmp_path)
    no_password = copy(AES256, tmp_path)
    drm = copy(ENCRYPTED / "fopn-foweb.pdf", tmp_path)
    restricted = copy(OWNER_RESTRICTED, tmp_path)
    good = copy(FIXTURES / "born-digital" / "two-pages.pdf", tmp_path)

    report = run_in_workers(
        [corrupt, no_password, drm, restricted, good], SourcePasswordProvider(PasswordSources())
    )

    results = {Path(r.source).name: r for r in report.conversions}
    assert {name: (r.outcome, [i.code for i in r.issues]) for name, r in results.items()} == {
        "truncated.pdf": (Outcome.FAILED, ["corrupt_pdf"]),
        "aes256-user.pdf": (Outcome.FAILED, ["missing_password"]),
        "fopn-foweb.pdf": (Outcome.FAILED, ["drm_protected"]),
        "owner-only-restricted.pdf": (Outcome.FAILED, ["restricted"]),
        "two-pages.pdf": (Outcome.CONVERTED, []),
    }
    assert sorted(p.name for p in tmp_path.glob("*.epub")) == ["two-pages.epub"]
    assert not report.interrupted
    assert report.exit_code == 1
