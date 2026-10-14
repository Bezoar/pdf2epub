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
    restricted = restricted_copy(tmp_path / "locked.pdf", "u", "o")
    drm = copy(VENDOR_HANDLERS[0], tmp_path)
    unsupported = copy(UNKNOWN_CRYPT_FILTER, tmp_path)

    class PerFile:
        prompt: Callable[[Path, int], Secret | None] | None = None

        def candidates(self, path: Path) -> list[Candidate]:
            if path == missing:
                return []
            if path == restricted:
                return [Candidate(Secret("u"), "cli #1")]
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
