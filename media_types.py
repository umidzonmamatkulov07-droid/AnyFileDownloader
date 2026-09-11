"""Download URL, filename, and MIME classification shared by desktop components."""

from __future__ import annotations

import mimetypes
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


HLS_EXTENSIONS = {".m3u8"}
DASH_EXTENSIONS = {".mpd"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".ts"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}
DIRECT_MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt",
    ".rtf", ".csv", ".odt", ".ods", ".odp", ".epub", ".mobi",
}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"}
OTHER_DIRECT_EXTENSIONS = {".apk", ".exe", ".msi", ".iso", ".dmg", ".deb", ".rpm"}
DIRECT_FILE_EXTENSIONS = DOCUMENT_EXTENSIONS | ARCHIVE_EXTENSIONS | OTHER_DIRECT_EXTENSIONS

HLS_MIME_TYPES = {
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
}
DASH_MIME_TYPES = {"application/dash+xml"}
DOCUMENT_MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/rtf": ".rtf",
    "application/rtf": ".rtf",
    "text/csv": ".csv",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/epub+zip": ".epub",
    "application/x-mobipocket-ebook": ".mobi",
}
ARCHIVE_MIME_EXTENSIONS = {
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/vnd.rar": ".rar",
    "application/x-rar-compressed": ".rar",
    "application/x-7z-compressed": ".7z",
    "application/x-tar": ".tar",
    "application/gzip": ".gz",
    "application/x-gzip": ".gz",
    "application/x-bzip2": ".bz2",
}
OTHER_DIRECT_MIME_EXTENSIONS = {
    "application/vnd.android.package-archive": ".apk",
    "application/x-msdownload": ".exe",
    "application/x-msi": ".msi",
    "application/x-iso9660-image": ".iso",
    "application/x-apple-diskimage": ".dmg",
    "application/vnd.debian.binary-package": ".deb",
    "application/x-debian-package": ".deb",
    "application/x-rpm": ".rpm",
    "application/x-redhat-package-manager": ".rpm",
}
DIRECT_MIME_EXTENSIONS = {
    **DOCUMENT_MIME_EXTENSIONS,
    **ARCHIVE_MIME_EXTENSIONS,
    **OTHER_DIRECT_MIME_EXTENSIONS,
}
NON_DOWNLOAD_MIME_TYPES = {"text/html", "application/xhtml+xml", "application/json"}


def strip_url_fragment(url: str) -> str:
    """Remove only the fragment, retaining query parameters such as signatures."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def url_extension(url: str) -> str:
    path = urlsplit(url).path.lower()
    dot_index = path.rfind(".")
    slash_index = path.rfind("/")
    return path[dot_index:] if dot_index > slash_index else ""


def filename_extension(filename: str) -> str:
    clean_name = filename.split("?", 1)[0].split("#", 1)[0].lower()
    dot_index = clean_name.rfind(".")
    return clean_name[dot_index:] if dot_index >= 0 else ""


def normalized_mime_type(mime_type: str) -> str:
    return mime_type.split(";", 1)[0].strip().lower()


def extension_for_mime(mime_type: str) -> str:
    normalized = normalized_mime_type(mime_type)
    if normalized in DIRECT_MIME_EXTENSIONS:
        return DIRECT_MIME_EXTENSIONS[normalized]
    if normalized.startswith("video/") or normalized.startswith("audio/"):
        return mimetypes.guess_extension(normalized) or ""
    return ""


def classify_download(
    url: str,
    mime_type: str = "",
    suggested_filename: str = "",
    content_disposition: str = "",
) -> Optional[str]:
    """Classify a user-useful downloadable response, preferring authoritative MIME data."""
    normalized_mime = normalized_mime_type(mime_type)
    extension = filename_extension(suggested_filename) or url_extension(url)

    if normalized_mime in HLS_MIME_TYPES:
        return "HLS"
    if normalized_mime in DASH_MIME_TYPES:
        return "DASH"
    if normalized_mime.startswith("video/"):
        return "VIDEO"
    if normalized_mime.startswith("audio/"):
        return "AUDIO"
    if normalized_mime in DOCUMENT_MIME_EXTENSIONS:
        return "DOCUMENT"
    if normalized_mime in ARCHIVE_MIME_EXTENSIONS:
        return "ARCHIVE"
    if normalized_mime in OTHER_DIRECT_MIME_EXTENSIONS:
        return "FILE"
    if normalized_mime in NON_DOWNLOAD_MIME_TYPES:
        return None

    if extension in HLS_EXTENSIONS:
        return "HLS"
    if extension in DASH_EXTENSIONS:
        return "DASH"
    if extension in VIDEO_EXTENSIONS:
        return "VIDEO"
    if extension in AUDIO_EXTENSIONS:
        return "AUDIO"
    if extension in DOCUMENT_EXTENSIONS:
        return "DOCUMENT"
    if extension in ARCHIVE_EXTENSIONS:
        return "ARCHIVE"
    if extension in OTHER_DIRECT_EXTENSIONS:
        return "FILE"
    if "attachment" in content_disposition.lower():
        return "FILE"
    return None


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
