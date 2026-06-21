"""Span tracer — emite eventos de seguimiento al bus SSE."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional


def _publish(payload: dict) -> None:
    try:
        from orchestrator.sse import BUS
        BUS.publish("trace", json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


@contextmanager
def span(name: str, run_id: Optional[int] = None, detail: Optional[str] = None):
    ts = datetime.now(timezone.utc).isoformat()
    _publish({"name": name, "status": "running", "run_id": run_id, "detail": detail, "ts": ts})
    t0 = time.monotonic()
    try:
        yield
        elapsed = int((time.monotonic() - t0) * 1000)
        _publish({
            "name": name, "status": "done", "run_id": run_id,
            "duration_ms": elapsed, "ts": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        _publish({
            "name": name, "status": "error", "run_id": run_id,
            "duration_ms": elapsed, "error": str(exc)[:200],
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        raise
