"""Cancellation (API §3)."""


class CancelToken:
    """Set once to cancel a batch.

    ``cancel()`` only assigns a flag: no lock is taken, so it is safe to call from any
    thread or from a signal handler (API-R6).
    """

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled
