"""The CI workflow definitions and the declared Python floor (MAIN-R10, MAIN-R11)."""

import itertools
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PR_WORKFLOW = REPO / ".github" / "workflows" / "pr.yml"

# GitHub-hosted runner labels and the platform each one provides (GitHub docs,
# "GitHub-hosted runners reference").
RUNNER_PLATFORM = {
    "macos-14": "macos-arm64",
    "macos-15": "macos-arm64",
    "macos-26": "macos-arm64",
    "macos-latest": "macos-arm64",
    "ubuntu-22.04": "linux-x86_64",
    "ubuntu-24.04": "linux-x86_64",
    "ubuntu-latest": "linux-x86_64",
    "ubuntu-22.04-arm": "linux-arm64",
    "ubuntu-24.04-arm": "linux-arm64",
}


def load_workflow(path: Path) -> dict[Any, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the bare key `on` as the boolean True.
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    assert isinstance(on, dict)
    return on


def matrix_combinations(job: dict[str, Any]) -> set[tuple[str, str]]:
    matrix = job.get("strategy", {}).get("matrix", {})
    combos = {
        (str(os_), str(py))
        for os_, py in itertools.product(matrix.get("os", []), matrix.get("python-version", []))
    }
    for extra in matrix.get("include", []):
        if "os" in extra and "python-version" in extra:
            combos.add((str(extra["os"]), str(extra["python-version"])))
    for gone in matrix.get("exclude", []):
        combos.discard((str(gone.get("os")), str(gone.get("python-version"))))
    return combos


@pytest.mark.ac("MAIN-AC4")
def test_pr_workflow_runs_on_every_pull_request() -> None:
    on = triggers(load_workflow(PR_WORKFLOW))
    assert "pull_request" in on
    config = on["pull_request"] or {}
    for narrowing in ("branches", "branches-ignore", "paths", "paths-ignore", "types"):
        assert narrowing not in config, f"pull_request trigger is narrowed by {narrowing}"


@pytest.mark.ac("MAIN-AC4")
def test_pr_workflow_tests_every_python_on_every_supported_platform() -> None:
    jobs = load_workflow(PR_WORKFLOW)["jobs"]
    covered: set[tuple[str, str]] = set()
    for job in jobs.values():
        for runner, python in matrix_combinations(job):
            if runner in RUNNER_PLATFORM:
                covered.add((RUNNER_PLATFORM[runner], python))
    required = set(
        itertools.product(["macos-arm64", "linux-x86_64", "linux-arm64"], ["3.12", "3.13", "3.14"])
    )
    assert required <= covered, f"missing: {sorted(required - covered)}"


@pytest.mark.ac("MAIN-AC4")
def test_package_requires_python_312_or_later() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == ">=3.12"
