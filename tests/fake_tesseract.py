"""Fake ``tesseract`` programs, for tests of how the Tesseract adapter runs its subprocess
(OCR-R14, OCR-R22, OCR-R23, PWD-R25).

Each fake is a small Python script made executable, run by this interpreter in isolated
mode (``-I``), so nothing in the test's environment changes how it starts. It answers
``--version`` and ``--list-langs`` like Tesseract 5.3.4 with English and orientation data,
``--print-parameters`` with a few of Tesseract's parameters (``PARAMETERS``), and does
``body`` for every other call. Given a ``log``, it first appends its arguments to that file
as a JSON line, on every call. ``body`` is Python run with ``argv``, ``os``,
``sys``, ``time`` and ``json`` imported.
"""

import os
import stat
import sys
from pathlib import Path

HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
)

SLEEP_FOREVER = "time.sleep(3600)"
EXIT_1 = "sys.exit(1)"
NO_WORDS = f"print({HEADER!r})"
PARAMETERS = ("preserve_interword_spaces", "tessedit_char_whitelist", "user_defined_dpi")
"""The parameters the fake's ``--print-parameters`` lists."""


def record(path: Path) -> str:
    """A body that appends its argv and environment to ``path`` as a JSON line, then
    reports no words."""
    return (
        f"with open({str(path)!r}, 'a', encoding='utf-8') as out:\n"
        "    out.write(json.dumps({'argv': argv, 'env': dict(os.environ)}) + '\\n')\n"
        f"{NO_WORDS}"
    )


def started(path: Path, body: str) -> str:
    """``body``, run after writing the fake's process ID and start time (``time.time()``)
    to ``path`` as a JSON line."""
    return (
        f"with open({str(path)!r}, 'a', encoding='utf-8') as out:\n"
        "    out.write(json.dumps({'pid': os.getpid(), 'time': time.time()}) + '\\n')\n"
        f"{body}"
    )


def fake_tesseract(
    folder: Path, body: str, log: Path | None = None, parameters: tuple[str, ...] = PARAMETERS
) -> Path:
    """Write a fake ``tesseract`` into ``folder`` and return its path. With ``log``, every
    call appends its arguments (without the program) to ``log`` as a JSON line.
    ``--print-parameters`` lists ``parameters``."""
    folder.mkdir(parents=True, exist_ok=True)
    program = folder / "tesseract"
    logging = (
        f"with open({str(log)!r}, 'a', encoding='utf-8') as out:\n"
        "    out.write(json.dumps(argv[1:]) + '\\n')\n"
        if log is not None
        else ""
    )
    listing = "".join(f"{name}\\t0\\tA parameter\\n" for name in parameters)
    program.write_text(
        f"#!{sys.executable} -I\n"
        "import json, os, sys, time\n"
        "argv = sys.argv\n"
        f"{logging}"
        "if '--print-parameters' in argv:\n"
        f"    print('Tesseract parameters:\\n{listing}', end='')\n"
        "    sys.exit(0)\n"
        "if '--version' in argv:\n"
        "    print('tesseract 5.3.4')\n"
        "    sys.exit(0)\n"
        "if '--list-langs' in argv:\n"
        "    print('List of available languages in \"/fake\" (2):\\neng\\nosd')\n"
        "    sys.exit(0)\n"
        f"{body}\n",
        encoding="utf-8",
    )
    program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return program


def alive(pid: int) -> bool:
    """Whether process ``pid`` still exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
