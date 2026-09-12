import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from download_errors import DownloadFailure
from downloader import AnyFileDownloaderApp
from retry_policy import RetryPolicy


class _RoutingDownloader:
    def _retry_status(self, *_args):
        pass


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


if __name__ == "__main__":
    unittest.main()
