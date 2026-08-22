# 🌌 Any File Downloader v3.1 [Hologram Edition]

A sleek, cyberpunk-inspired desktop downloader built with Python and CustomTkinter. Features a dynamic holographic HUD with real-time vector animation scaling, multi-format media extraction powered by yt-dlp, direct HTTP streaming for documents and archives, and advanced queue management.

---

## ✨ Features

- **Cyberpunk / Holographic Interface**: Dark glass transparency (lpha=0.78), neon cyan & amber accents, and futuristic HUD design.
- **Dynamic Animated HUD**: Rotating vector HUD arcs on a custom canvas whose spin speed dynamically scales with live download throughput.
- **Real-Time Speed & Progress Metrics**: Instant tracking of download speed (MB/s), completion percentage, and estimated time remaining (ETA).
- **Direct Document & File Streaming**: Built-in chunked streaming downloader for PDFs, EPUBs, ZIP archives, executables, and direct HTTP/HTTPS files.
- **Media Extraction via yt-dlp**: Support for 1080p, 720p, 480p video, and Best Audio (MP3) extraction.
- **Multi-URL Queue Management**:
  - **All at once (Parallel)**: Concurrent multi-stream downloads via ThreadPoolExecutor.
  - **Sequential**: Ordered downloads with customizable sorting (Newest to Oldest / Oldest to Newest).
- **Playlist Extraction**: Full playlist download support with reverse ordering option.
- **Smart FFmpeg Integration**: Automatic detection of FFmpeg with graceful fallbacks.
- **Quick Action Overlay**: Holographic pop-up menu for fast parameter selection.
- **Cross-Platform**: Supports Windows, macOS, and Linux.

---

## 🚀 Installation & Setup

### Prerequisites
- Python 3.9 or higher
- [Optional] [FFmpeg](https://ffmpeg.org/) (recommended for high-definition video muxing and MP3 conversion)

### 1. Clone the repository
\\\ash
git clone https://github.com/umidzonmamatkulov07-droid/AnyFileDownloader.git
cd AnyFileDownloader
\\\

### 2. Install dependencies
\\\ash
pip install -r requirements.txt
\\\

### 3. Run the application
\\\ash
python downloader.py
\\\

---

## 📦 Packaging to Standalone Executable (.exe)

You can build a standalone Windows executable using PyInstaller:

\\\ash
pip install pyinstaller
pyinstaller downloader.spec
\\\

The compiled binary will be placed in the dist/ directory.

---

## 🛠️ Tech Stack

- **GUI Framework**: [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)
- **Media Engine**: [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- **Direct Streamer**: Python urllib & 	hreading
- **Compiler**: PyInstaller

---

## 📄 License

This project is open source and available under the [MIT License](LICENSE).
