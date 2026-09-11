"""Bounded serial retry policy for transient HLS transport failures."""

from __future__ import annotations

import errno
import socket
import time
import urllib.error
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, TypeVar

from download_errors import DownloadFailure


T = TypeVar("T")

TRANSIENT_CATEGORIES = {
    "connection_aborted",
    "connection_reset",
    "hls_transport",
    "network_error",
    "timeout",
}
TRANSIENT_MARKERS = (
    "connection aborted",
    "connection reset",
    "connection refused",
    "fragment download failed",
    "network is unreachable",
    "remote end closed connection",
    "temporarily unavailable",
    "temporary failure",
    "timed out",
    "timeout",
    "unable to download video data",
)
PERMANENT_MARKERS = (
    "authorization",
    "copyright",
    "drm",
    "forbidden",
    "http error 400",
    "http error 401",
    "http error 403",
    "http error 404",
    "not found",
    "private video",
    "unsupported url",
    "widevine",
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    delays: Sequence[float] = (0.75, 1.5)

    def delay_before(self, attempt: int) -> float:
        if not self.delays:
            return 0.0
        return self.delays[min(max(0, attempt - 1), len(self.delays) - 1)]


def is_transient_transport_error(error: BaseException) -> bool:
    if isinstance(error, DownloadFailure):
        if error.category in TRANSIENT_CATEGORIES:
            return True
        text = f"{error.message} {error.diagnostic}".lower()
    else:
        text = str(error).lower()

    if any(marker in text for marker in PERMANENT_MARKERS):
        return False
    if isinstance(error, (TimeoutError, socket.timeout, ConnectionError)):
        return True
    if isinstance(error, urllib.error.URLError):
        return is_transient_transport_error(error.reason) if isinstance(error.reason, BaseException) else True
    if isinstance(error, OSError) and error.errno in {
        errno.ECONNABORTED,
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.ENETDOWN,
        errno.ENETUNREACH,
        errno.ETIMEDOUT,
    }:
        return True
    return any(marker in text for marker in TRANSIENT_MARKERS)


def run_with_retry(
    operation: Callable[[], T],
    policy: RetryPolicy,
    on_retry: Optional[Callable[[int, int, Exception, float], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run one operation at a time and retry only recognized transient failures."""
    if policy.max_attempts < 1:
        raise ValueError("max_attempts must be at least one")

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation()
        except Exception as error:
            if attempt >= policy.max_attempts or not is_transient_transport_error(error):
                raise
            delay = policy.delay_before(attempt)
            if on_retry:
                on_retry(attempt + 1, policy.max_attempts, error, delay)
            if delay > 0:
                sleep(delay)
    raise AssertionError("unreachable")
