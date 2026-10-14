"""The AC-marker gate (TST-R17, TST-R20), run as CI runs it: a script over a spec folder,
a test folder and a pending list."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ac_gate.py"


@dataclass
class GateResult:
    returncode: int
    output: str


def run_gate(specs: Path, tests: Path, pending: Path) -> GateResult:
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE),
            "--specs",
            str(specs),
            "--tests",
            str(tests),
            "--pending",
            str(pending),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return GateResult(proc.returncode, proc.stdout + proc.stderr)


def make_repo(
    root: Path, spec: str, marked: list[str], pending: list[str]
) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    specs = root / "specs"
    tests = root / "tests"
    specs.mkdir()
    tests.mkdir()
    (specs / "xyz.md").write_text(spec, encoding="utf-8")
    body = ["import pytest", ""]
    for n, ac_id in enumerate(marked):
        body += [f'@pytest.mark.ac("{ac_id}")', f"def test_{n}() -> None:", "    assert True", ""]
    (tests / "test_xyz.py").write_text("\n".join(body), encoding="utf-8")
    pending_file = root / "ac_pending.txt"
    pending_file.write_text("".join(f"{p}\n" for p in pending), encoding="utf-8")
    return specs, tests, pending_file


def ac(anchor: str, label: str, text: str = "**Given** x, **when** y, **then** z.") -> str:
    return f'<a id="{anchor}"></a>**{label}**: {text}\n\n'


# --- TST-AC11 -------------------------------------------------------------------------


@pytest.mark.ac("TST-AC11")
def test_unmarked_numbered_ac_fails_and_is_named(tmp_path: Path) -> None:
    spec = ac("xyz-ac1", "XYZ-AC1") + ac("xyz-ac2", "XYZ-AC2")
    result = run_gate(*make_repo(tmp_path, spec, marked=["XYZ-AC2"], pending=[]))
    assert result.returncode == 1
    assert "XYZ-AC1" in result.output
    assert "XYZ-AC2" not in result.output


@pytest.mark.ac("TST-AC11")
def test_marker_naming_unknown_id_fails_and_is_named(tmp_path: Path) -> None:
    spec = ac("xyz-ac1", "XYZ-AC1")
    result = run_gate(*make_repo(tmp_path, spec, marked=["XYZ-AC1", "XYZ-AC99"], pending=[]))
    assert result.returncode == 1
    assert "XYZ-AC99" in result.output


@pytest.mark.ac("TST-AC11")
def test_unmarked_lettered_ac_fails_and_is_named(tmp_path: Path) -> None:
    spec = ac("xyz-ac1", "XYZ-AC1") + ac("xyz-ac-b", "XYZ-AC-B")
    result = run_gate(*make_repo(tmp_path, spec, marked=["XYZ-AC1"], pending=[]))
    assert result.returncode == 1
    assert "XYZ-AC-B" in result.output


@pytest.mark.ac("TST-AC11")
def test_anchors_in_code_spans_and_fenced_blocks_are_not_collected(tmp_path: Path) -> None:
    spec = (
        ac("xyz-ac1", "XYZ-AC1")
        + 'An example: `<a id="xyz-ac2"></a>` and ``<a id="xyz-ac3"></a>``.\n\n'
        + '```markdown\n<a id="xyz-ac4"></a>**XYZ-AC4**: fenced.\n```\n\n'
        + '~~~\n<a id="xyz-ac5"></a>**XYZ-AC5**: fenced with tildes.\n~~~\n'
    )
    result = run_gate(*make_repo(tmp_path, spec, marked=["XYZ-AC1"], pending=[]))
    assert result.returncode == 0, result.output
    # A marker naming a code-span-only anchor is unknown, so it is not collected either.
    result = run_gate(*make_repo(tmp_path / "b", spec, marked=["XYZ-AC1", "XYZ-AC4"], pending=[]))
    assert result.returncode == 1
    assert "XYZ-AC4" in result.output


@pytest.mark.ac("TST-AC11")
def test_unmarked_manual_ac_is_not_reported(tmp_path: Path) -> None:
    spec = ac("xyz-ac1", "XYZ-AC1") + ac(
        "xyz-ac-e",
        "XYZ-AC-E",
        "Real readers (manual): **Given** an EPUB, **when** the owner opens it, **then** it "
        "reads. This AC is **manual**.",
    )
    result = run_gate(*make_repo(tmp_path, spec, marked=["XYZ-AC1"], pending=[]))
    assert result.returncode == 0, result.output
    assert "XYZ-AC-E" not in result.output


@pytest.mark.ac("TST-AC11")
def test_ac_that_only_mentions_manual_in_its_body_is_still_collected(tmp_path: Path) -> None:
    # Like TST-AC11 itself: its body talks about **manual** ACs, but it is not one.
    spec = ac("xyz-ac1", "XYZ-AC1", "**Given** an AC whose text says it is **manual**, **then** x.")
    result = run_gate(*make_repo(tmp_path, spec, marked=[], pending=[]))
    assert result.returncode == 1
    assert "XYZ-AC1" in result.output


@pytest.mark.ac("TST-AC11")
def test_passes_when_every_ac_is_marked(tmp_path: Path) -> None:
    spec = ac("xyz-ac1", "XYZ-AC1") + ac("xyz-ac-b", "XYZ-AC-B")
    result = run_gate(*make_repo(tmp_path, spec, marked=["XYZ-AC1", "XYZ-AC-B"], pending=[]))
    assert result.returncode == 0, result.output


@pytest.mark.ac("TST-AC11")
def test_only_markers_on_tests_count(tmp_path: Path) -> None:
    spec = "".join(ac(f"xyz-ac{n}", f"XYZ-AC{n}") for n in range(1, 10))
    specs, tests, pending = make_repo(tmp_path, spec, marked=[], pending=[])
    (tests / "test_forms.py").write_text(
        """
import pytest

pytestmark = [pytest.mark.ac("XYZ-AC1")]


@pytest.mark.parametrize("x", [pytest.param(1, marks=pytest.mark.ac("XYZ-AC2"))])
def test_param(x: int) -> None:
    assert x


@pytest.mark.ac("XYZ-AC3")
class TestGroup:
    pytestmark = pytest.mark.ac("XYZ-AC4")

    @pytest.mark.ac("XYZ-AC5")
    async def test_method(self) -> None:
        assert True


# None of these mark a collected test:
MARK = pytest.mark.ac("XYZ-AC6")


def helper() -> None:
    pytest.mark.ac("XYZ-AC7")


@pytest.mark.ac("XYZ-AC8")
def not_a_test() -> None:
    pass


class Helper:
    @pytest.mark.ac("XYZ-AC9")
    def test_in_non_test_class(self) -> None:
        pass
""",
        encoding="utf-8",
    )
    result = run_gate(specs, tests, pending)
    assert result.returncode == 1
    for counted in ["XYZ-AC1", "XYZ-AC2", "XYZ-AC3", "XYZ-AC4", "XYZ-AC5"]:
        assert f"unmarked and not pending: {counted}" not in result.output
    for ignored in ["XYZ-AC6", "XYZ-AC7", "XYZ-AC8", "XYZ-AC9"]:
        assert f"unmarked and not pending: {ignored}" in result.output


@pytest.mark.ac("TST-AC11")
def test_scope_marks_count_only_where_tests_are_collected(tmp_path: Path) -> None:
    spec = "".join(ac(f"xyz-ac{n}", f"XYZ-AC{n}") for n in range(1, 6))
    specs, tests, pending = make_repo(tmp_path, spec, marked=["XYZ-AC5"], pending=[])
    (tests / "test_helpers_only.py").write_text(
        'import pytest\n\npytestmark = pytest.mark.ac("XYZ-AC1")\n\n\ndef helper() -> None:\n'
        "    pass\n",
        encoding="utf-8",
    )
    (tests / "test_classes.py").write_text(
        """
import pytest


@pytest.mark.ac("XYZ-AC2")
class TestEmpty:
    pass


@pytest.mark.ac("XYZ-AC3")
class TestWithInit:  # pytest does not collect a Test class that defines __init__
    def __init__(self) -> None:
        pass

    def test_x(self) -> None:
        pass


class TestHelperOnly:
    pytestmark = pytest.mark.ac("XYZ-AC4")

    def helper(self) -> None:
        pass
""",
        encoding="utf-8",
    )
    result = run_gate(specs, tests, pending)
    assert result.returncode == 1
    for ignored in ["XYZ-AC1", "XYZ-AC2", "XYZ-AC3", "XYZ-AC4"]:
        assert f"unmarked and not pending: {ignored}" in result.output
    assert "XYZ-AC5" not in result.output


@pytest.mark.ac("TST-AC11")
def test_only_pytest_mark_receivers_count(tmp_path: Path) -> None:
    spec = "".join(ac(f"xyz-ac{n}", f"XYZ-AC{n}") for n in range(1, 7))
    specs, tests, pending = make_repo(tmp_path, spec, marked=[], pending=[])
    (tests / "test_aliases.py").write_text(
        """
import pytest as pt
from pytest import mark
from pytest import mark as m2

import other


@pt.mark.ac("XYZ-AC1")
def test_a() -> None:
    pass


@mark.ac("XYZ-AC2")
def test_b() -> None:
    pass


@m2.ac("XYZ-AC3")
def test_c() -> None:
    pass


@other.mark.ac("XYZ-AC4")
def test_d() -> None:
    pass


@other.ac("XYZ-AC5")
def test_e() -> None:
    pass
""",
        encoding="utf-8",
    )
    (tests / "test_shadowed.py").write_text(
        """
import other as p


def helper() -> None:
    import pytest as p  # local to helper: the decorator below still sees `other`

    p.skip()


@p.mark.ac("XYZ-AC6")
def test_f() -> None:
    pass
""",
        encoding="utf-8",
    )
    result = run_gate(specs, tests, pending)
    assert result.returncode == 1
    for counted in ["XYZ-AC1", "XYZ-AC2", "XYZ-AC3"]:
        assert counted not in result.output
    for ignored in ["XYZ-AC4", "XYZ-AC5", "XYZ-AC6"]:
        assert f"unmarked and not pending: {ignored}" in result.output


# --- TST-AC14 -------------------------------------------------------------------------

AC14_SPEC = (
    ac("xyz-ac1", "XYZ-AC1")
    + ac("xyz-ac2", "XYZ-AC2")
    + ac("xyz-ac3", "XYZ-AC3", "Manual check (manual): **Given** x, **then** y.")
)


@pytest.mark.ac("TST-AC14")
def test_passes_when_unmarked_ac_is_pending(tmp_path: Path) -> None:
    result = run_gate(*make_repo(tmp_path, AC14_SPEC, marked=["XYZ-AC1"], pending=["XYZ-AC2"]))
    assert result.returncode == 0, result.output


@pytest.mark.ac("TST-AC14")
def test_pending_file_ignores_blank_and_comment_lines(tmp_path: Path) -> None:
    pending = ["# not yet implemented", "", "XYZ-AC2", "   "]
    result = run_gate(*make_repo(tmp_path, AC14_SPEC, marked=["XYZ-AC1"], pending=pending))
    assert result.returncode == 0, result.output


@pytest.mark.ac("TST-AC14")
def test_fails_on_unmarked_ac_not_pending(tmp_path: Path) -> None:
    result = run_gate(*make_repo(tmp_path, AC14_SPEC, marked=["XYZ-AC1"], pending=[]))
    assert result.returncode == 1
    assert "unmarked and not pending: XYZ-AC2" in result.output


@pytest.mark.ac("TST-AC14")
def test_fails_on_pending_ac_that_is_marked(tmp_path: Path) -> None:
    pending = ["XYZ-AC1", "XYZ-AC2"]
    result = run_gate(*make_repo(tmp_path, AC14_SPEC, marked=["XYZ-AC1"], pending=pending))
    assert result.returncode == 1
    assert "pending but already marked: XYZ-AC1" in result.output


@pytest.mark.ac("TST-AC14")
def test_fails_on_pending_ac_that_is_unknown(tmp_path: Path) -> None:
    pending = ["XYZ-AC2", "XYZ-AC9"]
    result = run_gate(*make_repo(tmp_path, AC14_SPEC, marked=["XYZ-AC1"], pending=pending))
    assert result.returncode == 1
    assert "pending but unknown: XYZ-AC9" in result.output


@pytest.mark.ac("TST-AC14")
def test_fails_on_pending_ac_that_is_manual(tmp_path: Path) -> None:
    pending = ["XYZ-AC2", "XYZ-AC3"]
    result = run_gate(*make_repo(tmp_path, AC14_SPEC, marked=["XYZ-AC1"], pending=pending))
    assert result.returncode == 1
    assert "pending but manual: XYZ-AC3" in result.output


# --- Local AC: the gate passes on this repository -------------------------------------


def test_gate_passes_on_this_repository() -> None:
    result = run_gate(REPO / "docs" / "specs", REPO / "tests", REPO / "tests" / "ac_pending.txt")
    assert result.returncode == 0, result.output
