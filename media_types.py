"""Media URL and MIME classification shared by desktop-side components."""

from __future__ import annotations

import mimetypes
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


HLS_EXTENSIONS = {".m3u8"}
DASH_EXTENSIONS = {".mpd"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".ts"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}
DIRECT_MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

HLS_MIME_TYPES = {
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
}
DASH_MIME_TYPES = {"application/dash+xml"}


def strip_url_fragment(url: str) -> str:
    """Remove only the fragment, retaining query parameters such as signatures."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def url_extension(url: str) -> str:
    path = urlsplit(url).path.lower()
    dot_index = path.rfind(".")
    slash_index = path.rfind("/")
    return path[dot_index:] if dot_index > slash_index else ""


def classify_media(url: str, mime_type: str = "") -> Optional[str]:
    """Classify a useful media URL as HLS, DASH, VIDEO, or AUDIO."""
    normalized_mime = mime_type.split(";", 1)[0].strip().lower()
    extension = url_extension(url)

    if extension in HLS_EXTENSIONS or normalized_mime in HLS_MIME_TYPES:
        return "HLS"
    if extension in DASH_EXTENSIONS or normalized_mime in DASH_MIME_TYPES:
        return "DASH"
    if extension in VIDEO_EXTENSIONS or normalized_mime.startswith("video/"):
        return "VIDEO"
    if extension in AUDIO_EXTENSIONS or normalized_mime.startswith("audio/"):
        return "AUDIO"
    return None


def is_direct_media_url(url: str) -> bool:
    return url_extension(url) in DIRECT_MEDIA_EXTENSIONS


def guessed_mime_type(url: str) -> str:
    return mimetypes.guess_type(urlsplit(url).path)[0] or ""
