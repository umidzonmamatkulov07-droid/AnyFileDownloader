"""Controlled FFmpeg fallback for validated, non-DRM HLS playlists."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from diagnostics import redact_diagnostic
from download_errors import DownloadFailure
from filename_resolver import finalize_download, sanitize_filename, unique_path


def build_ffmpeg_hls_command(
    ffmpeg_path: str,
    url: str,
    output_path: Path,
    context: Optional[dict] = None,
) -> List[str]:
    context = context or {}
    command = [ffmpeg_path, "-hide_banner", "-nostdin", "-loglevel", "error"]
    if context.get("user_agent"):
        command.extend(["-user_agent", context["user_agent"]])
    referer = context.get("referer") or context.get("page_url")
    if referer:
        command.extend(["-referer", referer])
    if context.get("origin"):
        command.extend(["-headers", f"Origin: {context['origin']}\r\n"])
    command.extend([
        "-i", url,
        "-map", "0:v?",
        "-map", "0:a?",
        "-c", "copy",
        "-f", "mp4",
        "-n", str(output_path),
    ])
    return command


def run_ffmpeg_hls_fallback(
    ffmpeg_path: str,
    url: str,
    output_directory: str,
    suggested_title: str,
    context: Optional[dict] = None,
) -> Path:
    safe_title = sanitize_filename(suggested_title or "hls_download")
    if Path(safe_title).suffix.lower() != ".mp4":
        safe_title = f"{Path(safe_title).stem}.mp4"
    final_path = unique_path(output_directory, safe_title)
    try:
        with tempfile.TemporaryDirectory(prefix=".afd-hls-", dir=output_directory) as temporary_directory:
            part_path = Path(temporary_directory) / f"{final_path.stem}.part.mp4"
            command = build_ffmpeg_hls_command(ffmpeg_path, url, part_path, context)
            try:
                result = subprocess.run(command, capture_output=True, text=True, check=False)
            except OSError as error:
                raise DownloadFailure("ffmpeg_failure", "FFmpeg could not be started.", str(error)) from error

            if result.returncode != 0:
                diagnostic = redact_diagnostic(result.stderr)
                raise DownloadFailure("ffmpeg_failure", "FFmpeg could not save the validated HLS playlist.", diagnostic)
            if not part_path.is_file() or part_path.stat().st_size == 0:
                raise DownloadFailure("ffmpeg_failure", "FFmpeg completed without producing a media file.")
            return finalize_download(part_path, final_path)
    except DownloadFailure:
        raise
    except OSError as error:
        raise DownloadFailure("filesystem_error", "Could not finalize the FFmpeg output file.", str(error)) from error
