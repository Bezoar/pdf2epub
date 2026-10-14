"""Errors the core raises to its caller."""


class UsageError(Exception):
    """The run cannot start: invalid or conflicting inputs or options (BAT-R25).

    Raised before any event is emitted and before anything is converted; the CLI prints
    the reason and exits with code 2. The message is the reason.
    """
