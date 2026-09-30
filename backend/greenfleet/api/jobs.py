"""In-process background jobs with progress events (consumed by the SSE endpoint).

Jobs submitted with a ``key`` (a canonical description of the request) are shared: an identical request
returns the job already running or finished instead of computing again. On a small free-tier host this
keeps repeat visits instant and stops a burst of identical clicks from queueing identical work.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"          # queued | running | done | error
    progress: float = 0.0
    events: list[dict] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    key: str | None = None
    pinned: bool = False            # never evicted (warm-up runs of the default scenario)
    cond: threading.Condition = field(default_factory=threading.Condition, repr=False)

    def emit(self, event: dict) -> None:
        with self.cond:
            self.events.append(event)
            self.cond.notify_all()

    def summary(self) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "progress": self.progress,
                "error": self.error, "events": len(self.events)}


class JobManager:
    def __init__(self, workers: int = 2, keep: int = 50):
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.jobs: dict[str, Job] = {}
        self.by_key: dict[str, str] = {}
        self.keep = keep
        self.lock = threading.Lock()

    def _evict(self) -> None:
        excess = len(self.jobs) - self.keep
        if excess <= 0:
            return
        done = [j for j in self.jobs.values() if j.status in ("done", "error") and not j.pinned]
        for old in sorted(done, key=lambda j: j.created)[:excess]:
            self.jobs.pop(old.id, None)
            if old.key and self.by_key.get(old.key) == old.id:
                self.by_key.pop(old.key, None)

    def pending(self) -> int:
        return sum(j.status in ("queued", "running") for j in self.jobs.values())

    def submit(self, kind: str, fn: Callable[[Job], Any], key: str | None = None,
               pinned: bool = False) -> tuple[Job, bool]:
        """Run ``fn(job)`` in the pool; returns (job, reused). A failed job is never reused."""
        with self.lock:
            if key is not None and key in self.by_key:
                prev = self.jobs.get(self.by_key[key])
                if prev is not None and prev.status != "error":
                    return prev, True
            job = Job(id=uuid.uuid4().hex[:12], kind=kind, key=key, pinned=pinned)
            ahead = self.pending()
            self.jobs[job.id] = job
            if key is not None:
                self.by_key[key] = job.id
            self._evict()
        if ahead:
            job.emit({"type": "queued", "ahead": ahead})

        def run():
            job.status = "running"
            job.emit({"type": "status", "status": "running"})
            try:
                job.result = fn(job)
                job.status, job.progress = "done", 1.0
                job.emit({"type": "done"})
            except Exception as exc:  # surfaced to the client
                job.status, job.error = "error", f"{exc.__class__.__name__}: {exc}"
                job.emit({"type": "error", "error": job.error, "trace": traceback.format_exc(limit=3)})
            finally:
                job.finished = time.time()

        self.pool.submit(run)
        return job, False

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)
