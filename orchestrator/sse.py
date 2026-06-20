"""SSEBus: fan-out de eventos en tiempo real para el dashboard."""

from __future__ import annotations

import queue
import threading


class SSEBus:
    def __init__(self) -> None:
        self._subscribers: list[queue.Queue[str]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s is not q]

    def publish(self, event_type: str, data: str) -> None:
        msg = f"event: {event_type}\ndata: {data}\n\n"
        with self._lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)


BUS: SSEBus = SSEBus()
