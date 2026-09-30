"""In-process background jobs with progress events (consumed by the SSE endpoint)."""

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
        self.keep = keep
        self.lock = threading.Lock()

    def submit(self, kind: str, fn: Callable[[Job], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self.lock:
            self.jobs[job.id] = job
            if len(self.jobs) > self.keep:
                for old in sorted(self.jobs.values(), key=lambda j: j.created)[: len(self.jobs) - self.keep]:
                    if old.status in ("done", "error"):
                        self.jobs.pop(old.id, None)

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

        self.pool.submit(run)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)
