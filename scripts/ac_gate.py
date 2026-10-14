"""The acceptance-criterion marker gate (TST-R17, TST-R20).

Collects every AC ID defined in the spec folder, every ID named by an
``@pytest.mark.ac(...)`` marker on a collected test in the test folder (rules in
``_TestModule``), and the pending-AC list, then
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


class _TestModule:
    """Finds the AC IDs that mark collected tests in one test module, without importing it.

    A marker counts only when its receiver is pytest's: ``pytest.mark.ac`` (or an
    ``import pytest as ...`` alias) or ``mark.ac`` after ``from pytest import mark``
    (or an alias). It must decorate a ``test*`` function, or decorate or sit in the
    ``pytestmark`` of a module or ``Test*`` class (without ``__init__``) that contains
    at least one test.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        self.pytest_names: set[str] = set()
        self.mark_names: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "pytest":
                        self.pytest_names.add(alias.asname or "pytest")
            elif isinstance(node, ast.ImportFrom) and node.module == "pytest" and node.level == 0:
                for alias in node.names:
                    if alias.name == "mark":
                        self.mark_names.add(alias.asname or "mark")

    def _is_ac_marker(self, func: ast.expr) -> bool:
        if not (isinstance(func, ast.Attribute) and func.attr == "ac"):
            return False
        receiver = func.value
        if isinstance(receiver, ast.Name):
            return receiver.id in self.mark_names
        return (
            isinstance(receiver, ast.Attribute)
            and receiver.attr == "mark"
            and isinstance(receiver.value, ast.Name)
            and receiver.value.id in self.pytest_names
        )

    def _marker_ids(self, exprs: list[ast.expr]) -> list[str]:
        """AC IDs named by ``ac`` marker calls anywhere inside these expressions."""
        ids: list[str] = []
        for expr in exprs:
            for node in ast.walk(expr):
                if isinstance(node, ast.Call) and self._is_ac_marker(node.func):
                    for arg in node.args:
                        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                            raise SystemExit(
                                f"{self.path}:{node.lineno}: "
                                "ac marker arguments must be string literals"
                            )
                        ids.append(arg.value.strip().upper())
        return ids

    def _scope(self, body: list[ast.stmt]) -> tuple[list[str], bool]:
        """(IDs marking tests in this module or class body, whether it holds any test)."""
        ids: list[str] = []
        scope_marks: list[ast.expr] = []
        has_tests = False
        for stmt in body:
            if isinstance(stmt, ast.Assign | ast.AnnAssign):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                if stmt.value is not None and any(
                    isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets
                ):
                    scope_marks.append(stmt.value)
            elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                if stmt.name.startswith("test"):
                    has_tests = True
                    ids += self._marker_ids(stmt.decorator_list)
            elif isinstance(stmt, ast.ClassDef) and self._collectable_class(stmt):
                class_ids, class_has_tests = self._scope(stmt.body)
                if class_has_tests:
                    has_tests = True
                    ids += class_ids + self._marker_ids(stmt.decorator_list)
        if has_tests:
            ids += self._marker_ids(scope_marks)
        return ids, has_tests

    @staticmethod
    def _collectable_class(cls: ast.ClassDef) -> bool:
        # pytest skips Test* classes that define __init__.
        return cls.name.startswith("Test") and not any(
            isinstance(s, ast.FunctionDef) and s.name == "__init__" for s in cls.body
        )

    def marked_ids(self) -> list[str]:
        return self._scope(self.tree.body)[0]


def _is_test_module(path: Path) -> bool:
    # pytest's default python_files.
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def collect_marked_ids(tests: Path) -> dict[str, list[str]]:
    """Map each AC ID that marks a collected test to the test files that name it."""
    marked: dict[str, list[str]] = {}
    for path in sorted(p for p in tests.rglob("*.py") if _is_test_module(p)):
        for ac_id in _TestModule(path).marked_ids():
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
