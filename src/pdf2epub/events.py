"""The event stream (API §8).

An event is a plain JSON-ready ``dict``: the envelope ``v``, ``type`` and ``t`` (API-R16)
followed by the type's fields from the v1 catalogue (API-R17). The core hands each one to
the caller's sink, from the thread that called ``run_batch`` (API-R4).
"""

import time
from collections.abc import Callable
from typing import Any

PROTOCOL_VERSION = 1

Event = dict[str, Any]
EventSink = Callable[[Event], None]


class Emitter:
    """Stamps events with the envelope and passes them to the sink.

    ``t`` is seconds since the emitter was created (the batch start), from the monotonic
    clock, so it never decreases across the stream.
    """

    def __init__(self, sink: EventSink) -> None:
        self._sink = sink
        self._start = time.monotonic()

    def emit(self, type_: str, **fields: Any) -> Event:
        elapsed = round(time.monotonic() - self._start, 6)
        event: Event = {"v": PROTOCOL_VERSION, "type": type_, "t": elapsed, **fields}
        self._sink(event)
        return event
