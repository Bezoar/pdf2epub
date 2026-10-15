"""``--help`` lists every flag in the CLI spec's flag tables (#46's local AC)."""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI_SPEC = REPO / "docs" / "specs" / "cli.md"
PDF2EPUB = Path(sys.executable).with_name("pdf2epub")


def spec_flags() -> list[str]:
    """Every flag named in the first column of the tables in the spec's section 2."""
    text = CLI_SPEC.read_text(encoding="utf-8")
    match = re.search(r"^## 2\. Flags\n(.*?)^## 3\.", text, re.S | re.M)
    assert match, "cli.md has no '## 2. Flags' section"
    flags = []
    for line in match.group(1).splitlines():
        if line.startswith("| `"):
            first_cell = line.split("|")[1]
            flags.extend(re.findall(r"`(-[^`]+)`", first_cell))
    return flags


def test_help_lists_every_flag_in_the_cli_spec() -> None:
    flags = spec_flags()
    assert len(flags) > 30, flags  # the tables were found and read

    proc = subprocess.run(
        [str(PDF2EPUB), "--help"], capture_output=True, text=True, encoding="utf-8", check=False
    )

    assert proc.returncode == 0, proc.stderr
    listed = set(re.findall(r"(?<![\w-])(--?[A-Za-z][\w-]*)", proc.stdout))
    assert [flag for flag in flags if flag not in listed] == []
