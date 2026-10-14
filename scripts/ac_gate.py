"""The acceptance-criterion marker gate (TST-R17, TST-R20).

Collects every AC ID defined in the spec folder, every ID named by an
``@pytest.mark.ac(...)`` marker on a test in the test folder (a decorator of a ``test*``
function or a ``Test*`` class, or a ``pytestmark`` value, in a ``test_*.py`` or
``*_test.py`` file), and the pending-AC list, then
fails (exit 1), naming the IDs, when:

- an AC has no marked test, is not pending and is not manual;
- a marker names an ID that no spec defines;
- a pending ID already has a marked test, is not defined, or is a manual AC.

AC IDs come from HTML anchors ``<a id="<prefix>-ac<N>">`` or ``<a id="<prefix>-ac-<letter>">``
outside Markdown code spans and fenced code blocks. An AC is **manual** when the heading
before its first ``**Given**`` says "manual" (for example ``**MAIN-AC-E** (e) — Real readers
(manual): **Given** ...``) or its text says "This AC is **manual**". Mentioning manual ACs
elsewhere in the body, as TST-AC11 does, does not make an AC manual.

Usage: ``python scripts/ac_gate.py [--specs DIR] [--tests DIR] [--pending FILE]``; the
defaults are this repository's ``docs/specs``, ``tests`` and ``tests/ac_pending.txt``.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_ANCHOR = re.compile(r'<a\s+id="([a-z][a-z0-9]*-ac(?:\d+|-[a-z]))"\s*>\s*</a>', re.IGNORECASE)
_ANY_ANCHOR = re.compile(r"<a\s+id=", re.IGNORECASE)
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_CODE_SPAN = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
_MANUAL_SENTENCE = re.compile(r"This AC is \*\*manual\*\*", re.IGNORECASE)
_GIVEN = "**Given**"


@dataclass(frozen=True)
class SpecAc:
    ac_id: str
    manual: bool
    source: str


def _blank_out_code(text: str) -> str:
    """Replace fenced code blocks and code spans with spaces, keeping line structure."""
    lines = text.split("\n")
    out: list[str] = []
    fence: str | None = None
    for line in lines:
        m = _FENCE.match(line)
        if fence is None and m:
            fence = m.group(1)[0] * len(m.group(1))
            out.append("")
        elif fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append("")
        else:
            out.append(line)
    prose = "\n".join(out)
    return _CODE_SPAN.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), prose)


def _ac_text(prose: str, start: int) -> str:
    """The AC's text: from its anchor to the next blank line or the next anchor."""
    end_blank = prose.find("\n\n", start)
    end = len(prose) if end_blank == -1 else end_blank
    nxt = _ANY_ANCHOR.search(prose, start, end)
    return prose[start : nxt.start() if nxt else end]


def _is_manual(text: str) -> bool:
    heading = text.split(_GIVEN, 1)[0] if _GIVEN in text else text.split("\n", 1)[0]
    return "manual" in heading.lower() or bool(_MANUAL_SENTENCE.search(text))


def collect_spec_acs(specs: Path) -> dict[str, SpecAc]:
    acs: dict[str, SpecAc] = {}
    for path in sorted(specs.rglob("*.md")):
        prose = _blank_out_code(path.read_text(encoding="utf-8"))
        for m in _ANCHOR.finditer(prose):
            ac_id = m.group(1).upper()
            text = _ac_text(prose, m.end())
            acs[ac_id] = SpecAc(ac_id, _is_manual(text), str(path))
    return acs


def _is_ac_marker(func: ast.expr) -> bool:
    # Matches pytest.mark.ac(...) and mark.ac(...).
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "ac"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
    )


def _marker_ids(expr: ast.expr, path: Path) -> list[str]:
    """AC IDs named by ``ac`` marker calls anywhere inside one decorator or pytestmark value."""
    ids: list[str] = []
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and _is_ac_marker(node.func):
            for arg in node.args:
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    raise SystemExit(
                        f"{path}:{node.lineno}: ac marker arguments must be string literals"
                    )
                ids.append(arg.value.strip().upper())
    return ids


def _test_marks(body: list[ast.stmt], path: Path) -> list[str]:
    """IDs that mark collected tests: decorators on ``test*`` functions and ``Test*``
    classes, and ``pytestmark`` in a test module or a ``Test*`` class."""
    ids: list[str] = []
    for stmt in body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            if "pytestmark" in names and stmt.value is not None:
                ids += _marker_ids(stmt.value, path)
        elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            if stmt.name.startswith("test"):
                for dec in stmt.decorator_list:
                    ids += _marker_ids(dec, path)
        elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
            for dec in stmt.decorator_list:
                ids += _marker_ids(dec, path)
            ids += _test_marks(stmt.body, path)
    return ids


def _is_test_module(path: Path) -> bool:
    # pytest's default python_files.
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def collect_marked_ids(tests: Path) -> dict[str, list[str]]:
    """Map each AC ID that marks a collected test to the test files that name it."""
    marked: dict[str, list[str]] = {}
    for path in sorted(p for p in tests.rglob("*.py") if _is_test_module(p)):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for ac_id in _test_marks(tree.body, path):
            marked.setdefault(ac_id, []).append(str(path))
    return marked


def read_pending(pending: Path) -> list[str]:
    ids: list[str] = []
    for line in pending.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            ids.append(stripped.upper())
    return ids


def check(specs: Path, tests: Path, pending: Path) -> list[str]:
    """Return one error line per problem; an empty list means the gate passes."""
    acs = collect_spec_acs(specs)
    marked = collect_marked_ids(tests)
    pending_ids = read_pending(pending)
    pending_set = set(pending_ids)
    errors: list[str] = []
    for ac_id, ac in sorted(acs.items()):
        if not ac.manual and ac_id not in marked and ac_id not in pending_set:
            errors.append(f"unmarked and not pending: {ac_id} ({ac.source})")
    for ac_id, files in sorted(marked.items()):
        if ac_id not in acs:
            errors.append(f"marker names unknown AC: {ac_id} ({', '.join(sorted(set(files)))})")
    for ac_id in pending_ids:
        if ac_id not in acs:
            errors.append(f"pending but unknown: {ac_id}")
        elif acs[ac_id].manual:
            errors.append(f"pending but manual: {ac_id}")
        elif ac_id in marked:
            errors.append(f"pending but already marked: {ac_id} (remove it from {pending})")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0] if __doc__ else "")
    parser.add_argument("--specs", type=Path, default=REPO / "docs" / "specs")
    parser.add_argument("--tests", type=Path, default=REPO / "tests")
    parser.add_argument("--pending", type=Path, default=REPO / "tests" / "ac_pending.txt")
    args = parser.parse_args(argv)
    errors = check(args.specs, args.tests, args.pending)
    if errors:
        print(f"AC-marker gate failed ({len(errors)} problems):", file=sys.stderr)
        for line in errors:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("AC-marker gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
