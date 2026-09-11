import unittest

from download_policy import choose_download_engine


class DownloadPolicyTests(unittest.TestCase):
    def test_hls_and_dash_always_use_ytdlp(self):
        self.assertEqual(choose_download_engine("https://cdn.test/master.m3u8?token=x").engine, "yt_dlp")
        self.assertEqual(choose_download_engine("https://cdn.test/manifest", mime_type="application/dash+xml").engine, "yt_dlp")

    def test_auto_direct_media_and_documents_use_direct_engine(self):
        self.assertEqual(choose_download_engine("https://cdn.test/movie.mp4").engine, "direct")
        self.assertEqual(choose_download_engine("https://cdn.test/archive.zip").engine, "direct")

    def test_conversion_and_webpages_use_ytdlp(self):
        self.assertEqual(choose_download_engine("https://cdn.test/movie.mp4", "720p MP4").engine, "yt_dlp")
        self.assertEqual(choose_download_engine("https://example.test/watch/1").engine, "yt_dlp")


if __name__ == "__main__":
    unittest.main()
