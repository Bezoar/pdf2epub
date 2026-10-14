"""The cover option's usage error (RFL-R28) and the writer's built-in checks (EPUB-R16),
driven through ``plan_batch`` / ``run_batch`` in-process."""

import dataclasses
import shutil
from pathlib import Path
from typing import Any

import pytest
from conftest import NOVEL, RecordingSink

from pdf2epub import (
    BatchOptions,
    ConversionOptions,
    DiscoveryOptions,
    InputSpec,
    Outcome,
    UsageError,
    conversion,
    plan_batch,
    run_batch,
)
from pdf2epub.reflow.model import TocEntry


def novel_plan(folder: Path) -> Any:
    copy = folder / "novel.pdf"
    shutil.copyfile(NOVEL, copy)
    return plan_batch([InputSpec(copy)], DiscoveryOptions())


@pytest.mark.ac("RFL-AC19")
def test_a_cover_path_that_does_not_exist_is_a_usage_error(tmp_path: Path) -> None:
    plan = novel_plan(tmp_path)
    sink = RecordingSink()
    missing = tmp_path / "no-such-cover.png"

    with pytest.raises(UsageError, match=r"no-such-cover\.png"):
        run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(cover=missing), sink)
    assert sink.events == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["novel.pdf"]


def test_a_cover_file_that_is_not_an_image_is_a_usage_error(tmp_path: Path) -> None:
    plan = novel_plan(tmp_path)
    sink = RecordingSink()
    not_an_image = tmp_path / "cover.png"
    not_an_image.write_text("not a picture")

    with pytest.raises(UsageError, match=r"cover\.png"):
        run_batch(
            plan, BatchOptions(isolation="inprocess"), ConversionOptions(cover=not_an_image), sink
        )
    assert sink.events == []


@pytest.mark.ac("EPUB-AC11")
def test_a_broken_internal_reference_fails_the_writer_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build = conversion.build_document  # type: ignore[attr-defined]  # the module's own import, wrapped below

    def with_broken_toc(*args: Any, **kwargs: Any) -> Any:
        document, issues = build(*args, **kwargs)
        broken = TocEntry("Nowhere", chapter=0, anchor="no-such-anchor")
        return dataclasses.replace(document, toc=[*document.toc, broken]), issues

    monkeypatch.setattr(conversion, "build_document", with_broken_toc)
    plan = novel_plan(tmp_path)
    sink = RecordingSink()
    report = run_batch(plan, BatchOptions(isolation="inprocess"), ConversionOptions(), sink)

    [result] = report.conversions
    assert result.outcome is Outcome.FAILED
    assert [issue.code.value for issue in result.issues] == ["internal_error"]
    assert result.output is None
    # No EPUB and no temporary file remain: the folder holds only the source.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["novel.pdf"]
