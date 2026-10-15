"""``scripts/licence_check.py``: every runtime dependency's licence must be on the allowlist
in docs/instructions/coding.md section 9 (ticket #97).

The failing cases run the script against a folder of made-up installed distributions
(``--path``), so they never depend on what the real environment contains."""

import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "licence_check.py"
PR_WORKFLOW = REPO / ".github" / "workflows" / "pr.yml"
GPL3_CLASSIFIER = "License :: OSI Approved :: GNU General Public License v3 (GPLv3)"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )


def make_dist(
    site: Path,
    name: str,
    *,
    expression: str | None = None,
    licence: str | None = None,
    classifiers: Sequence[str] = (),
    requires: Sequence[str] = (),
) -> None:
    """Write a minimal installed distribution (a ``.dist-info`` folder) into ``site``."""
    info = site / f"{name.replace('-', '_')}-1.0.dist-info"
    info.mkdir(parents=True)
    lines = ["Metadata-Version: 2.4", f"Name: {name}", "Version: 1.0"]
    if expression is not None:
        lines.append(f"License-Expression: {expression}")
    if licence is not None:
        lines.append(f"License: {licence}")
    lines += [f"Classifier: {c}" for c in classifiers]
    lines += [f"Requires-Dist: {r}" for r in requires]
    (info / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_fake(site: Path) -> subprocess.CompletedProcess[str]:
    return run("--root", "book", "--path", str(site))


def test_todays_runtime_dependencies_pass() -> None:
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    # Every direct runtime dependency in pyproject.toml is listed, and passes.
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    listed = {line.split()[1] for line in result.stdout.splitlines() if line.startswith("ok ")}
    for dependency in project["dependencies"]:
        assert canonicalize_name(Requirement(dependency).name) in listed


def test_the_pr_workflow_runs_the_licence_check() -> None:
    assert "uv run python scripts/licence_check.py" in PR_WORKFLOW.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("metadata", "allowed"),
    [
        ({"expression": "MIT"}, True),
        ({"expression": "Apache-2.0 OR BSD-3-Clause"}, True),
        ({"expression": "AGPL-3.0-only OR MIT"}, True),
        ({"expression": "(MPL-2.0 AND ISC) OR GPL-3.0-only"}, True),
        ({"expression": "MIT-CMU"}, True),
        ({"licence": "PSF-2.0"}, True),
        ({"classifiers": ["License :: OSI Approved :: BSD License"]}, True),
        # PyMuPDF's licence: the case the check exists for.
        ({"expression": "AGPL-3.0-only"}, False),
        ({"expression": "MIT AND GPL-2.0-or-later"}, False),
        ({"expression": "LGPL-3.0-or-later"}, False),
        ({"licence": "GPL-3.0-only"}, False),
        ({"classifiers": [GPL3_CLASSIFIER]}, False),
        ({"licence": "Free for non-commercial use"}, False),
        ({}, False),
    ],
)
def test_a_dependency_licence_passes_only_when_allowlisted(
    tmp_path: Path, metadata: dict[str, Any], allowed: bool
) -> None:
    make_dist(tmp_path, "book", expression="MIT", requires=["dep"])
    make_dist(tmp_path, "dep", **metadata)
    result = check_fake(tmp_path)
    assert result.returncode == (0 if allowed else 1), result.stdout + result.stderr
    assert ("FAIL dep 1.0" in result.stdout) is not allowed


def test_a_transitive_dependency_with_a_disallowed_licence_fails(tmp_path: Path) -> None:
    make_dist(tmp_path, "book", expression="MIT", requires=["middle"])
    make_dist(tmp_path, "middle", expression="BSD-3-Clause", requires=["pymupdf>=1"])
    make_dist(tmp_path, "pymupdf", expression="AGPL-3.0-only")
    result = check_fake(tmp_path)
    assert result.returncode == 1
    assert "FAIL pymupdf 1.0: AGPL-3.0-only" in result.stdout
    assert "ok   middle 1.0" in result.stdout


def test_dependencies_that_are_not_installed_at_run_time_are_not_checked(tmp_path: Path) -> None:
    # An unrequested extra, a marker for another platform, and the root's own licence.
    make_dist(
        tmp_path,
        "book",
        expression="LicenseRef-Proprietary",
        requires=["dep", "gpl-extra; extra == 'gui'", "gpl-elsewhere; sys_platform == 'nowhere'"],
    )
    make_dist(tmp_path, "dep", expression="MIT")
    make_dist(tmp_path, "gpl-extra", expression="GPL-3.0-only")
    make_dist(tmp_path, "gpl-elsewhere", expression="GPL-3.0-only")
    result = check_fake(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "gpl" not in result.stdout


def test_an_extra_that_a_requirement_asks_for_is_checked(tmp_path: Path) -> None:
    make_dist(tmp_path, "book", expression="MIT", requires=["dep[fast]"])
    make_dist(tmp_path, "dep", expression="MIT", requires=["speedup; extra == 'fast'"])
    make_dist(tmp_path, "speedup", expression="GPL-3.0-only")
    result = check_fake(tmp_path)
    assert result.returncode == 1
    assert "FAIL speedup 1.0" in result.stdout


def test_an_exception_covers_only_the_licence_text_it_names(tmp_path: Path) -> None:
    make_dist(tmp_path, "book", expression="MIT", requires=["numpy", "pypdfium2"])
    # The excepted text, as NumPy declares it today: passes.
    make_dist(tmp_path, "numpy", expression="BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0")
    # A changed declaration from an excepted package: must be reviewed again.
    make_dist(tmp_path, "pypdfium2", licence="BSD-3-Clause, GPL-3.0, dependency licenses")
    result = check_fake(tmp_path)
    assert result.returncode == 1
    assert "ok   numpy 1.0" in result.stdout
    assert "FAIL pypdfium2 1.0" in result.stdout


def test_a_missing_dependency_is_an_error(tmp_path: Path) -> None:
    make_dist(tmp_path, "book", expression="MIT", requires=["absent"])
    result = check_fake(tmp_path)
    assert result.returncode == 1
    assert "absent is required but not installed" in result.stderr
