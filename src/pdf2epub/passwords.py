"""Candidate passwords: the ``PasswordProvider`` protocol the core asks for them
(API §4), and ``SourcePasswordProvider``, which builds them from the user's password
sources in the trial order of PWD-R12, with their source labels (PWD-R16, PWD-R18).

Password values are only ever held as ``Secret`` (API-R8).
"""

import fnmatch
import os
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, Protocol

from pdf2epub.errors import UsageError

SourceLabel = str


class Secret:
    """Wraps one password value. It is reachable only through ``reveal()``; ``str`` and
    ``repr`` give ``***`` (API-R8)."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return "***"

    def __repr__(self) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        # Two candidates with the same value are one candidate (PWD-R12).
        if not isinstance(other, Secret):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash((Secret, self._value))


class Candidate(NamedTuple):
    secret: Secret
    source: SourceLabel


class PasswordProvider(Protocol):
    """Supplies candidate passwords for a file, and optionally a prompt."""

    prompt: Callable[[Path, int], Secret | None] | None

    def candidates(self, path: Path) -> list[Candidate]: ...


Prompt = Callable[[Path, int], Secret | None]


@dataclass(frozen=True)
class PasswordSources:
    """The raw password sources a front end gathers (PWD-R18). It never orders or
    filters them: ``SourcePasswordProvider`` does."""

    map_file: Path | None = None
    """The password map (TOML), or None."""
    values: Sequence[Secret] = field(default_factory=list)
    """Command-line values, in the order given."""
    env_value: Secret | None = None
    """The environment value, or None."""
    password_file: Path | None = None
    """The password file, or None."""
    prompt: Prompt | None = None
    """A prompt function ``(path, attempt) -> Secret | None``, or None."""


class SourcePasswordProvider:
    """The core's ``PasswordProvider``: candidates from the password map, the
    command-line values, the environment and the password file, in that order, each
    labelled with its source, a repeated value kept once under its first label (PWD-R12,
    PWD-R16).

    The map and the file are read when the provider is built; one that can't be read or
    isn't valid raises ``UsageError`` (PWD-R14, PWD-R15)."""

    def __init__(self, sources: PasswordSources) -> None:
        self.sources = sources
        self.prompt: Prompt | None = sources.prompt
        self._map = _read_map(sources.map_file) if sources.map_file is not None else []
        self._map_dir = (
            Path(os.path.abspath(sources.map_file.parent)) if sources.map_file is not None else None
        )
        self._lines = (
            _read_password_file(sources.password_file) if sources.password_file is not None else []
        )

    def candidates(self, path: Path) -> list[Candidate]:
        found: list[Candidate] = []
        found.extend(self._map_candidates(path))
        found.extend(
            Candidate(value, f"cli #{n}") for n, value in enumerate(self.sources.values, 1)
        )
        if self.sources.env_value is not None:
            found.append(Candidate(self.sources.env_value, "env"))
        found.extend(Candidate(value, f"file:line {n}") for n, value in self._lines)
        return distinct(found)

    def _map_candidates(self, path: Path) -> list[Candidate]:
        """The map's entries for ``path``: an entry for exactly that path first, then
        every glob entry that matches it, in file order (PWD-R12)."""
        if self._map_dir is None:
            return []
        target = Path(os.path.abspath(path))
        exact = [e for e in self._map if Path(os.path.abspath(self._map_dir / e[0])) == target]
        globs = [
            e
            for e in self._map
            if e not in exact and _is_glob(e[0]) and _glob_matches(e[0], self._map_dir, target)
        ]
        return [
            Candidate(value, f'map:"{key}"') for key, values in exact + globs for value in values
        ]


def distinct(candidates: Sequence[Candidate]) -> list[Candidate]:
    """``candidates`` with each repeated value dropped, so a value keeps the label of its
    first appearance (PWD-R12)."""
    seen: set[Secret] = set()
    kept: list[Candidate] = []
    for candidate in candidates:
        if candidate.secret not in seen:
            seen.add(candidate.secret)
            kept.append(candidate)
    return kept


def _read_map(path: Path) -> list[tuple[str, list[Secret]]]:
    try:
        with path.open("rb") as file:
            table = tomllib.load(file)
    except OSError as error:
        raise UsageError(f"can't read the password map {path}: {error.strerror or error}") from None
    except UnicodeDecodeError:
        raise UsageError(f"the password map {path} isn't UTF-8 text") from None
    except tomllib.TOMLDecodeError as error:
        # The decoder's message names a position, never the file's contents.
        raise UsageError(f"the password map {path} isn't valid TOML: {error}") from None
    entries: list[tuple[str, list[Secret]]] = []
    for key, value in table.items():
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise UsageError(
                f'the password map {path}: the value for "{key}" must be a string '
                "or a list of strings"
            )
        entries.append((key, [Secret(v) for v in values]))
    return entries


def _read_password_file(path: Path) -> list[tuple[int, Secret]]:
    """The file's non-empty lines with their 1-based line numbers (PWD-R15)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise UsageError(
            f"can't read the password file {path}: {error.strerror or error}"
        ) from None
    except UnicodeDecodeError:
        raise UsageError(f"the password file {path} isn't UTF-8 text") from None
    # Only "\n" and "\r\n" end a line: any other character, even one str.splitlines()
    # treats as a break, is part of the password as written.
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    # A blank line is an empty one; a line of spaces is a password like any other.
    return [(number, Secret(line)) for number, line in enumerate(lines, start=1) if line]


def _is_glob(key: str) -> bool:
    return any(char in key for char in "*?[")


def _glob_matches(key: str, base: Path, target: Path) -> bool:
    """True when ``target`` matches the glob ``key``, taken relative to ``base``, one
    path segment per pattern segment."""
    pattern = Path(os.path.abspath(base / key)).parts
    parts = target.parts
    return len(pattern) == len(parts) and all(
        fnmatch.fnmatchcase(part, segment) for part, segment in zip(parts, pattern, strict=True)
    )
