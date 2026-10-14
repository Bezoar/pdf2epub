"""Password prompts (PWD §6): the prompt's three attempts, deferral of prompted
conversions to the end of a batch, and ``password_required`` when no prompt is possible,
through ``plan_batch`` / ``run_batch`` with a scripted ``PasswordProvider``."""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest
from conftest import FIXTURES, PUBLIC_DOMAIN_SAMPLE, RecordingSink
from test_passwords import restricted_copy

from pdf2epub import (
    BatchOptions,
    BatchReport,
    Candidate,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    Outcome,
    PasswordProvider,
    Secret,
    plan_batch,
    run_batch,
)

AES256 = FIXTURES / "encrypted" / "aes256-user.pdf"
PASSWORD = "hunter2"  # the AES-256 fixture's user password


class PromptingProvider:
    """A provider with fixed candidates and a scripted prompt that records each call
    (the ``PasswordProvider`` seam)."""

    def __init__(
        self,
        answers: list[str | None] | None,
        *candidates: tuple[str, str],
        on_prompt: Callable[[], None] | None = None,
    ) -> None:
        self._candidates = [Candidate(Secret(value), label) for value, label in candidates]
        self._answers = list(answers or [])
        self._on_prompt = on_prompt
        self.calls: list[tuple[str, int]] = []
        self.prompt: Callable[[Path, int], Secret | None] | None = (
            self._prompt if answers is not None else None
        )

    def candidates(self, path: Path) -> list[Candidate]:
        return list(self._candidates)

    def _prompt(self, path: Path, attempt: int) -> Secret | None:
        self.calls.append((path.name, attempt))
        if self._on_prompt is not None:
            self._on_prompt()
        answer = self._answers.pop(0)
        return None if answer is None else Secret(answer)


def run(
    sources: list[Path],
    passwords: PasswordProvider | None,
    sink: RecordingSink | None = None,
    isolation: Literal["subprocess", "inprocess"] = "inprocess",
) -> tuple[BatchReport, RecordingSink]:
    sink = sink if sink is not None else RecordingSink()
    plan = plan_batch([InputSpec(source) for source in sources], DiscoveryOptions())
    report = run_batch(
        plan, BatchOptions(isolation=isolation), ConversionOptions(), sink, passwords=passwords
    )
    return report, sink


def copy(fixture: Path, target: Path) -> Path:
    shutil.copyfile(fixture, target)
    return target


@pytest.mark.ac("PWD-AC16")
def test_three_wrong_prompt_answers_fail_wrong_password_naming_the_prompt(
    tmp_path: Path,
) -> None:
    pdf = copy(AES256, tmp_path / "enc.pdf")
    provider = PromptingProvider(["no1", "no2", "no3"])

    report, _ = run([pdf], provider)

    assert provider.calls == [("enc.pdf", 1), ("enc.pdf", 2), ("enc.pdf", 3)]
    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    [issue] = result.issues
    assert issue.code == "wrong_password"
    assert "prompt" in issue.message
    assert issue.hint == "check the password; sources tried: prompt"
    assert not (tmp_path / "enc.epub").exists()


@pytest.mark.ac("PWD-AC16")
def test_skipping_the_first_prompt_with_nothing_tried_fails_missing_password(
    tmp_path: Path,
) -> None:
    pdf = copy(AES256, tmp_path / "enc.pdf")
    provider = PromptingProvider([None])

    report, _ = run([pdf], provider)

    assert provider.calls == [("enc.pdf", 1)]
    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [i.code for i in result.issues] == ["missing_password"]


@pytest.mark.ac("PWD-AC16")
def test_skipping_the_owner_password_prompt_fails_restricted(tmp_path: Path) -> None:
    pdf = restricted_copy(tmp_path / "locked.pdf", "", "o")
    provider = PromptingProvider([None])

    report, _ = run([pdf], provider)

    assert provider.calls == [("locked.pdf", 1)]
    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [(i.code, i.hint) for i in result.issues] == [
        ("restricted", "supply the owner password")
    ]
    assert not (tmp_path / "locked.epub").exists()


def test_skipping_the_prompt_after_supplied_candidates_failed_fails_wrong_password(
    tmp_path: Path,
) -> None:
    """PWD-R20 (owner-accepted open point): the supplied candidates were tried."""
    pdf = copy(AES256, tmp_path / "enc.pdf")
    provider = PromptingProvider([None], ("nope", "cli #1"))

    report, _ = run([pdf], provider)

    [result] = report.conversions
    [issue] = result.issues
    assert issue.code == "wrong_password"
    assert issue.hint == "check the password; sources tried: cli #1"


@pytest.mark.parametrize("isolation", ["inprocess", "subprocess"])
def test_a_right_answer_on_the_second_attempt_converts_from_the_prompt(
    tmp_path: Path, isolation: Literal["subprocess", "inprocess"]
) -> None:
    pdf = copy(AES256, tmp_path / "enc.pdf")
    provider = PromptingProvider(["wrong", PASSWORD], ("nope", "cli #1"))

    report, sink = run([pdf], provider, isolation=isolation)

    assert provider.calls == [("enc.pdf", 1), ("enc.pdf", 2)]
    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert result.password_source == "prompt"
    assert (tmp_path / "enc.epub").is_file()
    assert sink.of_type("password_required") == []


def test_the_owner_password_from_the_prompt_lifts_the_restriction(tmp_path: Path) -> None:
    pdf = restricted_copy(tmp_path / "locked.pdf", "u", "o")
    provider = PromptingProvider(["u", "o"])

    report, _ = run([pdf], provider)

    assert provider.calls == [("locked.pdf", 1), ("locked.pdf", 2)]
    [result] = report.conversions
    assert result.outcome is Outcome.CONVERTED, result.issues
    assert [i.message for i in result.issues] == ["converted using owner password from prompt"]
    assert result.password_source == "prompt"


@pytest.mark.ac("PWD-AC17")
def test_prompts_wait_until_every_conversion_needing_none_has_finished(
    tmp_path: Path,
) -> None:
    enc = copy(AES256, tmp_path / "enc.pdf")
    plain1 = copy(PUBLIC_DOMAIN_SAMPLE, tmp_path / "plain1.pdf")
    plain2 = copy(PUBLIC_DOMAIN_SAMPLE, tmp_path / "plain2.pdf")
    sink = RecordingSink()
    seen_at_prompt: list[list[dict[str, object]]] = []
    provider = PromptingProvider(
        [PASSWORD], on_prompt=lambda: seen_at_prompt.append(list(sink.events))
    )

    report, _ = run([enc, plain1, plain2], provider, sink)

    [before] = seen_at_prompt
    finished = [Path(str(e["source"])).name for e in before if e["type"] == "conversion_finished"]
    assert finished == ["plain1.pdf", "plain2.pdf"]
    [batch_finished] = sink.of_type("batch_finished")
    assert [Path(c["source"]).name for c in batch_finished["conversions"]] == [
        "enc.pdf",
        "plain1.pdf",
        "plain2.pdf",
    ]
    assert [c.outcome for c in report.conversions] == [Outcome.CONVERTED] * 3
    assert report.conversions[0].password_source == "prompt"


@pytest.mark.ac("PWD-AC18")
def test_without_a_prompt_password_required_names_the_sources_tried(tmp_path: Path) -> None:
    enc = copy(AES256, tmp_path / "enc.pdf")
    plain = copy(PUBLIC_DOMAIN_SAMPLE, tmp_path / "plain.pdf")
    provider = PromptingProvider(None, ("nope", "cli #1"))

    report, sink = run([enc, plain], provider)

    types = [(e["type"], e.get("id")) for e in sink.events]
    required = types.index(("password_required", 0))
    assert required < types.index(("conversion_finished", 0))
    [event] = sink.of_type("password_required")
    assert event["sources_tried"] == ["cli #1"]
    [enc_result, plain_result] = report.conversions
    assert enc_result.outcome is Outcome.FAILED
    assert [i.code for i in enc_result.issues] == ["wrong_password"]
    assert plain_result.outcome is Outcome.CONVERTED


@pytest.mark.parametrize(
    ("make", "provider", "code"),
    [
        (lambda p: copy(AES256, p), None, "missing_password"),
        (lambda p: restricted_copy(p, "", "o"), PromptingProvider(None), "restricted"),
    ],
    ids=["no-provider", "owner-only"],
)
def test_password_required_is_emitted_for_a_missing_or_owner_password(
    tmp_path: Path,
    make: Callable[[Path], Path],
    provider: PasswordProvider | None,
    code: str,
) -> None:
    """PWD-R22, including the owner-accepted open point: also when only the owner
    password is missing."""
    pdf = make(tmp_path / "book.pdf")

    report, sink = run([pdf], provider)

    [event] = sink.of_type("password_required")
    assert event["sources_tried"] == []
    [result] = report.conversions
    assert [i.code for i in result.issues] == [code]


def test_a_plain_or_opened_file_gets_no_password_required(tmp_path: Path) -> None:
    enc = copy(AES256, tmp_path / "enc.pdf")
    plain = copy(PUBLIC_DOMAIN_SAMPLE, tmp_path / "plain.pdf")

    report, sink = run([enc, plain], PromptingProvider(None, (PASSWORD, "env")))

    assert sink.of_type("password_required") == []
    assert [c.outcome for c in report.conversions] == [Outcome.CONVERTED] * 2
