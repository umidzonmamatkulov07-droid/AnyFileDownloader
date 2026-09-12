"""Thread-safe sequential request queue for the persistent desktop process."""

from __future__ import annotations

import copy
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


TERMINAL_STATES = {"completed", "failed", "cancelled"}


@dataclass
class DownloadJob:
    request: dict
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "queued"
    progress: float = 0.0
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0

    def snapshot(self) -> "DownloadJob":
        return copy.deepcopy(self)


class SequentialDownloadQueue:
    """Retain all jobs while processing exactly one request at a time."""

    def __init__(
        self,
        worker: Callable[[DownloadJob], Any],
        on_change: Optional[Callable[[DownloadJob], None]] = None,
    ):
        self.worker = worker
        self.on_change = on_change or (lambda _job: None)
        self._pending: queue.Queue[Optional[str]] = queue.Queue()
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stopping.clear()
            self._thread = threading.Thread(target=self._run, name="afd-download-queue", daemon=True)
            self._thread.start()

    def enqueue(self, request: dict) -> DownloadJob:
        job = DownloadJob(copy.deepcopy(request))
        with self._lock:
            self._jobs[job.id] = job
        self._pending.put(job.id)
        self._notify(job)
        return job.snapshot()

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "queued":
                return False
            job.status = "cancelled"
            job.finished_at = time.time()
            snapshot = job.snapshot()
        self.on_change(snapshot)
        return True

    def update_progress(self, job_id: str, progress: float) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "active":
                return
            job.progress = min(100.0, max(0.0, float(progress)))
            snapshot = job.snapshot()
        self.on_change(snapshot)

    def jobs(self) -> list[DownloadJob]:
        with self._lock:
            return [job.snapshot() for job in self._jobs.values()]

    def active_job(self) -> Optional[DownloadJob]:
        with self._lock:
            for job in self._jobs.values():
                if job.status == "active":
                    return job.snapshot()
        return None

    def wait_idle(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                busy = any(job.status in {"queued", "active"} for job in self._jobs.values())
            if not busy:
                return True
            time.sleep(0.01)
        return False

    def stop(self, timeout: float = 2.0) -> None:
        self._stopping.set()
        self._pending.put(None)
        thread = self._thread
        if thread:
            thread.join(timeout=timeout)

    def _notify(self, job: DownloadJob) -> None:
        self.on_change(job.snapshot())

    def _run(self) -> None:
        while not self._stopping.is_set():
            job_id = self._pending.get()
            if job_id is None:
                return
            with self._lock:
                job = self._jobs.get(job_id)
                if not job or job.status == "cancelled":
                    continue
                job.status = "active"
                job.started_at = time.time()
                active_snapshot = job.snapshot()
            self.on_change(active_snapshot)
            try:
                result = self.worker(active_snapshot)
            except Exception as error:
                with self._lock:
                    job = self._jobs[job_id]
                    job.status = "failed"
                    job.error = str(error)
                    job.finished_at = time.time()
                    terminal_snapshot = job.snapshot()
            else:
                with self._lock:
                    job = self._jobs[job_id]
                    job.status = "completed"
                    job.progress = 100.0
                    job.result = result
                    job.finished_at = time.time()
                    terminal_snapshot = job.snapshot()
            self.on_change(terminal_snapshot)

