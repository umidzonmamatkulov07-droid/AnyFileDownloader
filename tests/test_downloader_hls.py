import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import downloader
from downloader import AnyFileDownloaderApp
from retry_policy import RetryPolicy


class _FakeYDL:
    calls = []
    failures_remaining = 0

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def extract_info(self, url, download):
        self.__class__.calls.append((url, self.options["http_headers"], download))
        if self.__class__.failures_remaining:
            self.__class__.failures_remaining -= 1
            raise ConnectionResetError("connection reset")
        output = Path(self.options["outtmpl"].replace("%(title)s", "master").replace("%(ext)s", "mp4"))
        output.write_bytes(b"complete-media")
        return {"title": "master"}


class _DummyDownloader:
    has_ffmpeg = True

    def _yt_dlp_progress_hook(self, _data):
        pass

    def _retry_status(self, *_args):
        pass


class _ProgressControl:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value

    def configure(self, **values):
        self.value = values


class _ProgressDownloader:
    current_progress_pct = 0
    current_speed_mbps = 0.0

    def __init__(self):
        self.progress_bar = _ProgressControl()
        self.speed_time_label = _ProgressControl()

    def after(self, _delay, callback):
        callback()


class DownloaderHLSTests(unittest.TestCase):
    def test_float_eta_from_ytdlp_updates_hud_without_aborting_download(self):
        app = _ProgressDownloader()

        AnyFileDownloaderApp._yt_dlp_progress_hook(app, {
            "status": "downloading",
            "total_bytes_estimate": 1000,
            "downloaded_bytes": 10,
            "speed": 100,
            "eta": 182.0,
        })

        self.assertEqual(app.current_progress_pct, 1)
        self.assertEqual(app.speed_time_label.value["text"], "Speed: 0.00 MB/s | ETA: 03:02 | Progress: 1%")

    def test_retries_keep_complete_url_and_headers_then_clean_staging(self):
        signed_url = "https://cdn.test/master.m3u8?token=secret&expires=123"
        context = {
            "title": "Episode 11",
            "referer": "https://page.test/watch/11",
            "origin": "https://page.test",
            "user_agent": "Test Browser",
            "accept": "*/*",
            "accept_language": "en-US,en;q=0.9",
        }
        _FakeYDL.calls = []
        _FakeYDL.failures_remaining = 2

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(downloader.yt_dlp, "YoutubeDL", _FakeYDL), patch.object(
                downloader, "HLS_RETRY_POLICY", RetryPolicy(max_attempts=3, delays=(0, 0))
            ):
                completed = AnyFileDownloaderApp._run_ytdlp_download(
                    _DummyDownloader(), signed_url, output, "Auto", False,
                    "Newest to Oldest", context, "HLS"
                )

            self.assertEqual([path.name for path in completed], ["Episode 11.mp4"])
            self.assertEqual(completed[0].read_bytes(), b"complete-media")
            self.assertEqual(len(_FakeYDL.calls), 3)
            self.assertTrue(all(call[0] == signed_url for call in _FakeYDL.calls))
            self.assertTrue(all(call[1]["Referer"] == context["referer"] for call in _FakeYDL.calls))
            self.assertTrue(all(call[1]["Origin"] == context["origin"] for call in _FakeYDL.calls))
            self.assertTrue(all(call[1]["User-Agent"] == context["user_agent"] for call in _FakeYDL.calls))
            self.assertTrue(all(call[1]["Accept"] == context["accept"] for call in _FakeYDL.calls))
            self.assertTrue(all(call[1]["Accept-Language"] == context["accept_language"] for call in _FakeYDL.calls))
            self.assertFalse(any(path.name.startswith(".afd-ytdlp-") for path in output.iterdir()))


if __name__ == "__main__":
    unittest.main()
