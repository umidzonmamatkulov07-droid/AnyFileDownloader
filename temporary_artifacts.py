"""Safe cleanup and promotion of downloader-owned temporary output."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional

from filename_resolver import finalize_download, resolve_filename, unique_path


_TEMPORARY_NAMES = re.compile(
    r"(?:\.part(?:-Frag\d+)?|\.ytdl|\.temp|\.tmp|\.frag\d+|\.f\d+\.[^.]+)$",
    re.IGNORECASE,
)


def is_temporary_artifact(path: Path) -> bool:
    return bool(_TEMPORARY_NAMES.search(path.name)) or path.name.startswith(".afd-")


def final_media_files(directory: Path) -> List[Path]:
    return sorted(
        path for path in directory.rglob("*")
        if path.is_file() and not is_temporary_artifact(path)
    )


def looks_like_mpegts(path: Path) -> bool:
    """Recognize a packet-aligned MPEG transport stream without decoding it."""
    try:
        with path.open("rb") as media:
            prefix = media.read(188 * 3)
    except OSError:
        return False
    return len(prefix) >= 188 * 3 and all(prefix[offset] == 0x47 for offset in (0, 188, 376))


def normalize_hls_container_extensions(sources: Iterable[Path]) -> List[Path]:
    """Give yt-dlp's MPEG-TS HLS output an accurate extension before promotion."""
    normalized = []
    for source in sources:
        if source.suffix.lower() != ".ts" and looks_like_mpegts(source):
            destination = unique_path(source.parent, f"{source.stem}.ts")
            source.replace(destination)
            normalized.append(destination)
        else:
            normalized.append(source)
    return normalized


def promote_downloaded_files(
    sources: Iterable[Path],
    output_directory: Path,
    url: str,
    context: Optional[dict] = None,
    extractor_title: str = "",
) -> List[Path]:
    """Move completed files to unique final names without replacing user files."""
    context = context or {}
    source_list = list(sources)
    promoted: List[Path] = []
    for source in source_list:
        use_browser_metadata = len(source_list) == 1
        filename = resolve_filename(
            url=url,
            explicit_filename=context.get("filename", "") if use_browser_metadata else "",
            media_title=context.get("media_title", "") if use_browser_metadata else "",
            page_title=context.get("title", "") if use_browser_metadata else "",
            extractor_title=extractor_title if use_browser_metadata else source.stem,
            fallback_title=source.stem,
            extension=source.suffix,
        )
        destination = unique_path(output_directory, filename)
        promoted.append(finalize_download(source, destination))
    return promoted
