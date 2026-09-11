"""Safe and duplicate-aware output filename handling."""

from __future__ import annotations

import os
import re
import threading
import urllib.parse
import mimetypes
from email.message import Message
from pathlib import Path
from typing import Optional, Tuple, Union

from media_types import extension_for_mime


_INVALID_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_DESTINATION_LOCK = threading.Lock()
_GENERIC_STEMS = {
    "download",
    "file",
    "hls",
    "index",
    "manifest",
    "master",
    "media",
    "playlist",
    "stream",
    "video",
}


def sanitize_filename(filename: str, fallback: str = "downloaded_file", max_length: int = 240) -> str:
    """Return one safe filename component suitable for Windows and Linux."""
    candidate = urllib.parse.unquote(filename or "")
    candidate = candidate.replace("\\", "/").rsplit("/", 1)[-1]
    candidate = _INVALID_CHARACTERS.sub("_", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" .")

    if not candidate or candidate in {".", ".."}:
        candidate = fallback

    path = Path(candidate)
    stem = path.stem.strip(" .") or fallback
    suffix = path.suffix
    if candidate.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"

    allowed_stem_length = max(1, max_length - len(suffix))
    stem = stem[:allowed_stem_length].rstrip(" .") or fallback
    return f"{stem}{suffix}"[:max_length].rstrip(" .")


def filename_from_response(
    url: str,
    content_disposition: Optional[str] = None,
    suggested_title: Optional[str] = None,
    mime_type: Optional[str] = None,
    media_title: Optional[str] = None,
    browser_filename: Optional[str] = None,
    link_text: Optional[str] = None,
) -> str:
    """Resolve a direct-response filename using safe response-oriented priority."""
    server_name = filename_from_content_disposition(content_disposition or "")
    url_name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
    candidates = (
        server_name,
        browser_filename or "",
        url_name,
        link_text or "",
        media_title or "",
        suggested_title or "",
    )
    selected = next((value for value in candidates if _meaningful_name(value)), "downloaded_file")
    safe_name = sanitize_filename(selected)
    mime_extension = extension_for_mime(mime_type or "")
    if mime_extension:
        current_extension = Path(safe_name).suffix.lower()
        if not current_extension or current_extension != mime_extension:
            safe_name = sanitize_filename(f"{Path(safe_name).stem}{mime_extension}")
    return safe_name


def filename_from_content_disposition(content_disposition: str) -> str:
    """Decode RFC 5987/6266 filename parameters without trusting them as paths."""
    if not content_disposition:
        return ""
    message = Message()
    message["content-disposition"] = content_disposition
    filename = message.get_filename() or ""
    if isinstance(filename, tuple):
        charset, _language, encoded = filename
        try:
            filename = urllib.parse.unquote(encoded, encoding=charset or "utf-8", errors="replace")
        except LookupError:
            filename = urllib.parse.unquote(encoded, encoding="utf-8", errors="replace")
    return str(filename)


def _meaningful_name(value: str) -> bool:
    safe_value = sanitize_filename(value or "", fallback="")
    if not safe_value:
        return False
    stem = Path(safe_value).stem.strip(" ._-").lower()
    return bool(stem) and stem not in _GENERIC_STEMS


def _extension_for_mime(mime_type: str) -> str:
    return extension_for_mime(mime_type) or mimetypes.guess_extension(
        (mime_type or "").split(";", 1)[0].strip().lower()
    ) or ""


def resolve_filename(
    url: str,
    explicit_filename: str = "",
    media_title: str = "",
    page_title: str = "",
    extractor_title: str = "",
    fallback_title: str = "",
    mime_type: str = "",
    extension: str = "",
) -> str:
    """Choose the best meaningful safe name and apply the known final extension."""
    url_name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
    candidates = (
        explicit_filename,
        media_title,
        page_title,
        extractor_title,
        url_name,
        fallback_title,
    )
    selected = next((value for value in candidates if _meaningful_name(value)), "downloaded_file")
    safe_name = sanitize_filename(selected)

    desired_extension = extension or _extension_for_mime(mime_type)
    if desired_extension and not desired_extension.startswith("."):
        desired_extension = f".{desired_extension}"
    if desired_extension and not Path(safe_name).suffix:
        safe_name = sanitize_filename(f"{safe_name}{desired_extension}")
    elif extension and Path(safe_name).suffix.lower() != desired_extension.lower():
        safe_name = sanitize_filename(f"{Path(safe_name).stem}{desired_extension}")
    return safe_name


def unique_path(directory: Union[str, Path], filename: str) -> Path:
    """Choose a final path that conflicts with neither a file nor its .part file."""
    output_directory = Path(directory)
    safe_name = sanitize_filename(filename)
    original = Path(safe_name)
    counter = 0

    while True:
        suffix = "" if counter == 0 else f" ({counter})"
        candidate = output_directory / f"{original.stem}{suffix}{original.suffix}"
        part_path = candidate.with_name(f"{candidate.name}.part")
        if not candidate.exists() and not part_path.exists():
            return candidate
        counter += 1


def reserve_download_path(directory: Union[str, Path], filename: str) -> Tuple[Path, Path]:
    """Atomically reserve a unique .part path for this process."""
    with _DESTINATION_LOCK:
        while True:
            final_path = unique_path(directory, filename)
            part_path = final_path.with_name(f"{final_path.name}.part")
            try:
                descriptor = os.open(part_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                continue
            os.close(descriptor)
            return final_path, part_path


def finalize_download(part_path: Path, final_path: Path) -> Path:
    """Move a completed part file into a non-conflicting final path."""
    with _DESTINATION_LOCK:
        destination = final_path
        if destination.exists():
            destination = unique_path(destination.parent, destination.name)
        os.replace(part_path, destination)
        return destination
