"""Validated, response-aware direct HTTP downloads with safe partial-file handling."""

from __future__ import annotations

import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from download_errors import DownloadFailure
from filename_resolver import (
    filename_from_content_disposition,
    filename_from_response,
    finalize_download,
    reserve_download_path,
)
from media_types import classify_download
from request_headers import media_request_headers


DIRECT_TYPES = {"DOCUMENT", "ARCHIVE", "FILE", "VIDEO", "AUDIO"}
CHUNK_SIZE = 64 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30


def _content_length(headers) -> int:
    value = headers.get("Content-Length")
    if not value:
        return 0
    try:
        length = int(value)
    except (TypeError, ValueError) as error:
        raise DownloadFailure("invalid_response", "The server returned an invalid Content-Length.") from error
    if length < 0:
        raise DownloadFailure("invalid_response", "The server returned an invalid Content-Length.")
    return length


def download_direct_file(
    url: str,
    output_dir,
    request_context: Optional[dict] = None,
    progress_callback: Optional[Callable[[int, int, float], None]] = None,
    metadata_callback: Optional[Callable[[str, str, int], None]] = None,
    require_recognized: bool = True,
    opener=urllib.request.urlopen,
) -> Path:
    """Download one response to a private .part and atomically promote it on success."""
    context = request_context or {}
    request = urllib.request.Request(url, headers=media_request_headers(context))
    with opener(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        final_url = response.geturl() or url
        content_disposition = response.headers.get("Content-Disposition") or ""
        mime_type = response.headers.get("Content-Type") or context.get("mime_type", "")
        browser_filename = context.get("browser_filename", "")
        response_filename = filename_from_content_disposition(content_disposition)
        response_type = classify_download(
            final_url, mime_type, response_filename or browser_filename, content_disposition
        )
        if require_recognized and response_type not in DIRECT_TYPES:
            raise DownloadFailure(
                "not_direct_file",
                "The response is not a recognized direct file; using the media extractor instead.",
            )
        if response_type in {"HLS", "DASH"}:
            raise DownloadFailure("not_direct_file", "The response is a streaming manifest, not an ordinary file.")

        total_size = _content_length(response.headers)
        filename = filename_from_response(
            final_url,
            content_disposition,
            context.get("title"),
            mime_type,
            context.get("media_title"),
            browser_filename,
            context.get("link_text"),
        )
        if metadata_callback:
            metadata_callback(filename, response_type or "FILE", total_size)
        final_path, part_path = reserve_download_path(output_dir, filename)
        downloaded = 0
        started = time.monotonic()

        try:
            with open(part_path, "wb") as output:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total_size, time.monotonic() - started)

            if total_size and downloaded != total_size:
                raise DownloadFailure(
                    "incomplete_download",
                    f"Incomplete download: expected {total_size} bytes, received {downloaded}.",
                )
            return finalize_download(part_path, final_path)
        except Exception:
            try:
                part_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
