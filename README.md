# AnyFileDownloader v3.1-recovery.2

AnyFileDownloader is in recovery/development. The original v3.1 application remains on `main`; ongoing reconstruction is on `recovery-linux`.

The project provides a CustomTkinter desktop downloader, a Chrome Manifest V3 extension, and a native-messaging bridge. It is intended to remain portable across Windows and Linux, while the current registration tooling targets Fedora/Linux with Google Chrome.

## Architecture

```text
Google Chrome
    -> passive extension detection (webRequest / performance / media elements)
    -> user selects Download in the extension popup
    -> Chrome Native Messaging
    -> native_host.py
    -> downloader.py
    -> direct transfer or yt-dlp
    -> FFmpeg when merging or conversion is required
    -> final file
```

Passive detection never opens the desktop application. The native host is contacted only for a popup connection check or after the user presses a Download button. Only a download action launches the desktop application.

## Current features

- Persistent download directory, quality, playlist, queue, and sort settings.
- Safe cross-platform filenames and duplicate numbering.
- Direct downloads through temporary `.part` files with safe finalization.
- yt-dlp extraction with meaningful failure reporting.
- Explicit FFmpeg requirements for MP4 merging and MP3 conversion.
- Per-tab browser media candidates with fragment-aware deduplication.
- Signed query parameters are retained.
- Candidate state is cleared on main-frame navigation and tab closure.
- Structured native-host errors for invalid requests and launch failures.

## Media detection

The extension passively observes response headers, performance resource entries, and HTML media/source elements. It detects:

- HLS: `.m3u8` and common HLS MIME types
- DASH: `.mpd` and `application/dash+xml`
- Video: `.mp4`, `.webm`, `.mkv`, `.mov`, `.m4v`, `.ts`, and `video/*`
- Audio: `.mp3`, `.m4a`, `.aac`, `.flac`, `.ogg`, `.opus`, `.wav`, and `audio/*`

Images, JavaScript, CSS, and unrelated response types are ignored. Tiny non-media-element audio/video responses are filtered, and transport-stream candidates are capped per tab to reduce segment noise.

Detection is generic. There are no site-specific hacks, request blocking, DRM bypassing, Widevine handling, credential scraping, or cookie extraction.

## Download dispatch

- HLS and DASH candidates are sent to yt-dlp first. No custom manifest or segment parser is included yet.
- Direct media extensions are attempted with the safe direct downloader first. If that fails and yt-dlp is installed, yt-dlp is used as a fallback.
- Recognized documents and archives use the same safe direct downloader.
- Page and extractor URLs are handled by yt-dlp.
- Browser-provided Referer, Origin, and User-Agent context can be forwarded. Authorization headers, passwords, and cookies are not captured.

An HLS or DASH URL may still fail when a site requires cookies, authorization, short-lived signatures, or other context. Detection does not imply that every stream is independently downloadable.

## Requirements

- Python 3.9 or newer
- `customtkinter>=5.2.0`
- `yt-dlp>=2024.0.0`
- FFmpeg on `PATH` for merging and MP3 conversion
- Google Chrome for current extension testing

Install Python dependencies in the environment that Chrome should use to launch the application. A virtual environment is recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run the desktop application directly:

```bash
python downloader.py
```

## Install the unpacked Chrome extension

1. Open `chrome://extensions` in Google Chrome.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Choose this repository's `browser_extension` directory.
5. Copy the extension ID displayed by Chrome. It is a 32-character value needed for native-host registration.

The extension is currently version 0.2.0.

## Register the native host on Fedora/Linux

Activate the Python environment containing the project dependencies first. The installer records that exact Python interpreter in a private per-user launcher.

From the repository root, run:

```bash
./scripts/install_native_host_linux.sh EXTENSION_ID
```

Replace `EXTENSION_ID` with the value from `chrome://extensions`.

The installer writes only per-user files:

- Chrome manifest: `${XDG_CONFIG_HOME:-~/.config}/google-chrome/NativeMessagingHosts/com.anyfiledownloader.native_host.json`
- Launcher: `${XDG_DATA_HOME:-~/.local/share}/anyfiledownloader/native_host_launcher.sh`

It does not modify global Chrome configuration. It is safe to rerun when the repository path, Python environment, or extension ID changes.

Completely close and restart Google Chrome after registration.

To unregister:

```bash
./scripts/uninstall_native_host_linux.sh
```

The scripts are provided for manual review and execution. They are not run automatically.

## Manual end-to-end test

1. Install the Python requirements in an activated environment.
2. Load `browser_extension` unpacked in Chrome.
3. Copy its extension ID and run the Linux registration command above from the same activated environment.
4. Restart Chrome completely.
5. Open a normal page containing downloadable audio/video or an HLS/DASH player.
6. Start playback so the page requests its media resources.
7. Open the AnyFileDownloader extension popup.
8. Confirm the popup says **Native host connected**.
9. Select an HLS, DASH, VIDEO, or AUDIO candidate.
10. Press **Download selected media**.
11. Confirm the popup reports **Accepted by desktop bridge**.
12. Confirm the desktop window opens, contains the selected URL, and begins the requested transfer.
13. Confirm the final file appears in the configured download directory only after transfer completion.

The manual URL field can test a known `.m3u8`, `.mpd`, or direct media URL when automatic detection is not convenient.

## Development tests

Run Python tests:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Run browser-classification tests when Node.js is available:

```bash
node tests/test_media_detection.js
```

Validate shell scripts and the extension manifest:

```bash
bash -n scripts/install_native_host_linux.sh scripts/uninstall_native_host_linux.sh
python3 -m json.tool browser_extension/manifest.json
```

## Settings locations

- Windows: `%APPDATA%\AnyFileDownloader\settings.json`
- Linux: `$XDG_CONFIG_HOME/anyfiledownloader/settings.json`, or `~/.config/anyfiledownloader/settings.json`
- macOS: `~/Library/Application Support/AnyFileDownloader/settings.json`

Set `ANYFILEDOWNLOADER_CONFIG_DIR` to override the settings directory.

## Current limitations

- No OS-level Windows native-host registration yet.
- No single-instance desktop forwarding; each accepted request can open a new GUI window.
- No custom HLS or DASH parser.
- No cookie forwarding or authenticated-session integration.
- No bundled FFmpeg.
- No final installer or native-host executable package.
- Parallel downloads still share one aggregate-style progress display.
- Browser detection can contain false positives or miss opaque/blob-based media.
- DRM-protected media is intentionally unsupported.

This repository does not yet contain a license file.
