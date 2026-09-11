import tempfile
import unittest
from pathlib import Path

from ytdlp_options import build_ytdlp_options


class YTDLPOptionsTests(unittest.TestCase):
    def test_hls_context_headers_are_forwarded_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            context = {
                "referer": "https://page.test/watch?episode=4",
                "origin": "https://page.test",
                "user_agent": "Browser Test",
                "accept": "*/*",
                "accept_language": "en-US,en;q=0.9",
                "detected_type": "HLS",
                "Cookie": "forbidden",
                "Authorization": "forbidden",
            }
            options = build_ytdlp_options(Path(directory), "Auto", False, "Newest to Oldest", True, context)
        self.assertEqual(options["http_headers"], {
            "User-Agent": "Browser Test",
            "Referer": "https://page.test/watch?episode=4",
            "Origin": "https://page.test",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.assertEqual(options["concurrent_fragment_downloads"], 1)
        self.assertEqual(options["fragment_retries"], 2)
        self.assertTrue(options["hls_use_mpegts"])

    def test_explicit_resolution_enables_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            options = build_ytdlp_options(Path(directory), "720p MP4", False, "Newest to Oldest", True)
        self.assertIn("bestvideo", options["format"])
        self.assertEqual(options["merge_output_format"], "mp4")
        self.assertNotIn("hls_use_mpegts", options)


if __name__ == "__main__":
    unittest.main()
