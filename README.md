# AnyFileDownloader v3.1-recovery.3

AnyFileDownloader is in recovery/development. The original v3.1 application remains on `main`; reconstruction work lives on `recovery-linux`.

The project combines a CustomTkinter desktop downloader, a Chrome Manifest V3 extension, and a native-messaging bridge. The architecture remains Windows-compatible, while current registration and integration testing target Fedora with Google Chrome.

## Architecture

```text
Google Chrome
    -> passive media detection
    -> user selects a candidate in the popup
    -> Chrome Native Messaging
    -> native_host.py
    -> downloader.py
       -> bounded HLS validation when applicable
       -> direct download or yt-dlp
       -> controlled FFmpeg fallback for validated HLS
    -> temporary output
    -> duplicate-safe final file
```

Passive detection never launches the GUI. A native `ping` only tests connectivity. The desktop application is launched after the user explicitly presses a Download button.

## Fedora development environment

Create the project environment and install only declared dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Check optional FFmpeg availability:

```bash
ffmpeg -version
```

The Linux native-host installer deliberately uses `.venv/bin/python`, ensuring Chrome launches the same interpreter used for development.

Run the desktop application:

```bash
.venv/bin/python downloader.py
```

On Fedora, Python must include its Tkinter bindings. If `import tkinter` fails, install the Fedora package providing Python Tkinter before attempting the GUI. The project does not install system packages automatically.

## Media detection and ranking

The extension passively observes response headers, performance entries, and HTML media/source elements. It detects:

- HLS: `.m3u8` and common HLS MIME types
- DASH: `.mpd` and `application/dash+xml`
- Video: `.mp4`, `.webm`, `.mkv`, `.mov`, `.m4v`, `.ts`, and `video/*`
- Audio: `.mp3`, `.m4a`, `.aac`, `.flac`, `.ogg`, `.opus`, `.wav`, and `audio/*`

Candidate fragments are removed for deduplication, but signed query parameters remain intact. Candidates remain separate across different hosts and URLs. Transport-stream candidates are capped to suppress segment floods.

The popup ranks likely-useful candidates approximately as:

1. apparent HLS master playlist
2. DASH manifest
3. large/direct video
4. audio
5. other HLS playlist
6. uncertain media

Because Chrome does not expose an HLS response body through passive `webRequest`, master-playlist ranking is initially heuristic. Definitive master/media classification occurs during desktop validation.

## HLS validation

Before an HLS candidate reaches yt-dlp, the desktop performs a bounded validation request:

- preserves the complete signed URL;
- forwards safe Referer, Origin, and User-Agent context;
- follows normal HTTP redirects;
- records HTTP status, final URL, and Content-Type;
- reads at most 64 KiB with an 8-second timeout;
- requires `#EXTM3U` near the start;
- identifies `#EXT-X-STREAM-INF` as `hls_master`;
- identifies `#EXTINF` as `hls_media`;
- rejects HTML, JSON, missing headers, HTTP errors, and common DRM markers.

Response bodies are never written to diagnostics. Valid playlists served with a nonstandard MIME type remain usable but receive a MIME-mismatch diagnostic.

## Dispatch and fallback

- Valid HLS: validation → yt-dlp → FFmpeg fallback if yt-dlp fails and FFmpeg exists.
- Invalid HLS: stops with a specific validation error; FFmpeg is never attempted.
- DASH: yt-dlp. There is no custom DASH parser.
- Direct documents/archives: safe direct downloader.
- Direct audio/video in Auto mode: safe direct downloader, then yt-dlp if direct transfer fails.
- Explicit resolution or MP3 conversion: yt-dlp and FFmpeg.
- General page/extractor URLs: yt-dlp.

FFmpeg fallback:

- receives arguments as a list, never a shell command;
- forwards only User-Agent, Referer, and Origin context;
- does not receive cookies or Authorization headers;
- uses normal FFmpeg HLS behavior only;
- writes an MP4 inside a private temporary directory;
- moves it to a duplicate-safe final name only after FFmpeg exits successfully.

The fallback is disabled for manifests with detected DRM markers. This project does not bypass DRM, extract keys, or defeat access controls.

## Diagnostic logging

Desktop and native-host diagnostics use rotating files:

- Linux: `~/.config/anyfiledownloader/logs/anyfiledownloader.log`
- Windows: `%APPDATA%\AnyFileDownloader\logs\anyfiledownloader.log`
- macOS: `~/Library/Application Support/AnyFileDownloader/logs/anyfiledownloader.log`

Up to three rotated 1 MB backups are retained. Native-host diagnostics may also go to stderr; stdout remains reserved exclusively for framed native messages.

Logs include classifications, dispatch paths, validation results, yt-dlp/FFmpeg transitions, and success/failure categories. Query values, Authorization/Cookie headers, and sensitive parameter values are redacted.

## Install the unpacked extension

1. Open `chrome://extensions` in Google Chrome.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Choose this repository's `browser_extension` directory.
5. Copy the displayed 32-character extension ID.

The extension recovery version is **0.3.0**.

## Register the native host on Fedora/Linux

After creating `.venv` and installing requirements:

```bash
./scripts/install_native_host_linux.sh EXTENSION_ID
```

The installer validates the extension ID and writes only per-user files:

- `${XDG_CONFIG_HOME:-~/.config}/google-chrome/NativeMessagingHosts/com.anyfiledownloader.native_host.json`
- `${XDG_DATA_HOME:-~/.local/share}/anyfiledownloader/native_host_launcher.sh`

The manifest uses host name `com.anyfiledownloader.native_host`, an absolute executable launcher path, and `chrome-extension://EXTENSION_ID/` as its only allowed origin. It is safe to rerun.

Restart Chrome completely after registration. To remove the registration:

```bash
./scripts/uninstall_native_host_linux.sh
```

The registration scripts are not run automatically.

## Native-host self-test

This verifies framing, request validation, and desktop command preparation without launching the GUI or downloading anything:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/native_host_self_test.py
```

Expected result includes:

```json
{
  "framing": "ok",
  "validation": "ok",
  "would_launch": false
}
```

## Development tests

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
bash -n scripts/install_native_host_linux.sh scripts/uninstall_native_host_linux.sh
.venv/bin/python -m json.tool browser_extension/manifest.json
```

When Node.js is available:

```bash
node tests/test_media_detection.js
```

The browser JavaScript can also be checked with the existing Chrome engine by opening `tests/browser_js_check.html`; successful execution displays `PASS`.

## Troubleshooting

### Native host unavailable

- Confirm the extension ID used by the installer matches `chrome://extensions`.
- Confirm the host manifest exists under `~/.config/google-chrome/NativeMessagingHosts/`.
- Confirm its `path` is absolute and points to the executable per-user launcher.
- Confirm `.venv/bin/python` still exists.
- Restart all Chrome processes after reinstalling the manifest.

### Downloader launch failure

- Run `.venv/bin/python -c "import tkinter, customtkinter, yt_dlp"`.
- Run `.venv/bin/python downloader.py` from a terminal and inspect immediate errors.
- Review the rotating diagnostic log without posting signed URLs publicly.

### Invalid m3u8 candidate

The error should distinguish HTTP 403/404, HTML or JSON responses, redirects to webpages, missing `#EXTM3U`, and detected DRM markers. Common causes include an expired signed URL, a decoy request, missing page context, or a server requiring credentials that this application intentionally does not extract.

### Valid HLS but yt-dlp and FFmpeg fail

Review the redacted diagnostics for the validation type and failure category. The application does not promise that every detected stream is independently downloadable.

## Current limitations

- Fedora currently requires working Python Tkinter bindings for the GUI.
- No Windows native-host registration script yet.
- Each accepted request can open a separate GUI window.
- No complete HLS or DASH parser.
- No cookie or authenticated-session forwarding.
- Blob/MSE media may not expose a usable URL.
- Generic detection may include false positives.
- FFmpeg is not bundled.
- No final installer or packaged native host.
- Parallel downloads share one progress display.
- DRM-protected media is intentionally unsupported.

This repository does not yet contain a license file.
