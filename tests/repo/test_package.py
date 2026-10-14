"""Built wheel and sdist metadata, and the licences of the runtime dependencies
(MAIN-R12, MAIN-R13, MAIN-R14, EPUB-R1)."""

import email.parser
import importlib.metadata as md
import json
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from dataclasses import dataclass
from email.message import Message
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

import pdf2epub

REPO = Path(__file__).resolve().parents[2]

# MAIN-R13's list as SPDX identifiers (lower case). MIT-0 and MIT-CMU are MIT variants
# (Pillow's HPND licence is published as MIT-CMU); 0BSD is a BSD variant. Zlib and
# CC0-1.0 cover components that NumPy, which MAIN-R13 names, bundles; both are
# permissive and impose nothing beyond MIT.
ALLOWED_SPDX = {
    "mit",
    "mit-0",
    "mit-cmu",
    "bsd-2-clause",
    "bsd-3-clause",
    "0bsd",
    "apache-2.0",
    "isc",
    "psf-2.0",
    "python-2.0",
    "hpnd",
    "mpl-2.0",
    "zlib",
    "cc0-1.0",
}

# Trove classifiers and free-text licence names, for packages without License-Expression.
LICENCE_NAMES = {
    "license :: osi approved :: mit license": "mit",
    "license :: osi approved :: bsd license": "bsd-3-clause",
    "license :: osi approved :: apache software license": "apache-2.0",
    "license :: osi approved :: isc license (iscl)": "isc",
    "license :: osi approved :: python software foundation license": "psf-2.0",
    "license :: osi approved :: historical permission notice and disclaimer (hpnd)": "hpnd",
    "license :: osi approved :: mozilla public license 2.0 (mpl 2.0)": "mpl-2.0",
    "mit": "mit",
    "mit license": "mit",
    "bsd": "bsd-3-clause",
    "bsd-3-clause": "bsd-3-clause",
    "bsd-2-clause": "bsd-2-clause",
    "apache 2.0": "apache-2.0",
    "apache-2.0": "apache-2.0",
    "psf-2.0": "psf-2.0",
}

# pypdfium2 declares "BSD-3-Clause, Apache-2.0, dependency licenses". The last part is
# PDFium's bundled third-party code (FreeType, ICU, libjpeg, ...), which MAIN-R14 handles
# as attribution: see test_installed_pypdfium2_ships_pdfium_notices.
PYPDFIUM2_BUNDLED = "dependency licenses"

FORBIDDEN_EPUB_LIBRARIES = {"ebooklib", "pymupdf", "pymupdfb", "fitz"}


@dataclass(frozen=True)
class Built:
    wheel: Path
    sdist: Path


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    out = tmp_path_factory.mktemp("dist")
    # hatchling from the dev environment: no build isolation, so no network.
    subprocess.run(
        [sys.executable, "-m", "hatchling", "build", "-d", str(out)],
        cwd=REPO,
        check=True,
        capture_output=True,
    )
    (wheel,) = out.glob("*.whl")
    (sdist,) = out.glob("*.tar.gz")
    return Built(wheel, sdist)


def wheel_metadata(wheel: Path) -> Message:
    with zipfile.ZipFile(wheel) as zf:
        (name,) = [n for n in zf.namelist() if n.endswith(".dist-info/METADATA")]
        return email.parser.Parser().parsestr(zf.read(name).decode("utf-8"))


def runtime_closure(requirements: list[str]) -> dict[str, md.Distribution]:
    """Every installed distribution reachable from these requirements (extras ignored)."""
    seen: dict[str, md.Distribution] = {}
    todo = list(requirements)
    while todo:
        req = Requirement(todo.pop())
        if req.marker is not None and not req.marker.evaluate({"extra": ""}):
            continue
        key = canonicalize_name(req.name)
        if key in seen:
            continue
        dist = md.distribution(req.name)
        seen[key] = dist
        todo.extend(dist.requires or [])
    return seen


def declared_licences(dist: md.Distribution) -> set[str]:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        tokens = re.split(r"[()\s]+", expression)
        return {t.lower() for t in tokens if t and t.upper() not in {"AND", "OR", "WITH"}}
    classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return {LICENCE_NAMES.get(c.lower(), c) for c in classifiers}
    text = (meta.get("License") or "").strip()
    parts = [p.strip().lower() for p in re.split(r",|/|\bor\b|\band\b", text) if p.strip()]
    if canonicalize_name(meta["Name"]) == "pypdfium2":
        parts = [p for p in parts if p != PYPDFIUM2_BUNDLED]
    return {LICENCE_NAMES.get(p, p) for p in parts}


@pytest.mark.ac("MAIN-AC3")
def test_wheel_and_sdist_declare_mit_and_include_licence(built: Built) -> None:
    licence_text = (REPO / "LICENSE").read_text(encoding="utf-8")
    meta = wheel_metadata(built.wheel)
    assert meta["License-Expression"] == "MIT"
    assert meta.get_all("License-File") == ["LICENSE"]
    with zipfile.ZipFile(built.wheel) as zf:
        (lic,) = [n for n in zf.namelist() if n.endswith(".dist-info/licenses/LICENSE")]
        assert zf.read(lic).decode("utf-8") == licence_text

    with tarfile.open(built.sdist) as tf:
        names = tf.getnames()
        (pkg_info,) = [n for n in names if n.count("/") == 1 and n.endswith("/PKG-INFO")]
        (lic_name,) = [n for n in names if n.count("/") == 1 and n.endswith("/LICENSE")]
        pkg_file = tf.extractfile(pkg_info)
        lic_file = tf.extractfile(lic_name)
        assert pkg_file is not None and lic_file is not None
        sdist_meta = email.parser.Parser().parsestr(pkg_file.read().decode("utf-8"))
        assert sdist_meta["License-Expression"] == "MIT"
        assert lic_file.read().decode("utf-8") == licence_text


@pytest.mark.ac("MAIN-AC3")
def test_wheel_bundles_no_pdfium_binary(built: Built) -> None:
    with zipfile.ZipFile(built.wheel) as zf:
        names = zf.namelist()
    assert names  # the wheel was read
    offending = [
        n for n in names if "pdfium" in n.lower() or n.endswith((".so", ".dylib", ".dll", ".pyd"))
    ]
    assert offending == []


@pytest.mark.ac("MAIN-AC3")
def test_runtime_dependencies_have_only_allowed_licences(built: Built) -> None:
    requires = wheel_metadata(built.wheel).get_all("Requires-Dist") or []
    closure = runtime_closure(requires)
    assert "pypdfium2" in closure  # the closure really follows the declared dependencies
    bad = {
        name: sorted(lics)
        for name, dist in closure.items()
        if not (lics := declared_licences(dist)) or not lics <= ALLOWED_SPDX
    }
    assert bad == {}


@pytest.mark.ac("MAIN-AC3")
def test_installed_pypdfium2_ships_pdfium_notices() -> None:
    files = [str(f) for f in md.distribution("pypdfium2").files or []]
    assert any(f.endswith(("libpdfium.so", "libpdfium.dylib", "pdfium.dll")) for f in files)
    notices = {Path(f).name for f in files if "/BUILD_LICENSES/" in f}
    for notice in ("pdfium.txt", "freetype.txt", "icu.txt", "libjpeg_turbo.ijg"):
        assert notice in notices


@pytest.mark.ac("EPUB-AC2")
def test_neither_ebooklib_nor_pymupdf_is_a_runtime_dependency() -> None:
    closure = runtime_closure(md.distribution("pdf2epub").requires or [])
    assert "lxml" in closure  # the EPUB writer's own dependency is seen
    assert FORBIDDEN_EPUB_LIBRARIES.isdisjoint(closure)


def test_wheel_ships_the_event_schema(built: Built) -> None:
    """Local AC of #26: the JSON Schema for v1 events ships inside the package (API-R26)."""
    with zipfile.ZipFile(built.wheel) as zf:
        schema = json.loads(zf.read("pdf2epub/schema/events.v1.json"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["v"] == {"const": 1}


def test_package_reports_the_version_declared_in_pyproject() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert pdf2epub.__version__ == project["version"]
