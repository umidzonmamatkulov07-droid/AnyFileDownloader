import os
import sys
import re
import time
import shutil
import threading
import argparse
import tempfile
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import customtkinter as ctk
from tkinter import filedialog, messagebox, Canvas

from app_settings import AppSettings, QUALITY_OPTIONS, SettingsStore
from diagnostics import configure_logging, log_event, redact_diagnostic, redact_url
from download_policy import choose_download_engine
from download_errors import DownloadFailure, hls_validation_failure, map_exception
from ffmpeg_fallback import run_ffmpeg_hls_fallback
from filename_resolver import filename_from_response, finalize_download, reserve_download_path
from hls_validation import validate_hls_url
from request_headers import media_request_headers
from retry_policy import RetryPolicy, run_with_retry
from temporary_artifacts import final_media_files, normalize_hls_container_extensions, promote_downloaded_files
from ytdlp_options import build_ytdlp_options

# Ensure yt-dlp is available or handled gracefully
try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# Cyberpunk / Hologram Theme Defaults
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# Common direct file extensions that can be streamed directly via HTTP
APP_VERSION = "3.2.0"
LOGGER = configure_logging("anyfiledownloader.desktop")


class PrivacySafeYTDLPLogger:
    """Route yt-dlp messages into redacted development diagnostics."""

    def debug(self, message):
        if message.startswith("[debug] "):
            LOGGER.debug("yt-dlp: %s", redact_diagnostic(message))
        else:
            LOGGER.info("yt-dlp: %s", redact_diagnostic(message))

    def warning(self, message):
        LOGGER.warning("yt-dlp: %s", redact_diagnostic(message))

    def error(self, message):
        LOGGER.error("yt-dlp: %s", redact_diagnostic(message))

HLS_RETRY_POLICY = RetryPolicy(max_attempts=3, delays=(0.75, 1.5))

class AnyFileDownloaderApp(ctk.CTk):
    def __init__(self, initial_url="", initial_page_url="", initial_title="", initial_context=None):
        super().__init__()

        self.title(f"ANY FILEDOWNLOADER {APP_VERSION} [HOLOGRAM_EDITION]")
        self.geometry("820x700")
        self.minsize(750, 650)
        self.resizable(False, False)
        
        # Enhanced Hologram Cyberpunk Transparency Level
        try:
            self.attributes("-alpha", 0.78)
        except Exception:
            pass
        
        # Hologram Color Palette (deep translucent black/blue tones)
        self.bg_color = "#020408"
        self.panel_color = "#050911"
        self.neon_cyan = "#00F0FF"
        self.neon_amber = "#FF9900"
        self.neon_pink = "#FF007F"
        self.text_dim = "#6B7280"
        
        self.configure(fg_color=self.bg_color)

        # Configuration variables
        self.settings_store = SettingsStore()
        saved_settings = self.settings_store.load()
        self.download_path = ctk.StringVar(value=saved_settings.download_directory)
        self.quality_selection = ctk.StringVar(value=saved_settings.quality)
        self.playlist_var = ctk.StringVar(value="on" if saved_settings.playlist else "off")
        self.queue_mode = ctk.StringVar(value=saved_settings.queue_mode)
        self.sort_order = ctk.StringVar(value=saved_settings.sort_order)
        self.theme_mode = ctk.StringVar(value="Dark")
        self.download_history = []
        self.initial_request_metadata = {
            "url": initial_url,
            "page_url": initial_page_url,
            "title": initial_title,
            **(initial_context or {}),
        }

        # Animation states for sci-fi HUD speed scaling
        self.is_downloading = False
        self.anim_angle = 0
        self.current_speed_mbps = 0.0
        self.current_progress_pct = 0
        self.has_ffmpeg = bool(shutil.which("ffmpeg"))
        log_event(LOGGER, "desktop_started", detected_type=self.initial_request_metadata.get("detected_type"))

        # Build UI Structure with Hologram Styling
        self.create_header()
        self.create_navigation_tabs()
        self._register_settings_persistence()
        
        self.overlay_window = None

        # Start animation tick loop
        self.animate_hud()

        if initial_url:
            self.url_entry.insert(0, initial_url)
            self.after(250, self.start_download_process)

    def _register_settings_persistence(self):
        for variable in (
            self.download_path,
            self.quality_selection,
            self.playlist_var,
            self.queue_mode,
            self.sort_order,
        ):
            variable.trace_add("write", self._persist_settings)

    def _persist_settings(self, *_args):
        settings = AppSettings(
            download_directory=self.download_path.get(),
            quality=self.quality_selection.get(),
            playlist=self.playlist_var.get() == "on",
            queue_mode=self.queue_mode.get(),
            sort_order=self.sort_order.get(),
        )
        try:
            self.settings_store.save(settings)
        except OSError as error:
            # Settings failures should not terminate an active download.
            if hasattr(self, "status_label"):
                self.status_label.configure(text=f"STATUS: SETTINGS NOT SAVED ({error})")

    def create_header(self):
        header_frame = ctk.CTkFrame(self, fg_color=self.panel_color, corner_radius=4, border_width=1, border_color=self.neon_cyan)
        header_frame.pack(fill="x", padx=15, pady=(15, 5))

        logo_lbl = ctk.CTkLabel(
            header_frame, 
            text=f"[AF]  ANY FILEDOWNLOADER {APP_VERSION} [HOLOGRAM]",
            font=("Consolas", 15, "bold"), 
            text_color=self.neon_cyan
        )
        logo_lbl.pack(side="left", padx=15, pady=10)

        ffmpeg_status = "FFMPEG: READY" if self.has_ffmpeg else "FFMPEG: NOT FOUND"
        badge_color = self.neon_amber if self.has_ffmpeg else self.neon_pink
        status_badge = ctk.CTkLabel(
            header_frame, 
            text=f"NEURAL_LINK: ACTIVE | {ffmpeg_status}", 
            font=("Consolas", 11, "bold"), 
            text_color=badge_color
        )
        status_badge.pack(side="right", padx=15, pady=10)

    def create_navigation_tabs(self):
        """Creates top tabview styled with hologram borders and colors."""
        self.tab_view = ctk.CTkTabview(
            self, 
            fg_color=self.panel_color, 
            segmented_button_fg_color="#020408",
            segmented_button_selected_color=self.neon_cyan,
            segmented_button_unselected_color="#050911",
            corner_radius=4,
            border_width=1,
            border_color="#111827"
        )
        self.tab_view._segmented_button.configure(text_color=self.text_dim)
        self.tab_view.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        self.main_tab = self.tab_view.add("Downloader")
        self.settings_tab = self.tab_view.add("Settings")

        self.create_main_tab_content()
        self.create_settings_tab_content()

    def create_main_tab_content(self):
        """Builds main downloader interface with cyberpunk HUD and controls."""
        # URL Input Section
        url_frame = ctk.CTkFrame(self.main_tab, fg_color="transparent")
        url_frame.pack(fill="x", padx=10, pady=10)

        self.url_label = ctk.CTkLabel(url_frame, text="NEURAL_LINK_ADDRESS (URL or Multiple URLs separated by space/newline):", font=("Consolas", 12, "bold"), text_color=self.neon_cyan)
        self.url_label.pack(anchor="w", pady=(0, 5))

        url_input_row = ctk.CTkFrame(url_frame, fg_color="transparent")
        url_input_row.pack(fill="x")

        self.url_entry = ctk.CTkEntry(
            url_input_row, 
            placeholder_text="Paste video, document, archive, or playlist stream link(s) here...", 
            height=38,
            font=("Consolas", 11),
            fg_color="#020408",
            border_color=self.neon_cyan,
            text_color="#FFFFFF"
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.paste_btn = ctk.CTkButton(
            url_input_row, 
            text="PASTE", 
            width=75, 
            height=38, 
            fg_color="#0B132B",
            hover_color="#1C2541",
            text_color=self.text_dim,
            font=("Consolas", 11, "bold"),
            command=self.paste_from_clipboard
        )
        self.paste_btn.pack(side="right")

        # Controls Grid (Quality Selector, Playlist Checkbox, Overlay Sim Button)
        controls_frame = ctk.CTkFrame(self.main_tab, fg_color="#020408", border_width=1, border_color="#111827", corner_radius=4)
        controls_frame.pack(fill="x", padx=10, pady=5)

        # Quality / Format Dropdown
        qual_box_frame = ctk.CTkFrame(controls_frame, fg_color="transparent")
        qual_box_frame.pack(side="left", padx=10, pady=10)

        self.qual_label = ctk.CTkLabel(qual_box_frame, text="FORMAT / RESOLUTION:", font=("Consolas", 11, "bold"), text_color=self.text_dim)
        self.qual_label.pack(anchor="w", pady=(0, 3))

        self.quality_dropdown = ctk.CTkComboBox(
            qual_box_frame, 
            values=list(QUALITY_OPTIONS),
            variable=self.quality_selection,
            width=175,
            font=("Consolas", 11),
            fg_color="#020408",
            border_color=self.neon_cyan,
            dropdown_fg_color="#050911"
        )
        self.quality_dropdown.pack()

        # Playlist Checkbox
        playlist_box_frame = ctk.CTkFrame(controls_frame, fg_color="transparent")
        playlist_box_frame.pack(side="left", padx=15, pady=10)

        self.playlist_checkbox = ctk.CTkCheckBox(
            playlist_box_frame, 
            text="Download Playlist", 
            variable=self.playlist_var, 
            onvalue="on", 
            offvalue="off",
            font=("Consolas", 11),
            text_color="#FFFFFF",
            border_color=self.neon_cyan
        )
        self.playlist_checkbox.pack(anchor="w", pady=(18, 0))

        # Quick action overlay trigger button
        overlay_sim_frame = ctk.CTkFrame(controls_frame, fg_color="transparent")
        overlay_sim_frame.pack(side="right", padx=10, pady=10)

        self.simulate_overlay_btn = ctk.CTkButton(
            overlay_sim_frame, 
            text="Quick Action Overlay", 
            fg_color="#0B132B", 
            hover_color="#1C2541",
            text_color=self.neon_amber,
            font=("Consolas", 10, "bold"),
            command=self.open_download_overlay_menu,
            width=150,
            height=32
        )
        self.simulate_overlay_btn.pack(pady=(15, 0))

        # Main Action Button
        action_frame = ctk.CTkFrame(self.main_tab, fg_color="transparent")
        action_frame.pack(fill="x", padx=10, pady=10)

        self.download_btn = ctk.CTkButton(
            action_frame, 
            text="INITIATE DATA TRANSFER", 
            height=42, 
            font=("Consolas", 13, "bold"),
            fg_color=self.neon_cyan,
            hover_color="#00B4D8",
            text_color="#000000",
            command=self.start_download_process
        )
        self.download_btn.pack(fill="x")

        # Status Panel with Circular Sci-Fi HUD Canvas & Neon Indicators
        status_frame = ctk.CTkFrame(self.main_tab, fg_color="#020408", border_width=1, border_color="#111827", corner_radius=4)
        status_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.status_label = ctk.CTkLabel(status_frame, text="STATUS: STANDBY FOR TRANSMISSION", font=("Consolas", 11, "bold"), text_color=self.neon_amber)
        self.status_label.pack(anchor="w", padx=15, pady=(10, 2))

        # Circular Sci-Fi HUD Canvas Container
        hud_container = ctk.CTkFrame(status_frame, fg_color="transparent")
        hud_container.pack(pady=2)

        self.canvas_size = 110
        self.hud_canvas = Canvas(hud_container, width=self.canvas_size, height=self.canvas_size, bg="#020408", highlightthickness=0)
        self.hud_canvas.pack()

        self.progress_bar = ctk.CTkProgressBar(status_frame, progress_color=self.neon_cyan, fg_color="#0B132B")
        self.progress_bar.pack(fill="x", padx=15, pady=5)
        self.progress_bar.set(0)

        self.speed_time_label = ctk.CTkLabel(status_frame, text="Speed: 0.0 MB/s | ETA: --:--", font=("Consolas", 10), text_color=self.text_dim)
        self.speed_time_label.pack(anchor="w", padx=15, pady=(0, 10))

    def create_settings_tab_content(self):
        """Builds the advanced Settings panel styled with cyberpunk aesthetics."""
        settings_container = ctk.CTkScrollableFrame(self.settings_tab, fg_color="transparent")
        settings_container.pack(fill="both", expand=True, padx=5, pady=5)

        # 1. Download Path Configuration
        path_frame = ctk.CTkFrame(settings_container, fg_color="#020408", border_width=1, border_color="#111827")
        path_frame.pack(fill="x", pady=8, padx=5)

        ctk.CTkLabel(path_frame, text="DOWNLOAD DESTINATION FOLDER", font=("Consolas", 11, "bold"), text_color=self.neon_cyan).pack(anchor="w", padx=10, pady=(8, 2))
        
        path_row = ctk.CTkFrame(path_frame, fg_color="transparent")
        path_row.pack(fill="x", padx=10, pady=(0, 10))

        self.path_entry = ctk.CTkEntry(path_row, textvariable=self.download_path, fg_color="#050911", border_color="#111827", text_color="#FFFFFF", font=("Consolas", 10))
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(path_row, text="BROWSE", width=80, fg_color="#0B132B", hover_color="#1C2541", text_color=self.text_dim, font=("Consolas", 10, "bold"), command=self.browse_directory).pack(side="right")

        # 2. Queue Mode Configuration
        queue_frame = ctk.CTkFrame(settings_container, fg_color="#020408", border_width=1, border_color="#111827")
        queue_frame.pack(fill="x", pady=8, padx=5)

        ctk.CTkLabel(queue_frame, text="QUEUE MANAGEMENT MODE", font=("Consolas", 11, "bold"), text_color=self.neon_cyan).pack(anchor="w", padx=10, pady=(8, 2))
        
        q_mode_row = ctk.CTkFrame(queue_frame, fg_color="transparent")
        q_mode_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkRadioButton(q_mode_row, text="All at once (Parallel)", variable=self.queue_mode, value="All at once", text_color="#FFFFFF", border_color=self.neon_cyan, font=("Consolas", 10)).pack(side="left", padx=10)
        ctk.CTkRadioButton(q_mode_row, text="Sequential", variable=self.queue_mode, value="Sequential", text_color="#FFFFFF", border_color=self.neon_cyan, font=("Consolas", 10)).pack(side="left", padx=10)

        # 3. Sequential Sorting Order
        sort_frame = ctk.CTkFrame(settings_container, fg_color="#020408", border_width=1, border_color="#111827")
        sort_frame.pack(fill="x", pady=8, padx=5)

        ctk.CTkLabel(sort_frame, text="SEQUENTIAL SORTING ORDER", font=("Consolas", 11, "bold"), text_color=self.neon_cyan).pack(anchor="w", padx=10, pady=(8, 2))
        
        sort_row = ctk.CTkFrame(sort_frame, fg_color="transparent")
        sort_row.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkRadioButton(sort_row, text="Newest to Oldest", variable=self.sort_order, value="Newest to Oldest", text_color="#FFFFFF", border_color=self.neon_cyan, font=("Consolas", 10)).pack(side="left", padx=10)
        ctk.CTkRadioButton(sort_row, text="Oldest to Newest", variable=self.sort_order, value="Oldest to Newest", text_color="#FFFFFF", border_color=self.neon_cyan, font=("Consolas", 10)).pack(side="left", padx=10)

    def animate_hud(self):
        """Renders the sci-fi rotating vector arcs whose speed scales with throughput."""
        self.hud_canvas.delete("all")
        cx, cy = self.canvas_size / 2, self.canvas_size / 2
        r = 42

        # Draw dark inner backing ring
        self.hud_canvas.create_oval(cx-r, cy-r, cx+r, cy+r, outline="#111827", width=3)

        if self.is_downloading:
            speed_factor = max(0.5, min(self.current_speed_mbps, 30.0))
            self.anim_angle = (self.anim_angle + int(max(2, speed_factor * 2.5))) % 360
            
            # Sci-Fi dual opposing amber vector arcs
            self.hud_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=self.anim_angle, extent=70, outline=self.neon_amber, width=4, style="arc")
            self.hud_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=(self.anim_angle + 180) % 360, extent=70, outline=self.neon_amber, width=4, style="arc")
            
            center_text = f"{self.current_progress_pct}%"
            next_tick = 30
        else:
            # Idle static dashes
            self.hud_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=45, extent=60, outline="#374151", width=2, style="arc")
            self.hud_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=225, extent=60, outline="#374151", width=2, style="arc")
            center_text = f"{self.current_progress_pct}%"
            next_tick = 200

        # Center percentage text
        self.hud_canvas.create_text(cx, cy, text=center_text, fill=self.neon_cyan, font=("Consolas", 12, "bold"))

        self.after(next_tick, self.animate_hud)

    def paste_from_clipboard(self):
        try:
            clipboard_content = self.clipboard_get()
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, clipboard_content)
        except Exception:
            pass

    def browse_directory(self):
        chosen_dir = filedialog.askdirectory(initialdir=self.download_path.get())
        if chosen_dir:
            self.download_path.set(chosen_dir)

    def open_download_overlay_menu(self):
        if self.overlay_window is not None and self.overlay_window.winfo_exists():
            self.overlay_window.focus()
            return

        self.overlay_window = ctk.CTkToplevel(self)
        self.overlay_window.title("QUICK_ACTION_OVERLAY")
        self.overlay_window.geometry("340x260")
        self.overlay_window.resizable(False, False)
        self.overlay_window.attributes("-topmost", True)
        try:
            self.overlay_window.attributes("-alpha", 0.85)
        except Exception:
            pass
        self.overlay_window.configure(fg_color=self.bg_color)

        ctk.CTkLabel(self.overlay_window, text="HOLOGRAPHIC QUICK OPTIONS", font=("Consolas", 12, "bold"), text_color=self.neon_cyan).pack(pady=(15, 5))
        ctk.CTkLabel(self.overlay_window, text="Select extraction parameters:", font=("Consolas", 10), text_color=self.text_dim).pack(pady=(0, 10))

        overlay_choices_frame = ctk.CTkFrame(self.overlay_window, fg_color="transparent")
        overlay_choices_frame.pack(fill="x", padx=15, pady=5)

        def trigger_option(choice_val):
            self.quality_dropdown.set(choice_val)
            self.overlay_window.destroy()
            if choice_val == "Document (EPUB/PDF)" and not self.url_entry.get().strip():
                messagebox.showinfo("Format Notice", "Note: Ensure target document link is active before extraction.")
            else:
                self.start_download_process()

        ctk.CTkButton(overlay_choices_frame, text="Auto Mode (Smart Detect)", fg_color="#0B132B", hover_color="#1C2541", text_color=self.neon_cyan, font=("Consolas", 10, "bold"), command=lambda: trigger_option("Auto")).pack(fill="x", pady=4)
        ctk.CTkButton(overlay_choices_frame, text="1080p High Quality Video", fg_color="#0B132B", hover_color="#1C2541", text_color="#FFFFFF", font=("Consolas", 10), command=lambda: trigger_option("1080p MP4")).pack(fill="x", pady=4)
        ctk.CTkButton(overlay_choices_frame, text="Primary Document (EPUB/PDF)", fg_color="#0B132B", hover_color="#1C2541", text_color="#FFFFFF", font=("Consolas", 10), command=lambda: trigger_option("Document (EPUB/PDF)")).pack(fill="x", pady=4)

    def parse_urls(self, raw_input):
        """Extracts and cleans all valid URLs from the input string."""
        tokens = re.split(r'[\s,\n]+', raw_input.strip())
        urls = [t.strip() for t in tokens if t.strip().startswith(('http://', 'https://', 'ftp://'))]
        return urls

    def start_download_process(self):
        raw_text = self.url_entry.get().strip()
        initial_url = self.initial_request_metadata.get("url")
        urls = [initial_url] if initial_url and raw_text == initial_url else self.parse_urls(raw_text)
        
        if not urls:
            messagebox.showwarning("Missing URL", "Please enter or paste at least one valid link (http:// or https://) first.")
            return

        for u in urls:
            if u not in self.download_history:
                self.download_history.append(u)

        self.download_btn.configure(state="disabled", text="TRANSFERRING...")
        self.is_downloading = True
        self.current_speed_mbps = 0.5
        self.current_progress_pct = 1
        self.status_label.configure(text="STATUS: INITIALIZING DATA STREAM...")

        request_metadata = {}
        if initial_url in urls:
            request_metadata[initial_url] = dict(self.initial_request_metadata)
        self.initial_request_metadata = {}
        download_options = {
            "output_dir": self.download_path.get(),
            "selected_quality": self.quality_selection.get(),
            "is_playlist": self.playlist_var.get() == "on",
            "sorting_setting": self.sort_order.get(),
            "queue_mode": self.queue_mode.get(),
        }

        threading.Thread(
            target=self._run_downloader_manager,
            args=(urls, request_metadata, download_options),
            daemon=True,
        ).start()

    def _yt_dlp_progress_hook(self, d):
        """Real-time progress hook from yt-dlp to update HUD and progress bar."""
        if d.get('status') == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed') or 0  # in bytes/sec
            try:
                eta = max(0, int(float(d.get('eta') or 0)))
            except (TypeError, ValueError, OverflowError):
                eta = 0

            pct = int((downloaded / total_bytes * 100)) if total_bytes > 0 else self.current_progress_pct
            speed_mbps = speed / (1024 * 1024) if speed else 0.0
            eta_str = f"{eta // 60:02d}:{eta % 60:02d}" if eta else "--:--"

            self.current_progress_pct = min(100, max(0, pct))
            self.current_speed_mbps = speed_mbps

            self.after(0, lambda p=pct, s=speed_mbps, e=eta_str: (
                self.progress_bar.set(p / 100.0),
                self.speed_time_label.configure(text=f"Speed: {s:.2f} MB/s | ETA: {e} | Progress: {p}%")
            ))
        elif d.get('status') == 'finished':
            self.after(0, lambda: (
                self.progress_bar.set(1.0),
                self.status_label.configure(text="STATUS: POST-PROCESSING DATA STREAM...")
            ))

    def _is_direct_download(self, url, selected_quality, request_context=None):
        """Return the deterministic Stage 4 direct/yt-dlp dispatch decision."""
        request_context = request_context or {}
        decision = choose_download_engine(
            url,
            selected_quality,
            request_context.get("detected_type", ""),
            request_context.get("mime_type", ""),
        )
        return decision.engine == "direct"

    def _download_direct_file(self, url, output_dir, request_context=None):
        """Chunked HTTP/HTTPS streaming downloader with live throughput and progress metrics."""
        request_context = request_context or {}
        request_headers = media_request_headers(request_context)
        req = urllib.request.Request(url, headers=request_headers)
        
        with urllib.request.urlopen(req, timeout=30) as response:
            content_length = response.headers.get('Content-Length')
            total_size = int(content_length) if content_length else 0
            
            cd = response.headers.get('Content-Disposition')
            response_mime = response.headers.get('Content-Type') or request_context.get('mime_type')
            filename = filename_from_response(
                url,
                cd,
                request_context.get("title"),
                response_mime,
                request_context.get("media_title"),
            )
            final_path, part_path = reserve_download_path(output_dir, filename)
            
            chunk_size = 64 * 1024
            downloaded = 0
            start_time = time.time()
            last_calc_time = start_time
            last_downloaded = 0

            try:
                with open(part_path, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        now = time.time()
                        dt = now - last_calc_time
                        if dt >= 0.2:
                            bytes_diff = downloaded - last_downloaded
                            speed_mbps = (bytes_diff / dt) / (1024 * 1024) if dt > 0 else 0.0
                            pct = int(downloaded / total_size * 100) if total_size > 0 else 50
                            eta = int((total_size - downloaded) / (bytes_diff / dt)) if total_size > 0 and bytes_diff > 0 else 0
                            eta_str = f"{eta // 60:02d}:{eta % 60:02d}" if eta else "--:--"

                            self.current_progress_pct = pct
                            self.current_speed_mbps = speed_mbps
                            last_calc_time = now
                            last_downloaded = downloaded

                            self.after(0, lambda p=pct, s=speed_mbps, e=eta_str: (
                                self.progress_bar.set(p / 100.0),
                                self.speed_time_label.configure(text=f"Speed: {s:.2f} MB/s | ETA: {e} | Progress: {p}%")
                            ))

                if total_size and downloaded != total_size:
                    raise IOError(f"Incomplete download: expected {total_size} bytes, received {downloaded}")
                return finalize_download(part_path, final_path)
            except Exception:
                try:
                    part_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise

    def _retry_status(self, engine, url, request_context, next_attempt, maximum, error, delay):
        log_event(
            LOGGER,
            "hls_retry_scheduled",
            url,
            request_context,
            detected_type="HLS",
            category=map_exception(error).category,
        )
        self.after(0, lambda: self.status_label.configure(
            text=f"STATUS: HLS {engine} RETRY [{next_attempt}/{maximum}] IN {delay:.1f}s..."
        ))

    def _validate_hls_with_retry(self, url, request_context):
        def validate_once():
            result = validate_hls_url(url, request_context)
            log_event(
                LOGGER,
                "hls_validation_result",
                url,
                request_context,
                detected_type="HLS",
                status_code=result.status_code,
                content_type=result.content_type,
                reason=result.reason,
                hls_kind=result.playlist_type,
            )
            if not result.valid:
                raise hls_validation_failure(result.reason, result.status_code)
            return result

        log_event(LOGGER, "hls_validation_started", url, request_context, detected_type="HLS")
        return run_with_retry(
            validate_once,
            HLS_RETRY_POLICY,
            lambda attempt, maximum, error, delay: self._retry_status(
                "VALIDATION", url, request_context, attempt, maximum, error, delay
            ),
        )

    def _run_ytdlp_download(self, url, output_dir, selected_quality, is_playlist, sorting_setting, request_context, detected_type):
        output_path = Path(output_dir)
        with tempfile.TemporaryDirectory(prefix=".afd-ytdlp-", dir=output_path) as staging_name:
            staging_path = Path(staging_name)
            options = build_ytdlp_options(
                staging_path,
                selected_quality,
                is_playlist,
                sorting_setting,
                self.has_ffmpeg,
                {**request_context, "detected_type": detected_type},
                self._yt_dlp_progress_hook,
                PrivacySafeYTDLPLogger(),
            )

            def download_once():
                with yt_dlp.YoutubeDL(options) as ydl:
                    return ydl.extract_info(url, download=True)

            if detected_type == "HLS":
                result = run_with_retry(
                    download_once,
                    HLS_RETRY_POLICY,
                    lambda attempt, maximum, error, delay: self._retry_status(
                        "TRANSFER", url, request_context, attempt, maximum, error, delay
                    ),
                )
            else:
                result = download_once()

            completed_files = final_media_files(staging_path)
            if detected_type == "HLS":
                completed_files = normalize_hls_container_extensions(completed_files)
            if not completed_files:
                raise DownloadFailure("yt_dlp_failure", "yt-dlp completed without producing a final media file.")
            extractor_title = result.get("title", "") if isinstance(result, dict) else ""
            return promote_downloaded_files(
                completed_files,
                output_path,
                url,
                request_context,
                extractor_title,
            )

    def _download_single_url(self, url, output_dir, selected_quality, is_playlist, sorting_setting, request_context=None):
        """Process one complete URL without mutating its path or query string."""
        request_context = request_context or {}
        decision = choose_download_engine(
            url,
            selected_quality,
            request_context.get("detected_type", ""),
            request_context.get("mime_type", ""),
        )
        detected_type = decision.detected_type

        if decision.engine == "direct":
            log_event(LOGGER, "dispatch_selected", url, request_context, detected_type=detected_type, category="direct")
            try:
                final_path = self._download_direct_file(url, output_dir, request_context)
                log_event(LOGGER, "download_succeeded", url, request_context, detected_type=detected_type, category="direct")
                return [final_path]
            except Exception as error:
                failure = map_exception(error)
                log_event(
                    LOGGER,
                    "direct_download_failed",
                    url,
                    request_context,
                    detected_type=detected_type,
                    category=failure.category,
                )
                if yt_dlp is None:
                    raise failure from error

        hls_validation = None
        if detected_type == "HLS":
            hls_validation = self._validate_hls_with_retry(url, request_context)

        if yt_dlp is None:
            if detected_type == "HLS" and selected_quality != "Best Audio (MP3)":
                return [self._run_hls_ffmpeg_fallback(url, output_dir, request_context)]
            raise DownloadFailure("unsupported_media", "yt-dlp is required for this URL but is not installed.")

        log_event(LOGGER, "yt_dlp_started", url, request_context, detected_type=detected_type)
        try:
            completed = self._run_ytdlp_download(
                url,
                output_dir,
                selected_quality,
                is_playlist,
                sorting_setting,
                request_context,
                detected_type,
            )
        except Exception as error:
            failure = map_exception(error, "yt_dlp_failure")
            diagnostic = redact_diagnostic(getattr(failure, "diagnostic", "") or str(error))
            log_event(
                LOGGER,
                "yt_dlp_failed",
                url,
                request_context,
                detected_type=detected_type,
                category=failure.category,
            )
            if diagnostic:
                LOGGER.warning("yt-dlp diagnostic: %s", diagnostic)
            if detected_type == "HLS" and selected_quality != "Best Audio (MP3)" and hls_validation:
                return [self._run_hls_ffmpeg_fallback(url, output_dir, request_context)]
            raise DownloadFailure("yt_dlp_failure", "yt-dlp could not download the selected media.", diagnostic) from error

        log_event(LOGGER, "download_succeeded", url, request_context, detected_type=detected_type, category="yt_dlp")
        return completed

    def _run_hls_ffmpeg_fallback(self, url, output_dir, request_context):
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise DownloadFailure(
                "ffmpeg_unavailable",
                "yt-dlp could not handle the valid HLS playlist and FFmpeg is unavailable.",
            )
        log_event(LOGGER, "ffmpeg_fallback_started", url, request_context, detected_type="HLS")

        def ffmpeg_once():
            return run_ffmpeg_hls_fallback(
                ffmpeg_path,
                url,
                output_dir,
                request_context.get("media_title") or request_context.get("title") or "hls_download",
                request_context,
            )

        try:
            final_path = run_with_retry(
                ffmpeg_once,
                HLS_RETRY_POLICY,
                lambda attempt, maximum, error, delay: self._retry_status(
                    "FFMPEG", url, request_context, attempt, maximum, error, delay
                ),
            )
        except DownloadFailure as error:
            log_event(LOGGER, "ffmpeg_fallback_failed", url, request_context, category=error.category)
            if error.diagnostic:
                LOGGER.warning("FFmpeg diagnostic: %s", redact_diagnostic(error.diagnostic))
            raise
        log_event(LOGGER, "download_succeeded", url, request_context, detected_type="HLS", category="ffmpeg")
        return final_path

    def _run_downloader_manager(self, urls, request_metadata=None, download_options=None):
        """Manages queue execution (Parallel vs Sequential) across all parsed URLs."""
        request_metadata = request_metadata or {}
        download_options = download_options or {}
        output_dir = download_options.get("output_dir", str(Path.home() / "Downloads"))
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as error:
            failure = DownloadFailure("filesystem_error", "Could not create the download directory.", str(error))
            self.after(0, lambda: self._on_download_error(str(failure)))
            return
        
        selected_quality = download_options.get("selected_quality", "Auto")
        is_playlist = download_options.get("is_playlist", False)
        sorting_setting = download_options.get("sorting_setting", "Newest to Oldest")
        queue_mode = download_options.get("queue_mode", "All at once")

        # Handle sorting for sequential mode
        if queue_mode == "Sequential" and sorting_setting == "Oldest to Newest":
            urls_to_process = list(reversed(urls))
        else:
            urls_to_process = list(urls)

        total_items = len(urls_to_process)
        errors = []

        try:
            if queue_mode == "All at once" and total_items > 1:
                # Parallel execution
                self.after(0, lambda: self.status_label.configure(
                    text=f"STATUS: TRANSMITTING {total_items} STREAMS IN PARALLEL..."
                ))
                with ThreadPoolExecutor(max_workers=min(4, total_items)) as executor:
                    futures = [
                        executor.submit(
                            self._download_single_url,
                            u,
                            output_dir,
                            selected_quality,
                            is_playlist,
                            sorting_setting,
                            request_metadata.get(u, {}),
                        )
                        for u in urls_to_process
                    ]
                    for f in futures:
                        try:
                            f.result()
                        except Exception as e:
                            errors.append(str(e))
            else:
                # Sequential execution
                for idx, u in enumerate(urls_to_process, 1):
                    self.after(0, lambda i=idx, tot=total_items: self.status_label.configure(
                        text=f"STATUS: TRANSMITTING LINK [{i}/{tot}]..."
                    ))
                    try:
                        self._download_single_url(
                            u,
                            output_dir,
                            selected_quality,
                            is_playlist,
                            sorting_setting,
                            request_metadata.get(u, {}),
                        )
                    except Exception as e:
                        errors.append(f"Link {idx} ({redact_url(u)}): {str(e)}")

            if errors and len(errors) == total_items:
                raise Exception("\n".join(errors))

            self.after(0, lambda: self._on_download_complete(errors))

        except Exception as e:
            error_msg = str(e)
            log_event(LOGGER, "download_failed", category=getattr(e, "category", "download_error"))
            self.after(0, lambda: self._on_download_error(error_msg))

    def _on_download_complete(self, errors=None):
        self.is_downloading = False
        self.current_speed_mbps = 0.0
        self.current_progress_pct = 100
        self.progress_bar.set(1.0)
        self.status_label.configure(text="STATUS: DATA TRANSFER COMPLETE")
        self.speed_time_label.configure(text="Speed: 0.0 MB/s | Stream Finalized")
        self.download_btn.configure(state="normal", text="INITIATE DATA TRANSFER")

        if errors:
            self.status_label.configure(text="STATUS: TRANSFER COMPLETE WITH WARNINGS")
            self.speed_time_label.configure(text=f"Completed with {len(errors)} warning(s) | See application log")

    def _on_download_error(self, err_text):
        self.is_downloading = False
        self.current_speed_mbps = 0.0
        self.current_progress_pct = 0
        self.progress_bar.set(0)
        self.status_label.configure(text="STATUS: STREAM ERROR ENCOUNTERED")
        self.speed_time_label.configure(text="Speed: 0.0 MB/s | Link Failed")
        self.download_btn.configure(state="normal", text="INITIATE DATA TRANSFER")
        safe_error = redact_diagnostic(err_text, limit=800)
        messagebox.showerror("Transfer Error", f"An error occurred during data stream:\n{safe_error}")

def parse_command_line():
    parser = argparse.ArgumentParser(description="AnyFileDownloader desktop application")
    parser.add_argument("--download-url", default="", help="URL forwarded by the native messaging host")
    parser.add_argument("--page-url", default="", help="Source page URL supplied by the browser")
    parser.add_argument("--title", default="", help="Suggested page/media title supplied by the browser")
    parser.add_argument("--media-title", default="", help="Media-element title supplied by the browser")
    parser.add_argument("--detected-type", default="", help="Browser media classification")
    parser.add_argument("--mime-type", default="", help="Browser-observed response MIME type")
    parser.add_argument("--source", default="", help="Browser detection source")
    parser.add_argument("--referer", default="", help="Safe browser page/referrer context")
    parser.add_argument("--origin", default="", help="Safe browser origin context")
    parser.add_argument("--user-agent", default="", help="Browser user agent context")
    parser.add_argument("--accept", default="", help="Browser Accept header for the selected media request")
    parser.add_argument("--accept-language", default="", help="Browser Accept-Language header for the selected request")
    parser.add_argument("--browser-range", default="", help="Observed browser Range header (diagnostic only)")
    parser.add_argument("--sec-fetch-dest", default="", help="Observed Sec-Fetch-Dest value (diagnostic only)")
    parser.add_argument("--sec-fetch-mode", default="", help="Observed Sec-Fetch-Mode value (diagnostic only)")
    parser.add_argument("--sec-fetch-site", default="", help="Observed Sec-Fetch-Site value (diagnostic only)")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_command_line()
    initial_context = {
        "detected_type": arguments.detected_type,
        "mime_type": arguments.mime_type,
        "source": arguments.source,
        "media_title": arguments.media_title,
        "referer": arguments.referer,
        "origin": arguments.origin,
        "user_agent": arguments.user_agent,
        "accept": arguments.accept,
        "accept_language": arguments.accept_language,
        "range": arguments.browser_range,
        "sec_fetch_dest": arguments.sec_fetch_dest,
        "sec_fetch_mode": arguments.sec_fetch_mode,
        "sec_fetch_site": arguments.sec_fetch_site,
    }
    app = AnyFileDownloaderApp(
        arguments.download_url,
        arguments.page_url,
        arguments.title,
        initial_context,
    )
    app.mainloop()
