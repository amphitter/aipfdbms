"""In-process domain events for the realtime gateway. Not a database poller."""

from __future__ import annotations

import queue
import threading
from typing import Any

_lock = threading.Lock()
_subscribers: list[queue.Queue] = []


def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=200)
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)


def client_count() -> int:
    with _lock:
        return len(_subscribers)


def publish(event: str, data: dict[str, Any] | None = None) -> None:
    payload = {"event": event, "data": data or {}}
    with _lock:
        targets = list(_subscribers)
    for q in targets:
        try:
            q.put_nowait(payload)
        except queue.Full:
            try:
                q.get_nowait()
                q.put_nowait(payload)
            except Exception:
                pass
