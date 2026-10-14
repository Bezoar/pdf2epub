"""Installing pdf2epub from git, and the README's install steps (MAIN-R15, MAIN-R17).

The install itself runs in CI, on clean macOS and Linux runners (the PR workflow's
``install`` job); this checks that the job does what MAIN-AC5 asks, and that the README
has the Tesseract steps.
"""

import re
from typing import Any

import pytest
from test_workflows import PR_WORKFLOW, REPO, RUNNER_PLATFORM, load_workflow, triggers

README = REPO / "README.md"
INSTALL = re.compile(r"uv tool install \"?git\+https://github\.com/")


def install_jobs() -> list[dict[str, Any]]:
    jobs = load_workflow(PR_WORKFLOW)["jobs"]
    return [
        job
        for job in jobs.values()
        if any(INSTALL.search(str(step.get("run", ""))) for step in job.get("steps", []))
    ]


@pytest.mark.ac("MAIN-AC5")
def test_ci_installs_from_git_on_clean_macos_and_linux_runners() -> None:
    assert "pull_request" in triggers(load_workflow(PR_WORKFLOW))
    [job] = install_jobs()
    runners = job.get("strategy", {}).get("matrix", {}).get("os", [])
    platforms = {RUNNER_PLATFORM[runner].split("-")[0] for runner in runners}
    assert platforms == {"macos", "linux"}
    steps = job["steps"]
    assert isinstance(steps, list)
    # A clean runner: nothing is checked out or synced before the install.
    uses = [str(step.get("uses", "")) for step in steps]
    assert not [u for u in uses if u.startswith("actions/checkout")]
    runs = [str(step.get("run", "")) for step in steps]
    assert not [r for r in runs if "uv sync" in r or "pip install" in r]
    install = next(i for i, run in enumerate(runs) if INSTALL.search(run))
    # The commit under test, from the repository it lives in (a fork's, for its PRs).
    assert "${REPOSITORY}@${COMMIT}" in runs[install]
    env = steps[install]["env"]
    assert env["REPOSITORY"].replace(" ", "") == (
        "${{github.event.pull_request.head.repo.full_name||github.repository}}"
    )
    assert env["COMMIT"].replace(" ", "") == "${{github.event.pull_request.head.sha||github.sha}}"
    assert any(re.search(r"^pdf2epub --version$", run, re.M) for run in runs[install:])


@pytest.mark.ac("MAIN-AC5")
def test_readme_has_tesseract_install_steps_for_homebrew_apt_and_language_packs() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "uv tool install git+https://github.com/Bezoar/pdf2epub" in readme
    section = readme.split("## Installing Tesseract", 1)[1].split("\n## ", 1)[0]
    assert "brew install tesseract" in section
    assert "tesseract-lang" in section  # Homebrew's language packs
    assert "apt install tesseract-ocr" in section
    assert "tesseract-ocr-<code>" in section  # apt's language packs
