"""Structured failures shared by downloader paths."""

from __future__ import annotations

import urllib.error
from dataclasses import dataclass
from typing import Optional

from diagnostics import redact_diagnostic


@dataclass
class DownloadFailure(Exception):
    category: str
    message: str
    diagnostic: str = ""

    def __str__(self) -> str:
        return f"{self.category}: {self.message}"


def http_failure(status_code: int, reason: str = "") -> DownloadFailure:
    if status_code == 403:
        return DownloadFailure("http_forbidden", "The media server refused the request (HTTP 403).", reason)
    if status_code == 404:
        return DownloadFailure("http_not_found", "The media URL was not found (HTTP 404).", reason)
    return DownloadFailure("network_error", f"The media server returned HTTP {status_code}.", reason)


def map_exception(error: Exception, default_category: str = "network_error") -> DownloadFailure:
    if isinstance(error, DownloadFailure):
        return error
    if isinstance(error, urllib.error.HTTPError):
        return http_failure(error.code, str(error.reason))
    if isinstance(error, urllib.error.URLError):
        return DownloadFailure("network_error", "Could not reach the media server.", redact_diagnostic(str(error.reason)))
    if isinstance(error, TimeoutError):
        return DownloadFailure("timeout", "The media server did not respond before the timeout.")
    if isinstance(error, ConnectionResetError):
        return DownloadFailure("connection_reset", "The media connection was reset.")
    if isinstance(error, ConnectionAbortedError):
        return DownloadFailure("connection_aborted", "The media connection was interrupted.")
    if isinstance(error, (OSError, IOError)):
        return DownloadFailure(default_category, redact_diagnostic(str(error)) or "An operating-system error occurred.")
    return DownloadFailure(default_category, redact_diagnostic(str(error)) or "The download failed.")


def hls_validation_failure(reason: str, status_code: Optional[int] = None) -> DownloadFailure:
    if status_code is not None and status_code >= 400:
        return http_failure(status_code, reason)
    if reason == "network_error":
        return DownloadFailure("network_error", "Could not validate the HLS URL.")
    if reason == "html_response":
        return DownloadFailure("invalid_hls_manifest", "The HLS URL returned HTML instead of a playlist.")
    if reason == "json_response":
        return DownloadFailure("invalid_hls_manifest", "The HLS URL returned JSON instead of a playlist.")
    if reason == "redirected_to_webpage":
        return DownloadFailure("invalid_hls_manifest", "The HLS request redirected to a webpage.")
    if reason == "redirected_non_playlist":
        return DownloadFailure("invalid_hls_manifest", "The HLS request redirected to a non-playlist response.")
    if reason == "missing_extm3u":
        return DownloadFailure("invalid_hls_manifest", "The response did not contain an HLS #EXTM3U header.")
    if reason == "drm_protected":
        return DownloadFailure("unsupported_media", "The HLS playlist indicates DRM-protected media, which is unsupported.")
    return DownloadFailure("invalid_hls_manifest", "The selected URL is not a valid HLS playlist.", reason)
