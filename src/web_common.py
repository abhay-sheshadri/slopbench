"""Shared server helpers for the viewer's web tabs (studio, proposals, blue team).

These centralize three things that were previously copy-pasted (and drifting)
across the tab modules:

* :func:`serve` — the per-tab request dispatch (path match + GET/POST routing +
  "never let a handler kill the server" exception trap).
* :func:`reply` — the JSON error-status convention: a result carrying an
  ``error`` is sent as HTTP 4xx, so the client never receives a failure
  disguised as a 200 (the root cause of "the button does nothing" bugs).
* :class:`BatchRunner` — a concurrency-capped, queue-backed "run all" so the
  blue-team audits and the studio drafts share one batch model instead of each
  reinventing (or omitting) throttling.

The client-side counterpart (a single shared ``api()`` fetch helper) lives in
``src.theme`` as ``API_JS``.
"""

from __future__ import annotations

import collections
import threading
from typing import Callable
from urllib.parse import urlparse


def serve(h, method: str, prefix: str, get_fn, post_fn) -> bool:
    """Dispatch one request for a tab mounted at ``prefix``.

    Returns True if the path was ours (and thus handled), False so the caller
    can let another tab try. Any unexpected exception becomes a 500 rather than
    crashing the server thread.
    """
    parsed = urlparse(h.path)
    if parsed.path != prefix and not parsed.path.startswith(prefix + "/"):
        return False
    path = parsed.path[len(prefix) :] or "/"
    try:
        if method == "GET":
            get_fn(h, path, parsed.query)
        else:
            post_fn(h, path)
    except (BrokenPipeError, ConnectionError, OSError):
        pass
    except Exception as exc:  # noqa: BLE001 - never let a handler kill the server
        try:
            h._json({"error": f"{type(exc).__name__}: {exc}"}, code=500)
        except Exception:
            pass
    return True


def reply(h, result, code: int | None = None) -> None:
    """Send a handler result as JSON, inferring the HTTP status.

    A dict carrying a truthy ``error`` defaults to HTTP 400 so a failed action
    is never delivered as a 200 (which the client would read as success). Pass
    ``code`` to override (e.g. 404/409 for a more specific failure).
    """
    if code is None:
        code = 400 if isinstance(result, dict) and result.get("error") else 200
    h._json(result, code=code)


class BatchRunner:
    """Concurrency-capped, queue-backed "run all" for streamable per-run jobs.

    Generic over *how* a job is started and *how many* jobs are currently live,
    so different tabs can share one batch model: enqueue every target, run up to
    ``cap`` at once, advance as slots free (call :meth:`advance` from a pump
    loop), and stop the whole batch in one call.

    Thread-safe; the caller owns the actual job registry and liveness check.
    """

    def __init__(
        self,
        cap: int,
        start_one: Callable[[str], object],
        live_count: Callable[[], int],
    ) -> None:
        self.cap = max(1, cap)
        self._start_one = start_one  # (rel) -> starts a job (return ignored)
        self._live_count = live_count  # () -> number of jobs live right now
        self._queue: "collections.deque[str]" = collections.deque()
        self._members: set[str] = set()  # rels belonging to the current batch
        self._lock = threading.Lock()

    def start_all(self, rels: list[str]) -> dict:
        with self._lock:
            self._members = set(rels)
            self._queue.clear()
            self._queue.extend(rels)
        self.advance()
        return {"ok": True, "queued": len(rels)}

    def advance(self) -> None:
        """Start queued jobs up to the concurrency cap. Idempotent; cheap."""
        while True:
            with self._lock:
                if not self._queue or self._live_count() >= self.cap:
                    return
                rel = self._queue.popleft()
            self._start_one(rel)

    def stop_all(self, stop_member: Callable[[str], None]) -> dict:
        with self._lock:
            self._queue.clear()
            members = list(self._members)
            self._members.clear()
        for rel in members:
            stop_member(rel)
        return {"ok": True}

    def discard(self, rel: str) -> None:
        """Drop a run from the batch + queue (e.g. when it is deleted)."""
        with self._lock:
            self._members.discard(rel)
            if rel in self._queue:
                kept = [r for r in self._queue if r != rel]
                self._queue.clear()
                self._queue.extend(kept)

    def queued(self) -> set[str]:
        with self._lock:
            return set(self._queue)

    def members(self) -> set[str]:
        with self._lock:
            return set(self._members)

    def status(self, running_members: int) -> dict:
        """Batch summary for the UI. ``running_members`` = how many of this
        batch's runs are live right now (the caller knows its registry)."""
        with self._lock:
            return {
                "batch": bool(self._queue) or running_members > 0,
                "active": running_members,
                "queued": len(self._queue),
            }
