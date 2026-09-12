import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from download_errors import DownloadFailure
from download_queue import DownloadJob
from download_telemetry import DownloadTelemetry
from downloader import AnyFileDownloaderApp
from retry_policy import RetryPolicy


class _RoutingDownloader:
    def _retry_status(self, *_args):
        pass


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class DownloaderRoutingTests(unittest.TestCase):
    def test_document_failure_does_not_fall_through_to_ytdlp(self):
        app = _RoutingDownloader()
        app._download_direct_file = Mock(side_effect=DownloadFailure("invalid_response", "bad document response"))
        app._run_ytdlp_download = Mock()

        with tempfile.TemporaryDirectory() as directory, patch(
            "downloader.DIRECT_RETRY_POLICY", RetryPolicy(max_attempts=1, delays=())
        ):
            with self.assertRaises(DownloadFailure):
                AnyFileDownloaderApp._download_single_url(
                    app,
                    "https://files.test/report.pdf",
                    directory,
                    "Auto",
                    False,
                    "Newest to Oldest",
                    {"detected_type": "DOCUMENT", "mime_type": "application/pdf"},
                )

        app._run_ytdlp_download.assert_not_called()

    def test_extensionless_direct_response_can_complete_before_ytdlp(self):
        app = _RoutingDownloader()
        with tempfile.TemporaryDirectory() as directory:
            completed = Path(directory) / "report.pdf"
            completed.write_bytes(b"fixture")
            app._download_direct_file = Mock(return_value=completed)
            app._run_ytdlp_download = Mock()

            result = AnyFileDownloaderApp._download_single_url(
                app,
                "https://files.test/download?id=42",
                directory,
                "Auto",
                False,
                "Newest to Oldest",
                {"detected_type": "DIRECT"},
            )

        self.assertEqual(result, [completed])
        app._run_ytdlp_download.assert_not_called()

    def test_browser_queue_creates_missing_download_directory(self):
        app = _RoutingDownloader()
        app.download_path = _Value("unused")
        app.quality_selection = _Value("Auto")
        app.playlist_var = _Value("off")
        app.sort_order = _Value("Newest to Oldest")
        app.telemetry = DownloadTelemetry()
        app.current_job_id = ""
        app._download_single_url = Mock(return_value=[])

        with tempfile.TemporaryDirectory() as parent:
            destination = Path(parent) / "new" / "downloads"
            job = DownloadJob({
                "action": "download",
                "url": "https://files.test/report.pdf",
                "_download_options": {
                    "output_dir": str(destination),
                    "selected_quality": "Auto",
                    "is_playlist": False,
                    "sorting_setting": "Newest to Oldest",
                },
            })
            AnyFileDownloaderApp._process_queue_job(app, job)
            self.assertTrue(destination.is_dir())

        app._download_single_url.assert_called_once()


if __name__ == "__main__":
    unittest.main()
