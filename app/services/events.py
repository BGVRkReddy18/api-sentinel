"""In-process publish/subscribe bus that feeds the /ws WebSocket stream.

Each connected client gets a bounded queue. A slow client never blocks the monitor: when its
queue is full the oldest event is dropped (the UI resyncs from the REST API on reconnect).
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.clock import utcnow


class EventBus:
    def __init__(self, queue_size: int = 256) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        event = {"type": event_type, "ts": utcnow().isoformat(), "data": data}
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()  # drop the oldest event for this slow consumer
                except asyncio.QueueEmpty:  # pragma: no cover
                    pass
            queue.put_nowait(event)
