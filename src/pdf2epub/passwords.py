"""The password-provider protocol the core asks for candidate passwords (API §4).

Only the shapes live here so far; the rules for trying candidates (PWD) arrive with
the password tickets.
"""

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple, Protocol

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


class Candidate(NamedTuple):
    secret: Secret
    source: SourceLabel


class PasswordProvider(Protocol):
    """Supplies candidate passwords for a file, and optionally a prompt."""

    prompt: Callable[[Path, int], Secret | None] | None

    def candidates(self, path: Path) -> list[Candidate]: ...
