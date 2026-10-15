"""Check the licence of every runtime dependency against the project's allowlist.

Walks the installed runtime dependency closure of pdf2epub (its own requirements and
theirs, never the dev dependency group), reads each distribution's declared licence and
fails when one is not on the allowlist (docs/instructions/coding.md section 9).

    uv run python scripts/licence_check.py

Run it in an environment made with ``uv sync --locked``. Requirement markers are evaluated
for the platform it runs on.

A distribution's licence is, in order: its ``License-Expression`` (PEP 639); else its
``License`` field when that is a valid SPDX expression; else its ``License ::``
classifiers. An SPDX expression passes when it is satisfied using allowlisted licences
only: every operand of ``AND``, at least one of ``OR``. Anything unknown or unclear fails
unless ``EXCEPTIONS`` names it.

Exit status: 0 when every licence passes, 1 when any fails.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import Distribution, distributions

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = "pdf2epub"

# SPDX identifiers that are MIT-compatible (coding.md section 9): MIT, BSD, Apache-2.0,
# ISC, PSF, MPL-2.0 and HPND / MIT-CMU (Pillow).
ALLOWED_SPDX = frozenset(
    {
        "MIT",
        "MIT-0",
        "MIT-CMU",
        "HPND",
        "0BSD",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "ISC",
        "PSF-2.0",
        "Python-2.0",
        "MPL-2.0",
    }
)

# Trove classifiers that name an allowlisted licence, for distributions that declare no
# SPDX expression.
ALLOWED_CLASSIFIERS = frozenset(
    {
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: MIT No Attribution License (MIT-0)",
        "License :: OSI Approved :: BSD License",
        "License :: OSI Approved :: Apache Software License",
        "License :: OSI Approved :: ISC License (ISCL)",
        "License :: OSI Approved :: Python Software Foundation License",
        "License :: OSI Approved :: Python License",
        "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
        "License :: OSI Approved :: Historical Permission Notice and Disclaimer (HPND)",
    }
)

# Exceptions: distribution name -> (the exact licence text it declares, why it is
# accepted). An exception covers only that text: if a new release declares something
# else, the check fails again and the new licence must be reviewed.
EXCEPTIONS: dict[str, tuple[str, str]] = {
    # NumPy's own code is BSD-3-Clause; the other terms cover bundled code (0BSD, MIT,
    # Zlib and CC0-1.0 pieces), all permissive and compatible with MIT.
    "numpy": (
        "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0",
        "bundled components under Zlib and CC0-1.0, both permissive",
    ),
    # Not an SPDX expression. The wrapper and the bundled PDFium binary are BSD-3-Clause /
    # Apache-2.0; PDFium's bundled libraries (FreeType, ICU, lcms, libjpeg-turbo, libpng,
    # OpenJPEG, zlib, ...) are permissive. Their texts ship in the wheel's dist-info
    # (licenses/LICENSES and licenses/data/*/BUILD_LICENSES).
    "pypdfium2": (
        "BSD-3-Clause, Apache-2.0, dependency licenses",
        "wrapper and PDFium under BSD-3-Clause / Apache-2.0; bundled libraries permissive",
    ),
}


@dataclass(frozen=True)
class Verdict:
    name: str
    version: str
    licence: str
    allowed: bool
    note: str


def runtime_closure(root: str, path: Sequence[str] | None = None) -> list[Distribution]:
    """The installed distributions ``root`` needs at run time, ``root`` first, then sorted
    by name. Optional dependencies are followed only where a requirement asks for them."""
    found: dict[str, Distribution] = {
        canonicalize_name(d.metadata["Name"]): d
        for d in (distributions(path=list(path)) if path is not None else distributions())
    }
    closure: dict[str, Distribution] = {}
    pending: list[tuple[str, frozenset[str]]] = [(canonicalize_name(root), frozenset())]
    seen: set[tuple[str, frozenset[str]]] = set()
    while pending:
        name, extras = pending.pop()
        if (name, extras) in seen:
            continue
        seen.add((name, extras))
        dist = found.get(name)
        if dist is None:
            raise LookupError(f"{name} is required but not installed; run `uv sync --locked`")
        closure[name] = dist
        for line in dist.requires or []:
            req = Requirement(line)
            if req.marker is not None and not any(
                req.marker.evaluate({"extra": extra}) for extra in ("", *extras)
            ):
                continue
            pending.append((canonicalize_name(req.name), frozenset(req.extras)))
    first = canonicalize_name(root)
    return [closure[first], *(closure[n] for n in sorted(closure) if n != first)]


def declared_licence(dist: Distribution) -> tuple[str, str | None]:
    """The licence text the distribution declares, and its SPDX form if it has one."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression, _spdx(expression)
    field = (meta.get("License") or "").strip()
    if field and _spdx(field) is not None:
        return field, _spdx(field)
    classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(classifiers), None
    return field or "UNKNOWN", None


def _spdx(text: str) -> str | None:
    try:
        return str(canonicalize_license_expression(text))
    except InvalidLicenseExpression:
        return None


def spdx_allowed(expression: str) -> bool:
    """Whether an SPDX expression can be satisfied with allowlisted licences alone."""
    tokens: list[str] = re.findall(r"\(|\)|[^\s()]+", expression)
    position = 0

    def peek() -> str | None:
        return tokens[position] if position < len(tokens) else None

    def take() -> str:
        nonlocal position
        position += 1
        return tokens[position - 1]

    def either() -> bool:  # OR binds more loosely than AND
        result = both()
        while peek() == "OR":
            take()
            result = both() or result
        return result

    def both() -> bool:
        result = single()
        while peek() == "AND":
            take()
            result = single() and result
        return result

    def single() -> bool:
        token = take()
        if token == "(":
            result = either()
            take()  # ")"
            return result
        if peek() == "WITH":  # a licence exception only adds permissions
            take()
            take()
        return token.removesuffix("+") in ALLOWED_SPDX

    return either()


def judge(dist: Distribution) -> Verdict:
    name = canonicalize_name(dist.metadata["Name"])
    text, spdx = declared_licence(dist)
    version = dist.version
    exception = EXCEPTIONS.get(name)
    if exception is not None and exception[0] == text:
        return Verdict(name, version, text, True, f"exception: {exception[1]}")
    if spdx is not None:
        return Verdict(name, version, text, spdx_allowed(spdx), "")
    classifiers = [c for c in text.split("; ") if c.startswith("License ::")]
    if classifiers and all(c in ALLOWED_CLASSIFIERS for c in classifiers):
        return Verdict(name, version, text, True, "")
    return Verdict(name, version, text, False, "not an allowlisted SPDX licence or classifier")


def report(verdicts: Iterable[Verdict]) -> tuple[list[str], bool]:
    lines: list[str] = []
    ok = True
    for v in verdicts:
        mark = "ok  " if v.allowed else "FAIL"
        note = f"  ({v.note})" if v.note else ""
        lines.append(f"{mark} {v.name} {v.version}: {v.licence}{note}")
        ok = ok and v.allowed
    return lines, ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=ROOT, help="distribution to start from")
    parser.add_argument(
        "--path",
        action="append",
        help="look for installed distributions only in this folder (repeatable)",
    )
    args = parser.parse_args(argv)
    try:
        closure = runtime_closure(args.root, args.path)
    except LookupError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    root = canonicalize_name(args.root)
    lines, ok = report(judge(d) for d in closure if canonicalize_name(d.metadata["Name"]) != root)
    print("\n".join(lines))
    if not ok:
        print(
            "\nA runtime dependency's licence is not on the allowlist. See "
            "docs/instructions/coding.md section 9 before adding an exception.",
            file=sys.stderr,
        )
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
