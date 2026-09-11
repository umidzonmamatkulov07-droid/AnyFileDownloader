"""yt-dlp configuration shared by HLS, DASH, and extractor downloads."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from download_errors import DownloadFailure
from request_headers import media_request_headers


def build_ytdlp_options(
    staging_directory: Path,
    selected_quality: str,
    is_playlist: bool,
    sorting_setting: str,
    has_ffmpeg: bool,
    request_context: Optional[dict] = None,
    progress_hook: Optional[Callable] = None,
    logger=None,
) -> dict:
    options = {
        "outtmpl": str(staging_directory / "%(title)s.%(ext)s"),
        "concurrent_fragment_downloads": 1,
        "retries": 2,
        "fragment_retries": 2,
        "file_access_retries": 1,
        "extractor_retries": 1,
        "ignoreerrors": False,
        "overwrites": False,
        "continuedl": True,
        "noplaylist": not is_playlist,
    }
    if progress_hook:
        options["progress_hooks"] = [progress_hook]
    if logger:
        options["logger"] = logger

    headers = media_request_headers(request_context, include_default_user_agent=False)
    if headers:
        options["http_headers"] = headers
    if str((request_context or {}).get("detected_type", "")).upper() == "HLS":
        # Keep native HLS as MPEG-TS instead of forcing yt-dlp's FFmpeg MP4 fixup.
        # The completed file is content-sniffed and renamed before promotion.
        options["hls_use_mpegts"] = True

    if selected_quality in {"1080p MP4", "720p MP4", "480p MP4"}:
        if not has_ffmpeg:
            raise DownloadFailure("ffmpeg_unavailable", f"FFmpeg is required to create the requested {selected_quality} file.")
        height = selected_quality.split("p", 1)[0]
        options["format"] = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"best[height<={height}][ext=mp4]"
        )
        options["merge_output_format"] = "mp4"
    elif selected_quality == "Best Audio (MP3)":
        if not has_ffmpeg:
            raise DownloadFailure("ffmpeg_unavailable", "FFmpeg is required to convert the requested audio to MP3.")
        options["format"] = "bestaudio/best"
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        options["format"] = "bestvideo+bestaudio/best" if has_ffmpeg else "best"

    if is_playlist and sorting_setting == "Newest to Oldest":
        options["playlist_reverse"] = True
    return options
