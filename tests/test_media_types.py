import unittest

from media_types import classify_media, is_direct_media_url, strip_url_fragment


class MediaTypeTests(unittest.TestCase):
    def test_detects_hls_and_preserves_signed_query(self):
        url = "https://cdn.example/live/master.m3u8?token=secret#player"
        self.assertEqual(classify_media(url), "HLS")
        self.assertEqual(strip_url_fragment(url), "https://cdn.example/live/master.m3u8?token=secret")

    def test_detects_dash_by_extension_and_mime(self):
        self.assertEqual(classify_media("https://cdn.example/manifest.mpd"), "DASH")
        self.assertEqual(classify_media("https://cdn.example/manifest", "application/dash+xml"), "DASH")

    def test_detects_direct_video_and_audio(self):
        self.assertEqual(classify_media("https://cdn.example/movie.MP4?signature=abc"), "VIDEO")
        self.assertEqual(classify_media("https://cdn.example/song", "audio/flac"), "AUDIO")
        self.assertTrue(is_direct_media_url("https://cdn.example/song.m4a?token=abc"))

    def test_ignores_non_media_resources(self):
        self.assertIsNone(classify_media("https://example.com/app.js", "application/javascript"))
        self.assertIsNone(classify_media("https://example.com/logo.png", "image/png"))


if __name__ == "__main__":
    unittest.main()
