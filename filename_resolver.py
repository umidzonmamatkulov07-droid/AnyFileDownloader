"""Safe and duplicate-aware output filename handling."""

from __future__ import annotations

import os
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple, Union


_INVALID_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_DESTINATION_LOCK = threading.Lock()


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
) -> str:
    """Prefer a server filename, then URL basename, then a supplied page title."""
    server_name = None
    if content_disposition:
        encoded_match = re.search(r"filename\*\s*=\s*(?:UTF-8'')?([^;]+)", content_disposition, re.IGNORECASE)
        regular_match = re.search(r'filename\s*=\s*(?:"([^"]+)"|([^;]+))', content_disposition, re.IGNORECASE)
        if encoded_match:
            server_name = encoded_match.group(1).strip().strip('"\'')
        elif regular_match:
            server_name = (regular_match.group(1) or regular_match.group(2)).strip().strip('"\'')

    url_name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
    selected = server_name or url_name or suggested_title or "downloaded_file.dat"
    return sanitize_filename(selected)


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
