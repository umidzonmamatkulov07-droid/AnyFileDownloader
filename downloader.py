import os
import sys
import re
import shutil
import threading
import argparse
import tempfile
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import customtkinter as ctk
from tkinter import filedialog, messagebox, Canvas

from app_settings import AppSettings, QUALITY_OPTIONS, SettingsStore
from diagnostics import configure_logging, log_event, redact_diagnostic, redact_url
from download_queue import DownloadJob, SequentialDownloadQueue
from download_telemetry import DownloadTelemetry, hud_degrees_per_tick
from direct_download import download_direct_file
from download_policy import choose_download_engine
from download_errors import DownloadFailure, hls_validation_failure, map_exception
from ffmpeg_fallback import run_ffmpeg_hls_fallback
from hls_validation import validate_hls_url
from retry_policy import RetryPolicy, run_with_retry
from temporary_artifacts import final_media_files, normalize_hls_container_extensions, promote_downloaded_files
from ytdlp_options import build_ytdlp_options
from single_instance import SingleInstanceService, send_ipc_message

# Ensure yt-dlp is available or handled gracefully
try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# Cyberpunk / Hologram Theme Defaults
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# Common direct file extensions that can be streamed directly via HTTP
APP_VERSION = "3.4.0"
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
DIRECT_RETRY_POLICY = RetryPolicy(max_attempts=3, delays=(0.75, 1.5))

class AnyFileDownloaderApp(ctk.CTk):
    def __init__(self, initial_url="", initial_page_url="", initial_title="", initial_context=None):
        super().__init__()

        self.settings_store = SettingsStore()
        saved_settings = self.settings_store.load()
        self.title(f"ANY FILEDOWNLOADER {APP_VERSION} [HOLOGRAM_EDITION]")
        self.geometry(saved_settings.window_geometry)
        self.minsize(980, 680)
        self.resizable(True, True)
        
        # Enhanced Hologram Cyberpunk Transparency Level
        try:
            self.attributes("-alpha", saved_settings.window_opacity)
        except Exception:
            pass
        self.window_opacity = saved_settings.window_opacity
        
        # Hologram Color Palette (deep translucent black/blue tones)
        self.bg_color = "#020408"
        self.panel_color = "#050911"
        self.neon_cyan = "#00F0FF"
        self.neon_amber = "#FF9900"
        self.neon_pink = "#FF007F"
        self.text_dim = "#6B7280"
        
        self.configure(fg_color=self.bg_color)

        # Configuration variables
        self.download_path = ctk.StringVar(value=saved_settings.download_directory)
        self.quality_selection = ctk.StringVar(value=saved_settings.quality)
        self.playlist_var = ctk.StringVar(value="on" if saved_settings.playlist else "off")
        self.queue_mode = ctk.StringVar(value=saved_settings.queue_mode)
        self.sort_order = ctk.StringVar(value=saved_settings.sort_order)
        self.theme_mode = ctk.StringVar(value="Dark")
        self.download_history = []
        self.session_history = []
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
        self.telemetry = DownloadTelemetry()
        self.current_job_id = ""
        self._last_progress_ui_at = 0.0
        self._last_queue_progress_at = 0.0
        self.instance_service = None
        self.has_ffmpeg = bool(shutil.which("ffmpeg"))
        self.download_queue = SequentialDownloadQueue(self._process_queue_job, self._queue_job_changed)
        self.download_queue.start()
        log_event(LOGGER, "desktop_started", detected_type=self.initial_request_metadata.get("detected_type"))

        # Build UI Structure with Hologram Styling
        self.create_header()
        self.create_navigation_tabs()
        self._register_settings_persistence()
        
        self.overlay_window = None
        self.protocol("WM_DELETE_WINDOW", self.close_application)
        self.after(80, self._apply_window_opacity)

        # Start animation tick loop
        self.animate_hud()

        if initial_url:
            self.after(250, lambda: self.enqueue_download_request(dict(self.initial_request_metadata)))

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
            window_geometry=self.geometry(),
            window_opacity=self._window_opacity(),
        )
        try:
            self.settings_store.save(settings)
        except OSError as error:
            # Settings failures should not terminate an active download.
            if hasattr(self, "status_label"):
                self.status_label.configure(text=f"STATUS: SETTINGS NOT SAVED ({error})")

    def _window_opacity(self):
        try:
            return float(self.attributes("-alpha"))
        except Exception:
            return 0.88

    def _apply_window_opacity(self):
        try:
            self.attributes("-alpha", self.window_opacity)
        except Exception:
            pass

    def create_header(self):
        header_frame = ctk.CTkFrame(
            self, fg_color=self.panel_color, corner_radius=5,
            border_width=1, border_color=self.neon_cyan,
        )
        header_frame.pack(fill="x", padx=18, pady=(16, 7))

        logo_lbl = ctk.CTkLabel(
            header_frame, 
            text=f"[ AF ]   ANY FILEDOWNLOADER   v{APP_VERSION}",
            font=("Consolas", 18, "bold"),
            text_color=self.neon_cyan
        )
        logo_lbl.pack(side="left", padx=18, pady=14)

        ffmpeg_status = "FFMPEG: READY" if self.has_ffmpeg else "FFMPEG: NOT FOUND"
        ytdlp_status = "YT-DLP: READY" if yt_dlp is not None else "YT-DLP: NOT FOUND"
        ctk.CTkLabel(
            header_frame, text=f"{ffmpeg_status}   |   {ytdlp_status}",
            font=("Consolas", 11, "bold"),
            text_color=self.neon_amber if self.has_ffmpeg and yt_dlp is not None else self.neon_pink,
        ).pack(side="right", padx=18, pady=14)

    def create_navigation_tabs(self):
        """Create the four-panel Hologram workspace."""
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
        self.tab_view.pack(fill="both", expand=True, padx=18, pady=(0, 16))

        self.main_tab = self.tab_view.add("Download")
        self.queue_tab = self.tab_view.add("Queue")
        self.settings_tab = self.tab_view.add("Settings")
        self.about_tab = self.tab_view.add("About")

        self.create_main_tab_content()
        self.create_queue_tab_content()
        self.create_settings_tab_content()
        self.create_about_tab_content()

    def create_main_tab_content(self):
        """Build the large three-column transfer console."""
        self.main_tab.grid_columnconfigure(0, minsize=180)
        self.main_tab.grid_columnconfigure(1, weight=1, minsize=520)
        self.main_tab.grid_columnconfigure(2, minsize=205)
        self.main_tab.grid_rowconfigure(0, weight=1)

        left_panel = ctk.CTkFrame(
            self.main_tab, fg_color="#030711", border_width=1,
            border_color="#172033", corner_radius=5, width=180,
        )
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(8, 5), pady=9)
        left_panel.grid_propagate(False)
        ctk.CTkLabel(left_panel, text="CONTROL MATRIX", font=("Consolas", 12, "bold"), text_color=self.neon_cyan).pack(anchor="w", padx=14, pady=(16, 12))
        self.left_urls_label = self._sidebar_stat(left_panel, "URLS", "0 detected")
        self.left_queue_label = self._sidebar_stat(left_panel, "QUEUE", "0 items")
        self.left_history_label = self._sidebar_stat(left_panel, "HISTORY", "0 session")
        ctk.CTkButton(
            left_panel, text="OPEN QUEUE", height=34, fg_color="#0B132B",
            hover_color="#14213D", text_color=self.neon_cyan,
            font=("Consolas", 10, "bold"),
            command=lambda: self.tab_view.set("Queue"),
        ).pack(fill="x", padx=12, pady=(18, 6))
        ctk.CTkButton(
            left_panel, text="QUICK ACTION", height=34, fg_color="#0B132B",
            hover_color="#14213D", text_color=self.neon_amber,
            font=("Consolas", 10, "bold"), command=self.open_download_overlay_menu,
        ).pack(fill="x", padx=12, pady=6)

        center_panel = ctk.CTkFrame(
            self.main_tab, fg_color="#050911", border_width=1,
            border_color="#172033", corner_radius=5,
        )
        center_panel.grid(row=0, column=1, sticky="nsew", padx=5, pady=9)

        url_frame = ctk.CTkFrame(center_panel, fg_color="transparent")
        url_frame.pack(fill="x", padx=16, pady=(17, 10))

        self.url_label = ctk.CTkLabel(url_frame, text="NEURAL_LINK_ADDRESS / URL", font=("Consolas", 12, "bold"), text_color=self.neon_cyan)
        self.url_label.pack(anchor="w", pady=(0, 5))

        url_input_row = ctk.CTkFrame(url_frame, fg_color="transparent")
        url_input_row.pack(fill="x")

        self.url_entry = ctk.CTkEntry(
            url_input_row, 
            placeholder_text="Paste video, document, archive, or playlist stream link(s) here...", 
            height=45,
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
            height=45,
            fg_color="#0B132B",
            hover_color="#1C2541",
            text_color=self.text_dim,
            font=("Consolas", 11, "bold"),
            command=self.paste_from_clipboard
        )
        self.paste_btn.pack(side="right")

        # Controls Grid (Quality Selector, Playlist Checkbox, Overlay Sim Button)
        controls_frame = ctk.CTkFrame(center_panel, fg_color="#020408", border_width=1, border_color="#111827", corner_radius=4)
        controls_frame.pack(fill="x", padx=16, pady=7)

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

        action_frame = ctk.CTkFrame(center_panel, fg_color="transparent")
        action_frame.pack(fill="x", padx=16, pady=10)

        self.download_btn = ctk.CTkButton(
            action_frame, 
            text="INITIATE DATA TRANSFER", 
            height=50,
            font=("Consolas", 14, "bold"),
            fg_color=self.neon_cyan,
            hover_color="#00B4D8",
            text_color="#000000",
            command=self.start_download_process
        )
        self.download_btn.pack(fill="x")

        status_frame = ctk.CTkFrame(center_panel, fg_color="#020408", border_width=1, border_color="#111827", corner_radius=4)
        status_frame.pack(fill="both", expand=True, padx=16, pady=(5, 16))

        self.status_label = ctk.CTkLabel(status_frame, text="STATUS: STANDBY FOR TRANSMISSION", font=("Consolas", 11, "bold"), text_color=self.neon_amber)
        self.status_label.pack(anchor="w", padx=17, pady=(14, 2))
        self.current_item_label = ctk.CTkLabel(
            status_frame, text="NO ACTIVE DATA STREAM", font=("Consolas", 10),
            text_color=self.text_dim, wraplength=500, justify="left",
        )
        self.current_item_label.pack(anchor="w", padx=17, pady=(0, 5))

        # Circular Sci-Fi HUD Canvas Container
        hud_container = ctk.CTkFrame(status_frame, fg_color="transparent")
        hud_container.pack(pady=2)

        self.canvas_size = 190
        self.hud_canvas = Canvas(hud_container, width=self.canvas_size, height=self.canvas_size, bg="#020408", highlightthickness=0)
        self.hud_canvas.pack()

        self.progress_bar = ctk.CTkProgressBar(status_frame, progress_color=self.neon_cyan, fg_color="#0B132B")
        self.progress_bar.pack(fill="x", padx=20, pady=10)
        self.progress_bar.set(0)

        self.speed_time_label = ctk.CTkLabel(status_frame, text="Speed: 0 B/s | ETA: --:-- | Progress: --", font=("Consolas", 10), text_color=self.text_dim)
        self.speed_time_label.pack(anchor="w", padx=20, pady=(0, 14))

        right_panel = ctk.CTkFrame(
            self.main_tab, fg_color="#030711", border_width=1,
            border_color=self.neon_cyan, corner_radius=5, width=205,
        )
        right_panel.grid(row=0, column=2, sticky="nsew", padx=(5, 8), pady=9)
        right_panel.grid_propagate(False)
        ctk.CTkLabel(right_panel, text="DATA STREAM", font=("Consolas", 13, "bold"), text_color=self.neon_cyan).pack(anchor="w", padx=15, pady=(17, 13))
        self.stream_speed_value = self._stream_stat(right_panel, "SPEED", "0 B/s")
        self.stream_progress_value = self._stream_stat(right_panel, "PROGRESS", "--")
        self.stream_elapsed_value = self._stream_stat(right_panel, "ELAPSED", "00:00")
        self.stream_queue_value = self._stream_stat(right_panel, "QUEUE", "0 items")
        self.stream_status_value = self._stream_stat(right_panel, "STATUS", "IDLE", self.neon_amber)

    def _sidebar_stat(self, parent, title, value):
        frame = ctk.CTkFrame(parent, fg_color="#020408", corner_radius=3)
        frame.pack(fill="x", padx=12, pady=5)
        ctk.CTkLabel(frame, text=title, font=("Consolas", 9, "bold"), text_color=self.text_dim).pack(anchor="w", padx=9, pady=(7, 0))
        label = ctk.CTkLabel(frame, text=value, font=("Consolas", 11, "bold"), text_color="#FFFFFF")
        label.pack(anchor="w", padx=9, pady=(0, 7))
        return label

    def _stream_stat(self, parent, title, value, color=None):
        ctk.CTkLabel(parent, text=title, font=("Consolas", 9, "bold"), text_color=self.text_dim).pack(anchor="w", padx=16, pady=(9, 0))
        label = ctk.CTkLabel(parent, text=value, font=("Consolas", 16, "bold"), text_color=color or "#FFFFFF")
        label.pack(anchor="w", padx=16, pady=(0, 4))
        return label

    def create_queue_tab_content(self):
        header = ctk.CTkFrame(self.queue_tab, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(12, 5))
        ctk.CTkLabel(header, text="TRANSFER QUEUE", font=("Consolas", 15, "bold"), text_color=self.neon_cyan).pack(side="left")
        self.queue_summary_label = ctk.CTkLabel(header, text="0 items", font=("Consolas", 10), text_color=self.neon_amber)
        self.queue_summary_label.pack(side="right")
        self.queue_list_frame = ctk.CTkScrollableFrame(self.queue_tab, fg_color="#020408")
        self.queue_list_frame.pack(fill="both", expand=True, padx=12, pady=(5, 12))
        self._render_queue()

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

        appearance_frame = ctk.CTkFrame(settings_container, fg_color="#020408", border_width=1, border_color="#111827")
        appearance_frame.pack(fill="x", pady=8, padx=5)
        ctk.CTkLabel(appearance_frame, text="HOLOGRAM GLASS", font=("Consolas", 11, "bold"), text_color=self.neon_cyan).pack(anchor="w", padx=10, pady=(8, 2))
        ctk.CTkLabel(
            appearance_frame, text="Window opacity: 88% (stable compositor alpha; blur depends on the desktop compositor)",
            font=("Consolas", 10), text_color=self.text_dim,
        ).pack(anchor="w", padx=10, pady=(0, 10))

    def create_about_tab_content(self):
        panel = ctk.CTkFrame(self.about_tab, fg_color="#020408", border_width=1, border_color=self.neon_cyan)
        panel.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(panel, text="ANY FILEDOWNLOADER", font=("Consolas", 22, "bold"), text_color=self.neon_cyan).pack(pady=(55, 8))
        ctk.CTkLabel(panel, text=f"v{APP_VERSION} · HOLOGRAM EDITION", font=("Consolas", 12, "bold"), text_color=self.neon_amber).pack()
        ctk.CTkLabel(
            panel,
            text="Local-first media, document, archive, and direct-file transfers.\nNo cookies or Authorization values are captured or forwarded.",
            font=("Consolas", 11), text_color="#FFFFFF", justify="center",
        ).pack(pady=18)

    def animate_hud(self):
        """Render real-throughput-driven arcs without blocking the Tk event loop."""
        self.hud_canvas.delete("all")
        cx, cy = self.canvas_size / 2, self.canvas_size / 2
        r = 72

        # Draw dark inner backing ring
        self.hud_canvas.create_oval(cx-r, cy-r, cx+r, cy+r, outline="#111827", width=3)

        snapshot = self.telemetry.snapshot()
        if snapshot.active and time.monotonic() - self.telemetry.updated_at > 1.0:
            snapshot = self.telemetry.mark_stalled()
        self.anim_angle = (self.anim_angle + hud_degrees_per_tick(snapshot.speed_bps, snapshot.active)) % 360
        arc_color = self.neon_amber if snapshot.active else "#374151"
        self.hud_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=self.anim_angle, extent=72, outline=arc_color, width=5, style="arc")
        self.hud_canvas.create_arc(cx-r, cy-r, cx+r, cy+r, start=(self.anim_angle + 180) % 360, extent=72, outline=arc_color, width=5, style="arc")
        inner = r - 13
        self.hud_canvas.create_arc(cx-inner, cy-inner, cx+inner, cy+inner, start=-self.anim_angle * 0.65, extent=44, outline=self.neon_pink if snapshot.active else "#1f2937", width=2, style="arc")
        center_text = f"{snapshot.progress_percent:.0f}%" if snapshot.progress_percent is not None else "--"

        # Center percentage text
        self.hud_canvas.create_text(cx, cy, text=center_text, fill=self.neon_cyan, font=("Consolas", 20, "bold"))
        self._update_stream_statistics(snapshot)
        self.after(40, self.animate_hud)

    @staticmethod
    def _format_duration(seconds):
        seconds = max(0, int(seconds or 0))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    @staticmethod
    def _format_rate(speed_bps):
        speed = max(0.0, float(speed_bps or 0.0))
        if speed >= 1024 * 1024:
            return f"{speed / (1024 * 1024):.2f} MB/s"
        if speed >= 1024:
            return f"{speed / 1024:.1f} KB/s"
        return f"{speed:.0f} B/s"

    def _update_stream_statistics(self, snapshot):
        jobs = self.download_queue.jobs()
        waiting = sum(job.status in {"queued", "active"} for job in jobs)
        progress_text = f"{snapshot.progress_percent:.0f}%" if snapshot.progress_percent is not None else "--"
        eta_text = self._format_duration(snapshot.eta_seconds) if snapshot.eta_seconds is not None else "--:--"
        speed_text = self._format_rate(snapshot.speed_bps)
        self.current_speed_mbps = snapshot.speed_bps / (1024 * 1024)
        self.current_progress_pct = int(snapshot.progress_percent or 0)
        self.stream_speed_value.configure(text=speed_text)
        self.stream_progress_value.configure(text=progress_text)
        self.stream_elapsed_value.configure(text=self._format_duration(snapshot.elapsed_seconds))
        self.stream_queue_value.configure(text=f"{waiting} item" if waiting == 1 else f"{waiting} items")
        self.stream_status_value.configure(
            text="ACTIVE" if snapshot.active else "IDLE",
            text_color=self.neon_cyan if snapshot.active else self.neon_amber,
        )
        self.speed_time_label.configure(
            text=f"Speed: {speed_text} | ETA: {eta_text} | Progress: {progress_text}"
        )

    def _safe_job_name(self, job):
        request = job.request
        return (
            request.get("browser_filename")
            or request.get("media_title")
            or request.get("title")
            or redact_url(request.get("url", ""))
            or "Untitled transfer"
        )

    def _render_queue(self):
        if not hasattr(self, "queue_list_frame"):
            return
        for widget in self.queue_list_frame.winfo_children():
            widget.destroy()
        jobs = self.download_queue.jobs()
        if not jobs:
            ctk.CTkLabel(
                self.queue_list_frame, text="NO TRANSFERS IN THIS SESSION",
                font=("Consolas", 11), text_color=self.text_dim,
            ).pack(pady=35)
        colors = {
            "queued": self.neon_amber,
            "active": self.neon_cyan,
            "completed": "#4ADE80",
            "failed": self.neon_pink,
            "cancelled": self.text_dim,
        }
        for job in jobs:
            row = ctk.CTkFrame(self.queue_list_frame, fg_color="#050911", border_width=1, border_color="#172033")
            row.pack(fill="x", padx=5, pady=5)
            ctk.CTkLabel(
                row, text=self._safe_job_name(job), anchor="w",
                font=("Consolas", 11, "bold"), text_color="#FFFFFF",
            ).pack(side="left", fill="x", expand=True, padx=12, pady=10)
            progress = f" {job.progress:.0f}%" if job.status in {"active", "completed"} else ""
            ctk.CTkLabel(
                row, text=f"{job.status.upper()}{progress}",
                font=("Consolas", 10, "bold"), text_color=colors.get(job.status, self.text_dim),
            ).pack(side="right", padx=12, pady=10)
        summary = f"{len(jobs)} item" if len(jobs) == 1 else f"{len(jobs)} items"
        self.queue_summary_label.configure(text=summary)
        active_count = sum(job.status in {"queued", "active"} for job in jobs)
        self.left_queue_label.configure(text=f"{active_count} items")
        self.left_history_label.configure(text=f"{len(self.session_history)} session")

    def _queue_job_changed(self, job):
        self.after(0, lambda current=job: self._apply_queue_job_change(current))

    def _apply_queue_job_change(self, job):
        if job.status == "active":
            self.is_downloading = True
            self.status_label.configure(text="STATUS: DATA STREAM ACTIVE")
            self.current_item_label.configure(text=self._safe_job_name(job))
        elif job.status in {"completed", "failed", "cancelled"}:
            if not any(item.id == job.id for item in self.session_history):
                self.session_history.append(job)
            if self.current_job_id == job.id:
                self.telemetry.finish()
                self.is_downloading = False
                self.current_job_id = ""
                if job.status == "completed":
                    self.status_label.configure(text="STATUS: DATA TRANSFER COMPLETE")
                elif job.status == "failed":
                    self.status_label.configure(text="STATUS: STREAM ERROR ENCOUNTERED")
                else:
                    self.status_label.configure(text="STATUS: TRANSFER CANCELLED")
        self._render_queue()

    def enqueue_request_threadsafe(self, request):
        if request.get("action") != "download" or not self.parse_urls(request.get("url", "")):
            return {"ok": False, "error": {"code": "invalid_request", "message": "Invalid download request"}}
        self.after(0, lambda: self.enqueue_download_request(request))
        return {"ok": True, "status": "queued", "pid": os.getpid()}

    def ipc_status(self):
        jobs = self.download_queue.jobs()
        telemetry = self.telemetry.snapshot()
        return {
            "ok": True,
            "pid": os.getpid(),
            "jobs": [
                {"id": job.id, "status": job.status, "progress": round(job.progress, 1)}
                for job in jobs
            ],
            "telemetry": {
                "active": telemetry.active,
                "downloaded_bytes": telemetry.downloaded_bytes,
                "total_bytes": telemetry.total_bytes,
                "speed_bps": round(telemetry.speed_bps, 1),
                "progress_percent": (
                    round(telemetry.progress_percent, 1)
                    if telemetry.progress_percent is not None
                    else None
                ),
                "elapsed_seconds": round(telemetry.elapsed_seconds, 1),
                "eta_seconds": (
                    round(telemetry.eta_seconds, 1)
                    if telemetry.eta_seconds is not None
                    else None
                ),
                "hud_degrees_per_tick": round(
                    hud_degrees_per_tick(telemetry.speed_bps, telemetry.active), 2
                ),
            },
        }

    def enqueue_download_request(self, request):
        request = dict(request)
        request["action"] = "download"
        request["url"] = request.get("url", "")
        request["_download_options"] = {
            "output_dir": self.download_path.get(),
            "selected_quality": self.quality_selection.get(),
            "is_playlist": self.playlist_var.get() == "on",
            "sorting_setting": self.sort_order.get(),
        }
        job = self.download_queue.enqueue(request)
        self.download_history.append(request["url"])
        self.left_urls_label.configure(text=f"{len(self.download_history)} detected")
        self.status_label.configure(text="STATUS: REQUEST QUEUED")
        self.current_item_label.configure(text=self._safe_job_name(job))
        self.activate_window()
        return job

    def _process_queue_job(self, job):
        request = job.request
        options = request.get("_download_options", {})
        output_dir = options.get("output_dir", self.download_path.get())
        try:
            Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise DownloadFailure(
                "filesystem_error",
                "Could not create the download directory.",
                redact_diagnostic(str(error)),
            ) from error
        self.current_job_id = job.id
        self._last_progress_ui_at = 0.0
        self._last_queue_progress_at = 0.0
        self.telemetry.start()
        return self._download_single_url(
            request["url"],
            output_dir,
            options.get("selected_quality", "Auto"),
            options.get("is_playlist", False),
            options.get("sorting_setting", "Newest to Oldest"),
            {key: value for key, value in request.items() if not key.startswith("_")},
        )

    def _accept_telemetry(self, downloaded, total, speed_bps=None):
        if hasattr(self, "telemetry"):
            snapshot = self.telemetry.update(downloaded, total, speed_bps)
            self.current_speed_mbps = snapshot.speed_bps / (1024 * 1024)
            self.current_progress_pct = int(snapshot.progress_percent or self.current_progress_pct)
            now = time.monotonic()
            should_refresh_queue = (
                now - getattr(self, "_last_queue_progress_at", 0.0) >= 0.25
                or snapshot.progress_percent == 100.0
            )
            if (
                should_refresh_queue
                and getattr(self, "current_job_id", "")
                and hasattr(self, "download_queue")
            ):
                self._last_queue_progress_at = now
                self.download_queue.update_progress(self.current_job_id, snapshot.progress_percent or 0)
            return snapshot
        return None

    def activate_window(self):
        try:
            self.deiconify()
            self.lift()
        except Exception:
            pass

    def close_application(self):
        try:
            self._persist_settings()
            self.download_queue.stop()
            if self.instance_service is not None:
                self.instance_service.stop()
        finally:
            self.destroy()

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
        urls = self.parse_urls(raw_text)
        
        if not urls:
            messagebox.showwarning("Missing URL", "Please enter or paste at least one valid link (http:// or https://) first.")
            return

        for url in urls:
            self.enqueue_download_request({
                "action": "download",
                "url": url,
                "detected_type": "UNKNOWN",
                "source": "manual",
            })
        self.url_entry.delete(0, "end")
        self.download_btn.configure(text="QUEUED")
        self.after(700, lambda: self.download_btn.configure(text="INITIATE DATA TRANSFER"))

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
            AnyFileDownloaderApp._accept_telemetry(self, downloaded, total_bytes, speed)

            self.after(0, lambda p=pct, s=speed_mbps, e=eta_str: (
                self.progress_bar.set(p / 100.0),
                self.speed_time_label.configure(text=f"Speed: {s:.2f} MB/s | ETA: {e} | Progress: {p}%")
            ))
        elif d.get('status') == 'finished':
            if hasattr(self, "telemetry"):
                self.telemetry.update(
                    d.get("total_bytes") or d.get("downloaded_bytes") or 0,
                    d.get("total_bytes") or d.get("downloaded_bytes") or 0,
                    0,
                )
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
        """Run the response-aware direct downloader and update the existing HUD."""
        request_context = request_context or {}

        def show_metadata(filename, detected_type, total_size):
            if hasattr(self, "telemetry") and total_size and not self.telemetry.total_bytes:
                self.telemetry.total_bytes = total_size
            size_text = f" ({total_size / (1024 * 1024):.1f} MB)" if total_size else ""
            self.after(0, lambda: self.status_label.configure(
                text=f"STATUS: DOWNLOADING {detected_type}: {filename}{size_text}"
            ))

        def show_progress(downloaded, total_size, elapsed):
            snapshot = AnyFileDownloaderApp._accept_telemetry(self, downloaded, total_size)
            speed_mbps = (
                snapshot.speed_bps / (1024 * 1024)
                if snapshot is not None
                else downloaded / max(elapsed, 0.001) / (1024 * 1024)
            )
            pct = min(100, int(downloaded / total_size * 100)) if total_size else 50
            remaining = max(0, total_size - downloaded)
            eta = int(remaining / (speed_mbps * 1024 * 1024)) if total_size and speed_mbps else 0
            eta_str = f"{eta // 60:02d}:{eta % 60:02d}" if eta else "--:--"
            self.current_progress_pct = pct
            self.current_speed_mbps = speed_mbps
            now = time.monotonic()
            if (
                now - getattr(self, "_last_progress_ui_at", 0.0) < 0.1
                and pct < 100
            ):
                return
            self._last_progress_ui_at = now
            self.after(0, lambda: (
                self.progress_bar.set(pct / 100.0),
                self.speed_time_label.configure(
                    text=f"Speed: {speed_mbps:.2f} MB/s | ETA: {eta_str} | Progress: {pct}%"
                ),
            ))

        return download_direct_file(
            url,
            output_dir,
            request_context,
            progress_callback=show_progress,
            metadata_callback=show_metadata,
        )

    def _retry_status(self, engine, url, request_context, next_attempt, maximum, error, delay, detected_type="HLS"):
        log_event(
            LOGGER,
            "download_retry_scheduled",
            url,
            request_context,
            detected_type=detected_type,
            category=map_exception(error).category,
        )
        self.after(0, lambda: self.status_label.configure(
            text=f"STATUS: {detected_type} {engine} RETRY [{next_attempt}/{maximum}] IN {delay:.1f}s..."
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

        should_try_direct = decision.engine == "direct" or (
            selected_quality == "Auto" and detected_type in {"UNKNOWN", "DIRECT"}
        )
        if should_try_direct:
            log_event(LOGGER, "dispatch_selected", url, request_context, detected_type=detected_type, category="direct")
            try:
                final_path = run_with_retry(
                    lambda: self._download_direct_file(url, output_dir, request_context),
                    DIRECT_RETRY_POLICY,
                    lambda attempt, maximum, error, delay: self._retry_status(
                        "TRANSFER", url, request_context, attempt, maximum, error, delay, detected_type
                    ),
                )
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
                if detected_type in {"DOCUMENT", "ARCHIVE", "FILE"} or yt_dlp is None:
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


class DesktopRequestRouter:
    """Bridge the IPC thread to Tk, including requests received during startup."""

    def __init__(self):
        self.app = None
        self.pending = []
        self.lock = threading.Lock()

    def attach(self, app):
        with self.lock:
            self.app = app
            pending = self.pending
            self.pending = []
        for request in pending:
            self.handle(request)

    def handle(self, message):
        if message.get("action") == "activate":
            with self.lock:
                app = self.app
            if app is not None:
                app.after(0, app.activate_window)
            return {"ok": True, "status": "active"}
        if message.get("action") == "status":
            with self.lock:
                app = self.app
            return app.ipc_status() if app is not None else {"ok": True, "status": "starting", "jobs": []}
        if message.get("action") != "download":
            return {"ok": False, "error": {"code": "invalid_request", "message": "Unsupported IPC action"}}
        with self.lock:
            app = self.app
            if app is None:
                self.pending.append(dict(message))
                return {"ok": True, "status": "startup_queue", "pid": os.getpid()}
        return app.enqueue_request_threadsafe(message)


def command_line_request(arguments):
    if not arguments.download_url:
        return None
    return {
        "action": "download",
        "url": arguments.download_url,
        "page_url": arguments.page_url,
        "title": arguments.title,
        "detected_type": arguments.detected_type,
        "mime_type": arguments.mime_type,
        "source": arguments.source,
        "media_title": arguments.media_title,
        "browser_filename": arguments.browser_filename,
        "link_text": arguments.link_text,
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


def forward_to_running_desktop(message, attempts=50, delay=0.1):
    for _attempt in range(attempts):
        try:
            response = send_ipc_message(message)
            if response.get("ok"):
                return True
        except (OSError, ValueError, RuntimeError):
            time.sleep(delay)
    return False

def parse_command_line():
    parser = argparse.ArgumentParser(description="AnyFileDownloader desktop application")
    parser.add_argument("--download-url", default="", help="URL forwarded by the native messaging host")
    parser.add_argument("--page-url", default="", help="Source page URL supplied by the browser")
    parser.add_argument("--title", default="", help="Suggested page/media title supplied by the browser")
    parser.add_argument("--media-title", default="", help="Media-element title supplied by the browser")
    parser.add_argument("--browser-filename", default="", help="Filename metadata supplied by the browser")
    parser.add_argument("--link-text", default="", help="Safe anchor text supplied by the browser")
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
    initial_request = command_line_request(arguments)
    router = DesktopRequestRouter()
    instance_service = SingleInstanceService(router.handle)
    if not instance_service.start():
        message = initial_request or {"action": "activate"}
        raise SystemExit(0 if forward_to_running_desktop(message) else 1)

    app = AnyFileDownloaderApp()
    app.instance_service = instance_service
    router.attach(app)
    if initial_request:
        router.handle(initial_request)
    try:
        app.mainloop()
    finally:
        instance_service.stop()
