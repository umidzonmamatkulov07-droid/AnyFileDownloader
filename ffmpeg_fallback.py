"""Controlled FFmpeg fallback for validated, non-DRM HLS playlists."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from diagnostics import redact_diagnostic
from download_errors import DownloadFailure
from filename_resolver import finalize_download, resolve_filename, unique_path
from request_headers import media_request_headers


# Retain FFmpeg's normal HLS segment allowlist and additionally accept common
# static-resource suffixes used for disguised transport-stream or fragmented-MP4
# segments. This remains deliberately narrower than FFmpeg's ``ALL`` setting.
HLS_ALLOWED_SEGMENT_EXTENSIONS = (
    "3gp,aac,avi,ac3,eac3,flac,mkv,m3u8,m4a,m4s,m4v,mpg,mov,mp2,mp3,mp4,"
    "mpeg,mpegts,ogg,ogv,oga,ts,vob,vtt,wav,webvtt,cmfv,cmfa,ec3,fmp4,html,"
    "jpg,jpeg,png,webp,ico,txt,css,js"
)
MP4_CONTAINER_FAILURE_MARKERS = (
    "could not write header",
    "dimensions not set",
    "incorrect codec parameters",
    "is not supported with codec",
)


def build_ffmpeg_hls_command(
    ffmpeg_path: str,
    url: str,
    output_path: Path,
    context: Optional[dict] = None,
    output_format: str = "mp4",
) -> List[str]:
    context = context or {}
    forwarded_headers = media_request_headers(context, include_default_user_agent=False)
    command = [ffmpeg_path, "-hide_banner", "-nostdin", "-loglevel", "error"]
    if forwarded_headers.get("User-Agent"):
        command.extend(["-user_agent", forwarded_headers["User-Agent"]])
    referer = forwarded_headers.get("Referer")
    if referer:
        command.extend(["-referer", referer])
    header_lines = []
    for header_name in ("Origin", "Accept", "Accept-Language"):
        value = forwarded_headers.get(header_name)
        if value:
            header_lines.append(f"{header_name}: {value}")
    if header_lines:
        command.extend(["-headers", "\r\n".join(header_lines) + "\r\n"])
    command.extend([
        "-allowed_segment_extensions", HLS_ALLOWED_SEGMENT_EXTENSIONS,
        "-extension_picky", "0",
        "-i", url,
        "-map", "0:v?",
        "-map", "0:a?",
        "-c", "copy",
        "-f", output_format,
        "-n", str(output_path),
    ])
    return command


def is_mp4_container_failure(diagnostic: str) -> bool:
    lowered = (diagnostic or "").lower()
    return any(marker in lowered for marker in MP4_CONTAINER_FAILURE_MARKERS)


def run_ffmpeg_hls_fallback(
    ffmpeg_path: str,
    url: str,
    output_directory: str,
    suggested_title: str,
    context: Optional[dict] = None,
) -> Path:
    safe_title = resolve_filename(
        url,
        page_title=suggested_title,
        fallback_title="hls_download",
        extension=".mp4",
    )
    try:
        with tempfile.TemporaryDirectory(prefix=".afd-hls-", dir=output_directory) as temporary_directory:
            final_path = unique_path(output_directory, safe_title)
            part_path = Path(temporary_directory) / f"{final_path.stem}.part.mp4"
            command = build_ffmpeg_hls_command(ffmpeg_path, url, part_path, context, "mp4")
            try:
                result = subprocess.run(command, capture_output=True, text=True, check=False)
            except OSError as error:
                raise DownloadFailure("ffmpeg_failure", "FFmpeg could not be started.", str(error)) from error

            if result.returncode != 0:
                diagnostic = redact_diagnostic(result.stderr)
                if not is_mp4_container_failure(diagnostic):
                    raise DownloadFailure("ffmpeg_failure", "FFmpeg could not save the validated HLS playlist.", diagnostic)

                part_path.unlink(missing_ok=True)
                ts_name = resolve_filename(
                    url,
                    page_title=suggested_title,
                    fallback_title="hls_download",
                    extension=".ts",
                )
                final_path = unique_path(output_directory, ts_name)
                part_path = Path(temporary_directory) / f"{final_path.stem}.part.ts"
                command = build_ffmpeg_hls_command(ffmpeg_path, url, part_path, context, "mpegts")
                try:
                    result = subprocess.run(command, capture_output=True, text=True, check=False)
                except OSError as error:
                    raise DownloadFailure("ffmpeg_failure", "FFmpeg could not be started.", str(error)) from error
                if result.returncode != 0:
                    ts_diagnostic = redact_diagnostic(result.stderr)
                    raise DownloadFailure(
                        "ffmpeg_failure",
                        "FFmpeg could not save the validated HLS playlist.",
                        ts_diagnostic or diagnostic,
                    )
            if not part_path.is_file() or part_path.stat().st_size == 0:
                raise DownloadFailure("ffmpeg_failure", "FFmpeg completed without producing a media file.")
            return finalize_download(part_path, final_path)
    except DownloadFailure:
        raise
    except OSError as error:
        raise DownloadFailure("filesystem_error", "Could not finalize the FFmpeg output file.", str(error)) from error
