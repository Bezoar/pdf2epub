"""The legal statement in ``--help`` and the README, and the forbidden phrase (MAIN-R8,
MAIN-R9, CLI-R9)."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"
PDF2EPUB = Path(sys.executable).with_name("pdf2epub")

# CLI-R9 and MAIN-R8, verbatim.
LEGAL_STATEMENT = (
    "Opens password-protected PDFs only with a password you supply. "
    "Honours permission restrictions. Does not remove DRM."
)
# Split so that this file doesn't itself contain the phrase it searches for.
FORBIDDEN = re.compile("DRM" + r"\s+" + "removal", re.IGNORECASE)
# MAIN-AC2's exceptions: archived history, and the MAIN-R8 and MAIN-AC2 sentences.
ARCHIVE = "docs/archive/"
RULE_ANCHORS = ('id="main-r8"', 'id="main-ac2"')


def help_text() -> str:
    proc = subprocess.run(
        [str(PDF2EPUB), "--help"], capture_output=True, text=True, encoding="utf-8", check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def tracked_text_files() -> list[Path]:
    """Every file git tracks or would add (so new files count before they're committed)."""
    proc = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO,
        capture_output=True,
        check=True,
    )
    return [REPO / name for name in proc.stdout.decode().split("\0") if name]


def readme_section(title: str) -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"README has no '## {title}' section"
    return " ".join(match.group(1).split())


@pytest.mark.ac("CLI-AC8")
@pytest.mark.ac("MAIN-AC2")
def test_help_contains_the_legal_statement_verbatim() -> None:
    assert LEGAL_STATEMENT in help_text()


@pytest.mark.ac("MAIN-AC2")
def test_forbidden_phrase_appears_nowhere_outside_the_allowed_places() -> None:
    hits: list[str] = []
    for path in tracked_text_files():
        relative = path.relative_to(REPO).as_posix()
        if relative.startswith(ARCHIVE) or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary files (PDFs, images) carry no prose
        for number, line in enumerate(text.splitlines(), start=1):
            if FORBIDDEN.search(line) and not any(a in line for a in RULE_ANCHORS):
                hits.append(f"{relative}:{number}")
    assert hits == []
    assert not FORBIDDEN.search(help_text())


def test_the_phrase_search_finds_the_phrase() -> None:
    # Guards the search above against a pattern that can never match.
    assert FORBIDDEN.search("no " + "DRM" + " removal here")
    assert FORBIDDEN.search("drm\nREMOVAL")


@pytest.mark.ac("MAIN-AC6")
def test_readme_legal_scope_states_every_required_point() -> None:
    section = readme_section("Legal scope")
    required = [
        # MAIN-R3: never circumvents DRM or copy controls.
        "never circumvents DRM or any other access or copy control",
        # MAIN-R4: only Standard-handler PDFs, with a password the user supplies.
        "Standard security handler",
        "with a password you supply",
        # MAIN-R5: DRM-protected files are refused.
        "DRM-protected files are refused",
        # MAIN-R6: permission restrictions honoured; `restricted` lifted only by the owner
        # password.
        "honours permission restrictions",
        "`restricted`",
        "only the owner password lifts",
        # MAIN-R7: at most 25 candidate passwords per file.
        "at most 25 candidate passwords",
        # MAIN-R9: the EPUB is unencrypted; protecting it is the user's responsibility.
        "written unencrypted",
        "protecting it is your responsibility",
    ]
    missing = [phrase for phrase in required if phrase not in section]
    assert missing == []


def test_readme_states_the_legal_statement_verbatim() -> None:
    # MAIN-R8: the README states it too.
    assert LEGAL_STATEMENT in " ".join(README.read_text(encoding="utf-8").split())
