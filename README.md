# AnyFileDownloader v3.4.0

AnyFileDownloader combines a CustomTkinter desktop downloader, a Chrome Manifest V3 extension, and a native-messaging bridge. Version 3.4.0 is the approved Stage 6 release.

The architecture remains Windows-compatible, while current registration and integration testing target Fedora with Google Chrome.

Stage 6 adds a persistent single desktop instance, a real sequential transfer queue, conservative inline webpage controls, and the restored large Hologram interface while preserving the Stage 4/5 download engine and privacy boundaries.

## Architecture

```text
Google Chrome
    -> passive media detection
    -> user selects a candidate in the popup or its associated inline control
    -> Chrome Native Messaging
    -> native_host.py
       -> local-user Unix socket if the desktop is already running
       -> otherwise launch one desktop owner
    -> downloader.py
       -> persistent sequential queue
       -> bounded HLS validation when applicable
       -> deterministic direct download or yt-dlp dispatch
       -> bounded serial retry for transient HLS transport failures
       -> controlled FFmpeg fallback for validated HLS
    -> private downloader-owned temporary output
    -> duplicate-safe final file
```

Passive detection never launches the GUI. A native `ping` only tests connectivity. The desktop application is launched after the user explicitly presses a popup or in-page Download button. Later requests are delivered to the existing desktop process and retained in its session queue.

## Stage 6 desktop and IPC

The desktop owns an advisory instance lock and an `AF_UNIX` socket inside its per-user configuration directory. The directory is mode `0700`; the lock and socket are mode `0600`; Linux peer credentials must match the current UID. The endpoint is not exposed over TCP. Kernel lock ownership handles crash recovery, and the lock owner safely replaces a stale socket before listening.

The native host attempts one bounded IPC request first. When no owner exists it launches the desktop with the already-validated request. Concurrent launches converge on the one lock owner; losing processes forward their requests to that owner during its bounded startup window. Manual launches activate the existing window instead of creating another GUI.

All accepted transfers enter one thread-safe sequential queue and remain visible for the current session as queued, active, completed, failed, or cancelled jobs. The queue uses the current Stage 4/5 dispatch, validation, retry, and safe file-promotion engine.

The desktop opens at `1180x820`, has a `980x680` minimum, is resizable, and persists its last valid geometry. It uses stable Tk window alpha at `0.88`; true blur-behind remains compositor-dependent. The Download, Queue, Settings, and About tabs restore the richer Hologram layout, including the control matrix, central transfer console, circular HUD, and DATA STREAM statistics.

Direct HTTP and yt-dlp progress callbacks feed actual downloaded bytes, total bytes when known, elapsed time, smoothed bytes/second, progress, and ETA into the UI. Unknown totals and ETAs are displayed as unknown. The HUD advances every 40 ms on the Tk event loop. Its speed is a bounded logarithmic mapping of the smoothed throughput: idle advances `0.3` degrees/tick, an active stall `0.55`, and live transfers increase from `0.8 + 2.6 * log1p(bytes_per_second / 128 KiB)` up to a hard maximum of `14` degrees/tick.

## Stage 6 in-page controls

The local extension setting **Show in-page download buttons** defaults to on. When enabled, a small cyan Hologram control is associated only with a matching visible video/audio element or exact recognized file anchor. Strong HLS/DASH web-request evidence may be associated with the sole visible player on a page. Multiple media choices use a compact menu capped at six items. Mutation, resize, and scroll observation handles dynamic players and stale-control cleanup without remote scripts or evaluation.

Opaque `blob:` download anchors remain browser-owned: clicking their inline control invokes the original browser anchor, and neither the extension nor native host reads or reconstructs blob contents. Browser-owned media blobs are not offered to the desktop. Turning the setting off removes all controls while leaving the popup unchanged.

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

The extension passively observes response headers, redirect chains, Chrome download lifecycle events, performance entries, HTML media/source elements, and recognizable anchor links (including dynamically-created `<a download>` elements). It detects:

- HLS: `.m3u8` and common HLS MIME types
- DASH: `.mpd` and `application/dash+xml`
- Video: `.mp4`, `.webm`, `.mkv`, `.mov`, `.m4v`, `.ts`, and `video/*`
- Audio: `.mp3`, `.m4a`, `.aac`, `.flac`, `.ogg`, `.opus`, `.wav`, and `audio/*`
- Documents: PDF, DOC/DOCX, XLS/XLSX, PPT/PPTX, TXT, RTF, CSV, ODT/ODS/ODP, EPUB, and MOBI
- Archives: ZIP, RAR, 7Z, TAR, GZ, and BZ2
- Other direct files: APK, EXE, MSI, ISO, DMG, DEB, and RPM

Classification uses Chrome download events, recognized response MIME types, and Content-Disposition filenames as high-confidence evidence. A redirect chain ending in a valid downloadable response is medium-confidence evidence. URL extensions and uncorroborated performance/network entries remain low-confidence signals. This allows extensionless download endpoints and corrects misleading URL suffixes when the response identifies a known file type. Detection remains passive: the extension never initiates a browser download, and it launches the desktop downloader only when the user presses a Download button.

Redirect chains retain their original and final safe URLs. Candidate fragments are removed for deduplication, but signed query parameters remain intact. Anchor, redirect-response, and `chrome.downloads` observations of the same transfer merge into one canonical final-URL candidate. Candidates remain separate across different hosts and URLs. Transport-stream candidates are capped to suppress segment floods.

Chrome download creation and change events record only safe metadata: final/original URLs, basename-only filename, MIME type when available, byte count, reliable tab attribution, and completion or interruption state. Request capture remains explicitly allowlisted; Cookie and Authorization values are never collected or logged. Blob download URLs are recognized as opaque, browser-owned candidates. Their contents are never read, inspected, or reconstructed, and they are not sent to the native host.

Each popup candidate shows its filename, classified type, extension, host, approximate size, and download state when known, with a separate Download button. Browser-owned blob candidates are informational and cannot be resent through the native bridge. Manual URLs remain supported. The popup ranks likely-useful candidates approximately as:

1. apparent HLS master playlist
2. documents, archives, and ordinary files
3. DASH manifest
4. large/direct video
5. audio
6. other HLS playlist
7. uncertain media

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

Validation redirects are recorded for diagnosis, but the original selected URL—including its complete signed query—is passed unchanged to every yt-dlp or FFmpeg attempt. Only Referer, Origin, User-Agent, Accept, and Accept-Language are allowlisted for forwarding. Cookies and Authorization values are neither collected nor forwarded.

## Dispatch and fallback

- Valid HLS: validation → yt-dlp → FFmpeg fallback if yt-dlp fails and FFmpeg exists.
- Invalid HLS: stops with a specific validation error; FFmpeg is never attempted.
- DASH: yt-dlp. There is no custom DASH parser.
- Direct documents/archives: safe direct downloader.
- Direct audio/video in Auto mode: safe direct downloader, then yt-dlp if direct transfer fails.
- Explicit resolution or MP3 conversion: yt-dlp and FFmpeg.
- General page/extractor URLs: yt-dlp.

Direct responses follow redirects and resolve names in this order: Content-Disposition, browser filename metadata, final URL path, safe link/media/page text, and a MIME-aware fallback. Known MIME types correct missing or misleading extensions. Downloads remain private `.part` files until complete; advertised lengths must match, interrupted partials are removed, transient failures receive bounded serial retries, and existing files are never overwritten. A missing Content-Length is allowed and completes normally at clean end-of-stream. Known document/archive/file failures do not fall through to yt-dlp.

HLS validation and transfer failures identified as timeouts, resets, aborted connections, fragment interruptions, or temporary network failures are retried serially up to three whole-operation attempts with short bounded delays. Permanent failures such as HTTP 403/404, invalid manifests, unsupported URLs, and DRM markers are not repeatedly retried. yt-dlp also performs two bounded fragment/network retries inside each attempt.

yt-dlp writes fragments, separate streams, and post-processing output into one downloader-owned temporary directory. After yt-dlp and FFmpeg finish merging/remuxing, only completed files are promoted to duplicate-safe names in the selected destination; the temporary directory and its remaining artifacts are removed.

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

Filename selection prefers an explicit meaningful server name, media-element metadata, the page title, the extractor title, and then a meaningful URL basename. Generic HLS names such as `master`, `index`, `manifest`, and `playlist` are skipped when better metadata is available. Existing files are never replaced; numbered names such as `name (1).mp4` are generated instead.

## Install the unpacked extension

1. Open `chrome://extensions` in Google Chrome.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Choose this repository's `browser_extension` directory.
5. Copy the displayed 32-character extension ID.

The extension version is **3.4.0**.

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

## Release workflow

- Development happens on a development or recovery branch. Checkpoint commits may be created there, but unfinished work is not pushed over the known-good release.
- Before release, run the complete test suite, shell and JSON validation, `git diff --check`, a repository-wide secret/private-data scan, and cleanup of temporary files. The application must then be tested manually.
- Only after the owner explicitly approves the tested version is it merged into `main`, tagged with a new application version, and pushed. `main` therefore always represents the latest owner-tested and approved version.
- Previous commits and release tags remain available for rollback; release history must not be rewritten.

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
- Inline controls depend on a resource being safely associated with an actual player or file anchor; ambiguous background traffic intentionally receives no button.
- No complete HLS or DASH parser.
- No cookie or authenticated-session forwarding.
- Blob/MSE media may not expose a usable URL.
- Generic detection may include false positives.
- FFmpeg is not bundled.
- No final installer or packaged native host.
- The persistent Stage 6 queue intentionally processes one transfer at a time.
- Native single-instance IPC currently targets Unix-socket platforms; the existing downloader engine remains Windows-compatible, but equivalent Windows local IPC is future work.
- Fedora/Wayland exposes stable whole-window alpha through Tk in the tested environment, but portable compositor blur-behind is not available.
- DRM-protected media is intentionally unsupported.

This repository does not yet contain a license file.
