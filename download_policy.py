"""Deterministic routing decisions for AnyFileDownloader URLs."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from media_types import classify_media, is_direct_media_url


DIRECT_FILE_EXTENSIONS = {
    ".pdf", ".epub", ".mobi", ".azw3", ".djvu", ".doc", ".docx", ".ppt", ".pptx",
    ".xls", ".xlsx", ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".iso",
    ".exe", ".msi", ".apk", ".dmg", ".pkg", ".deb", ".rpm", ".txt", ".csv",
}


@dataclass(frozen=True)
class DownloadDecision:
    engine: str
    detected_type: str
    reason: str


def choose_download_engine(
    url: str,
    selected_quality: str = "Auto",
    detected_type: str = "",
    mime_type: str = "",
) -> DownloadDecision:
    """Return a stable direct/yt-dlp decision without performing I/O."""
    media_type = (detected_type or classify_media(url, mime_type) or "UNKNOWN").upper()
    extension = urllib.parse.urlparse(url).path.lower()

    if media_type in {"HLS", "DASH"}:
        return DownloadDecision("yt_dlp", media_type, media_type.lower())
    if selected_quality == "Document (EPUB/PDF)":
        return DownloadDecision("direct", media_type, "document_mode")
    if selected_quality != "Auto":
        return DownloadDecision("yt_dlp", media_type, "explicit_conversion")
    if any(extension.endswith(suffix) for suffix in DIRECT_FILE_EXTENSIONS):
        return DownloadDecision("direct", media_type, "document_or_archive")
    if media_type in {"VIDEO", "AUDIO"} or is_direct_media_url(url):
        return DownloadDecision("direct", media_type, "direct_media")
    return DownloadDecision("yt_dlp", media_type, "extractor_url")
