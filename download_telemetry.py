"""Real transfer telemetry and throughput-to-HUD motion mapping."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TelemetrySnapshot:
    active: bool
    downloaded_bytes: int
    total_bytes: int
    speed_bps: float
    progress_percent: Optional[float]
    elapsed_seconds: float
    eta_seconds: Optional[float]


class DownloadTelemetry:
    """Smooth measured throughput while retaining truthful byte/progress values."""

    def __init__(self, smoothing_seconds: float = 1.25):
        self.smoothing_seconds = max(0.1, float(smoothing_seconds))
        self._lock = threading.RLock()
        self.reset()

    def reset(self, now: Optional[float] = None) -> None:
        with self._lock:
            current = time.monotonic() if now is None else float(now)
            self.active = False
            self.downloaded_bytes = 0
            self.total_bytes = 0
            self.speed_bps = 0.0
            self.started_at = current
            self.updated_at = current

    def start(self, total_bytes: int = 0, now: Optional[float] = None) -> None:
        with self._lock:
            self.reset(now)
            self.active = True
            self.total_bytes = max(0, int(total_bytes or 0))

    def update(
        self,
        downloaded_bytes: int,
        total_bytes: int = 0,
        speed_bps: Optional[float] = None,
        now: Optional[float] = None,
    ) -> TelemetrySnapshot:
        with self._lock:
            current = time.monotonic() if now is None else float(now)
            if not self.active:
                self.start(total_bytes, current)
            elapsed_since_update = max(0.001, current - self.updated_at)
            downloaded = max(0, int(downloaded_bytes or 0))
            measured = (
                max(0.0, float(speed_bps))
                if speed_bps is not None
                else max(0.0, (downloaded - self.downloaded_bytes) / elapsed_since_update)
            )
            alpha = 1.0 - math.exp(-elapsed_since_update / self.smoothing_seconds)
            self.speed_bps += alpha * (measured - self.speed_bps)
            self.downloaded_bytes = downloaded
            if total_bytes:
                self.total_bytes = max(0, int(total_bytes))
            self.updated_at = current
            return self.snapshot(current)

    def mark_stalled(self, now: Optional[float] = None) -> TelemetrySnapshot:
        return self.update(self.downloaded_bytes, self.total_bytes, 0.0, now)

    def finish(self, now: Optional[float] = None) -> TelemetrySnapshot:
        with self._lock:
            current = time.monotonic() if now is None else float(now)
            if self.total_bytes:
                self.downloaded_bytes = self.total_bytes
            self.speed_bps = 0.0
            self.active = False
            self.updated_at = current
            return self.snapshot(current)

    def snapshot(self, now: Optional[float] = None) -> TelemetrySnapshot:
        with self._lock:
            current = time.monotonic() if now is None else float(now)
            elapsed = max(0.0, current - self.started_at)
            progress = None
            if self.total_bytes > 0:
                progress = min(100.0, self.downloaded_bytes / self.total_bytes * 100.0)
            remaining = max(0, self.total_bytes - self.downloaded_bytes)
            eta = remaining / self.speed_bps if self.total_bytes and self.speed_bps > 1.0 else None
            return TelemetrySnapshot(
                self.active,
                self.downloaded_bytes,
                self.total_bytes,
                self.speed_bps,
                progress,
                elapsed,
                eta,
            )


def hud_degrees_per_tick(speed_bps: float, active: bool) -> float:
    """Map throughput logarithmically into smooth, bounded HUD motion."""
    if not active:
        return 0.3
    speed = max(0.0, float(speed_bps or 0.0))
    if speed <= 1.0:
        return 0.55
    normalized = math.log1p(speed / (128 * 1024))
    return min(14.0, 0.8 + normalized * 2.6)
