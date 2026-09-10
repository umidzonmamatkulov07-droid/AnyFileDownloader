# Any File Downloader v3.1 — Recovery Stage 1

AnyFileDownloader is a cross-platform desktop downloader built with Python and CustomTkinter. This branch preserves the v3.1 Hologram Edition interface while rebuilding the lost browser-to-desktop architecture incrementally.

## Current features

- Dark CustomTkinter interface with an animated throughput HUD.
- Direct, chunked downloads for supported document and archive URLs.
- Safe `.part` files and duplicate-aware final filenames for direct downloads.
- Media extraction through yt-dlp.
- 1080p, 720p, and 480p MP4 selections when FFmpeg is available.
- MP3 extraction when FFmpeg is available.
- Parallel and sequential multi-URL queues.
- Optional playlist downloads.
- Persistent download directory, quality, playlist, queue, and sort settings.
- A Manifest V3 Chrome extension foundation and native-messaging bridge.

## Recovery architecture

```text
Chrome extension
    -> native_host.py
    -> downloader.py
    -> direct HTTP / yt-dlp / HLS through yt-dlp / FFmpeg
    -> final downloaded file
```

The native bridge accepts framed JSON messages containing `action`, `url`, `page_url`, and `title`. Chrome native-host registration is intentionally not included in this recovery stage, so the extension cannot connect until an OS-specific host manifest is installed in a later stage.

## Requirements

- Python 3.9 or newer
- `customtkinter>=5.2.0`
- `yt-dlp>=2024.0.0`
- FFmpeg on `PATH` for audio/video merging and MP3 conversion

Install the Python dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the desktop application:

```bash
python downloader.py
```

Run the tests:

```bash
python -m unittest discover -s tests -v
```

## Settings locations

Settings are stored in a per-user JSON file:

- Windows: `%APPDATA%\AnyFileDownloader\settings.json`
- Linux: `$XDG_CONFIG_HOME/anyfiledownloader/settings.json`, or `~/.config/anyfiledownloader/settings.json`
- macOS: `~/Library/Application Support/AnyFileDownloader/settings.json`

Set `ANYFILEDOWNLOADER_CONFIG_DIR` to override the directory, which is useful for testing or portable development environments.

## Native messaging protocol

Each message is UTF-8 JSON prefixed by its length as an unsigned 4-byte little-endian integer. Example request:

```json
{
  "action": "download",
  "url": "https://example.com/video",
  "page_url": "https://example.com/watch",
  "title": "Example video"
}
```

Standard output from `native_host.py` is reserved for framed protocol responses. Diagnostic logging goes to standard error.

The extension currently uses the placeholder native host name `com.anyfiledownloader.native_host`. OS-level Chrome registration scripts and manifests remain future work.

## Packaging

The existing PyInstaller specs still build the desktop application:

```bash
python -m pip install pyinstaller
pyinstaller AnyFileDownloader.spec
```

FFmpeg and the native messaging host are not bundled yet.

## Project status

This is reconstruction stage 1. It does not include aggressive media detection, DRM bypassing, site-specific extraction code, browser host registration, an installer, or bundled FFmpeg.

A license file has not yet been added to the repository.
