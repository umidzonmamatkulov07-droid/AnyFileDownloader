import unittest
from unittest.mock import Mock, patch

from downloader import AnyFileDownloaderApp


class _CompletionUI:
    is_downloading = True
    current_speed_mbps = 1.0
    current_progress_pct = 20
    progress_bar = Mock()
    status_label = Mock()
    speed_time_label = Mock()
    download_btn = Mock()


class CompletionUITests(unittest.TestCase):
    def test_success_and_warning_completion_do_not_open_popup(self):
        ui = _CompletionUI()
        with patch("downloader.messagebox.showwarning") as warning:
            AnyFileDownloaderApp._on_download_complete(ui, ["one warning"])
        warning.assert_not_called()
        ui.status_label.configure.assert_called_with(text="STATUS: TRANSFER COMPLETE WITH WARNINGS")


if __name__ == "__main__":
    unittest.main()
