"""The Tesseract adapter (OCR-R11, OCR-R14, OCR-R15).

Each attempt runs the ``tesseract`` program as its own subprocess: the page image goes in
on stdin as PNG, and the words come back on stdout as TSV, read by ``parse_tsv``. The
process is killed when the attempt's deadline passes (``EngineTimeout``); a crash or a
non-zero exit is ``EngineFailed``. Either costs only that page.

The program runs with ``OMP_THREAD_LIMIT=1`` (pages are OCR'd one at a time per
conversion; conversions run side by side) and without any password environment variable
(PWD-R25). Nothing it is given on its command line comes from a password.
"""

import contextlib
import io
import logging
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from pdf2epub.ocr.engine import (
    Capabilities,
    EngineFailed,
    EngineTimeout,
    LayoutHint,
    OcrLine,
    OcrPageResult,
    OcrRequest,
    Word,
)
from pdf2epub.options import OcrOptions
from pdf2epub.passwords import PASSWORD_VARIABLES

log = logging.getLogger(__name__)

PSM: Mapping[LayoutHint, int] = {"PAGE": 3, "BLOCK": 6, "LINE": 7, "SPARSE": 11}
"""Tesseract's page segmentation mode for each layout hint (OCR-R12, OCR-R20)."""
PROBE_TIMEOUT = 30.0
"""Seconds ``tesseract --version`` or ``--list-langs`` may take."""
_WORD, _LINE = 5, 4
"""TSV ``level`` values."""


def environment() -> dict[str, str]:
    """The environment Tesseract runs in: this process's, without the password variables,
    with one OpenMP thread (OCR-R14)."""
    env = {name: value for name, value in os.environ.items() if name not in PASSWORD_VARIABLES}
    env["OMP_THREAD_LIMIT"] = "1"
    return env


@dataclass
class Tesseract:
    """An ``OcrEngine`` that runs the ``tesseract`` program at ``program``."""

    program: Path
    tessdata_dir: Path | None = None
    _capabilities: Capabilities | None = field(default=None, init=False, repr=False)
    _languages: frozenset[str] = field(default=frozenset(), init=False, repr=False)

    def capabilities(self) -> Capabilities:
        """Tesseract's version, from ``--version``, and whether its orientation data
        (``osd``) is installed, from ``--list-langs``; asked once."""
        if self._capabilities is None:
            version = _version(self._probe(["--version"]))
            languages = self._languages = _languages(self._probe(["--list-langs"]))
            self._capabilities = Capabilities(
                name="tesseract",
                version=version,
                granularities=("word", "line"),
                confidence_scale="0-100",
                osd="osd" in languages,
                licence="Apache-2.0",
            )
        return self._capabilities

    def languages(self) -> frozenset[str]:
        """The languages Tesseract has data for, from ``--list-langs``; asked once, with
        the capabilities."""
        self.capabilities()
        return self._languages

    def parameters(self) -> frozenset[str] | None:
        """The names of Tesseract's parameters, from ``--print-parameters``; None if it
        lists none."""
        lines = self._probe(["--print-parameters"]).splitlines()
        # A heading line (``Tesseract parameters:``), then one ``name value description``
        # line per parameter.
        names = {line.split()[0] for line in lines if line.split() and not line.endswith(":")}
        return frozenset(names) or None

    def recognise(self, request: OcrRequest) -> OcrPageResult:
        image = io.BytesIO()
        request.image.save(image, format="PNG", dpi=(request.dpi, request.dpi))
        args = ["stdin", "stdout", "--dpi", str(request.dpi), "--psm"]
        args += [str(PSM[request.layout_hint]), "-l", request.languages]
        for key, value in request.engine_options.items():
            args += ["-c", f"{key}={value}"]
        stdout, stderr = self._run([*args, "tsv"], image.getvalue(), request.deadline)
        warnings = tuple(line for line in stderr.splitlines() if line.strip())
        for warning in warnings:
            log.debug("tesseract: %s", warning)
        return OcrPageResult(lines=parse_tsv(stdout), warnings=warnings)

    def orientation(self, image: Image.Image, dpi: int, deadline: float) -> int:
        """The clockwise turn that makes ``image`` upright, by Tesseract's orientation
        detection (``--psm 0``); 0 when it can't tell (too little text, say)."""
        data = io.BytesIO()
        image.save(data, format="PNG", dpi=(dpi, dpi))
        args = ["stdin", "stdout", "--dpi", str(dpi), "--psm", "0"]
        try:
            stdout, _ = self._run(args, data.getvalue(), deadline)
        except EngineFailed as error:
            log.debug("tesseract orientation: %s", error)
            return 0
        match = re.search(r"^Rotate:\s*(\d+)", stdout, re.MULTILINE)
        rotate = int(match.group(1)) if match else 0
        return rotate if rotate in (90, 180, 270) else 0

    def _probe(self, args: Sequence[str]) -> str:
        """The program's output for ``args``, or "" if it can't answer."""
        try:
            stdout, stderr = self._run(args, b"", time.monotonic() + PROBE_TIMEOUT)
        except (EngineFailed, EngineTimeout) as error:
            log.debug("tesseract %s: %s", " ".join(args), error)
            return ""
        # Older versions print their version and language list on stderr.
        return stdout or stderr

    def _run(self, args: Sequence[str], stdin: bytes, deadline: float) -> tuple[str, str]:
        """Run the program with ``args``, feeding it ``stdin``; its stdout and stderr. The
        process (and anything it started) is killed at ``deadline``."""
        command = [str(self.program)]
        if self.tessdata_dir is not None:
            command += ["--tessdata-dir", str(self.tessdata_dir)]
        command += args
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment(),
                start_new_session=True,
            )
        except OSError as error:
            raise EngineFailed(f"could not start {self.program}: {error}") from error
        try:
            out, err = process.communicate(stdin, timeout=max(deadline - time.monotonic(), 0))
        except subprocess.TimeoutExpired:
            _kill(process)
            raise EngineTimeout(f"{self.program} ran past its deadline and was stopped") from None
        except BaseException:
            _kill(process)
            raise
        stderr = err.decode("utf-8", errors="replace")
        if process.returncode != 0:
            last = stderr.strip().splitlines()[-1:] or [""]
            raise EngineFailed(f"{self.program} exited with status {process.returncode}: {last[0]}")
        return out.decode("utf-8", errors="replace"), stderr


def find_tesseract(options: OcrOptions) -> Tesseract | None:
    """Tesseract at ``options.tesseract_path``, or on ``PATH`` when that isn't set; None
    when there is no such program."""
    if options.tesseract_path is not None:
        program = options.tesseract_path
        if not (program.is_file() and os.access(program, os.X_OK)):
            return None
        return Tesseract(program, options.tessdata_dir)
    found = shutil.which("tesseract")
    return Tesseract(Path(found), options.tessdata_dir) if found else None


def _kill(process: "subprocess.Popen[bytes]") -> None:
    """Kill ``process`` and its process group, and reap it."""
    with contextlib.suppress(ProcessLookupError):  # it may have exited on its own by now
        os.killpg(process.pid, signal.SIGKILL)
    process.communicate()


def _languages(text: str) -> frozenset[str]:
    """The language codes in ``tesseract --list-langs`` output: every line after the
    heading (``List of available languages in "…" (3):``)."""
    lines = text.splitlines()
    starts = [i + 1 for i, line in enumerate(lines) if line.startswith("List of available")]
    return frozenset(line.strip() for line in lines[starts[-1] if starts else 0 :] if line.strip())


def _version(text: str) -> str:
    """The version from ``tesseract --version`` output (``tesseract 5.3.4``)."""
    for line in text.splitlines():
        name, _, version = line.strip().partition(" ")
        if name.lower() == "tesseract" and version:
            return version.split()[0].removeprefix("v")
    return "unknown"


def parse_tsv(text: str) -> tuple[OcrLine, ...]:
    """The lines of words in Tesseract's TSV output, in its reading order. A word's
    confidence is its raw confidence ÷ 100 (OCR-R15); a line's height is the height of
    Tesseract's line box."""
    rows = text.splitlines()
    if not rows or not rows[0].startswith("level\t"):
        raise EngineFailed("tesseract gave no TSV output")
    columns = rows[0].split("\t")
    lines: dict[tuple[str, ...], tuple[list[Word], list[float]]] = {}
    for row in rows[1:]:
        values = dict(zip(columns, row.split("\t"), strict=False))
        try:
            level = int(values["level"])
            key = tuple(values[k] for k in ("page_num", "block_num", "par_num", "line_num"))
            left, top = float(values["left"]), float(values["top"])
            width, height = float(values["width"]), float(values["height"])
            raw = float(values["conf"])
        except (KeyError, ValueError):
            continue
        text_ = values.get("text", "").strip()
        if level == _LINE:
            lines.setdefault(key, ([], []))[1].append(height)
        elif level == _WORD and text_ and raw >= 0:
            words = lines.setdefault(key, ([], []))[0]
            confidence = raw / 100
            words.append(Word(text_, left, top, left + width, top + height, confidence, raw))
    result = []
    for words, heights in lines.values():
        if words:
            height = (
                heights[0] if heights else max(w.bottom for w in words) - min(w.top for w in words)
            )
            result.append(OcrLine(tuple(words), height))
    return tuple(result)
