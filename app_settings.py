"""Persistent, cross-platform settings for AnyFileDownloader."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


QUALITY_OPTIONS = (
    "Auto",
    "1080p MP4",
    "720p MP4",
    "480p MP4",
    "Best Audio (MP3)",
    "Document (EPUB/PDF)",
)
QUEUE_MODES = ("All at once", "Sequential")
SORT_ORDERS = ("Newest to Oldest", "Oldest to Newest")


def user_config_directory() -> Path:
    """Return the platform-appropriate per-user configuration directory."""
    override = os.environ.get("ANYFILEDOWNLOADER_CONFIG_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        return Path(base) / "AnyFileDownloader" if base else Path.home() / "AnyFileDownloader"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AnyFileDownloader"

    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".config") / "anyfiledownloader"


@dataclass
class AppSettings:
    download_directory: str = str(Path.home() / "Downloads")
    quality: str = "Auto"
    playlist: bool = False
    queue_mode: str = "All at once"
    sort_order: str = "Newest to Oldest"
    window_geometry: str = "1180x820"
    window_opacity: float = 0.88

    @classmethod
    def from_mapping(cls, data: Any) -> "AppSettings":
        defaults = cls()
        if not isinstance(data, dict):
            return defaults

        directory = data.get("download_directory")
        quality = data.get("quality")
        playlist = data.get("playlist")
        queue_mode = data.get("queue_mode")
        sort_order = data.get("sort_order")
        window_geometry = data.get("window_geometry")
        window_opacity = data.get("window_opacity")

        return cls(
            download_directory=directory if isinstance(directory, str) and directory.strip() else defaults.download_directory,
            quality=quality if quality in QUALITY_OPTIONS else defaults.quality,
            playlist=playlist if isinstance(playlist, bool) else defaults.playlist,
            queue_mode=queue_mode if queue_mode in QUEUE_MODES else defaults.queue_mode,
            sort_order=sort_order if sort_order in SORT_ORDERS else defaults.sort_order,
            window_geometry=(
                window_geometry
                if isinstance(window_geometry, str)
                and re.fullmatch(r"\d{3,4}x\d{3,4}(?:[+-]\d+){0,2}", window_geometry)
                else defaults.window_geometry
            ),
            window_opacity=(
                float(window_opacity)
                if isinstance(window_opacity, (int, float)) and 0.70 <= float(window_opacity) <= 1.0
                else defaults.window_opacity
            ),
        )


class SettingsStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or user_config_directory() / "settings.json"

    def load(self) -> AppSettings:
        try:
            with self.path.open("r", encoding="utf-8") as settings_file:
                return AppSettings.from_mapping(json.load(settings_file))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return AppSettings()

    def save(self, settings: AppSettings) -> None:
        """Atomically replace the settings file after writing valid JSON."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as settings_file:
                json.dump(asdict(settings), settings_file, indent=2, ensure_ascii=False)
                settings_file.write("\n")
                temporary_path = Path(settings_file.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
