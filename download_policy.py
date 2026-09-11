"""Deterministic routing decisions for AnyFileDownloader URLs."""

from __future__ import annotations

from dataclasses import dataclass

from media_types import classify_download, is_direct_media_url


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
    supplied_type = (detected_type or "").upper()
    media_type = (
        supplied_type
        if supplied_type not in {"", "UNKNOWN", "DIRECT"}
        else (classify_download(url, mime_type) or supplied_type or "UNKNOWN")
    )

    if media_type in {"HLS", "DASH"}:
        return DownloadDecision("yt_dlp", media_type, media_type.lower())
    if selected_quality == "Document (EPUB/PDF)":
        return DownloadDecision("direct", media_type, "document_mode")
    if selected_quality != "Auto":
        return DownloadDecision("yt_dlp", media_type, "explicit_conversion")
    if media_type in {"DOCUMENT", "ARCHIVE", "FILE"}:
        return DownloadDecision("direct", media_type, "document_or_archive")
    if media_type in {"VIDEO", "AUDIO"} or is_direct_media_url(url):
        return DownloadDecision("direct", media_type, "direct_media")
    return DownloadDecision("yt_dlp", media_type, "extractor_url")
