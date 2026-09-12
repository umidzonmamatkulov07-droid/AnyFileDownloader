import unittest

from media_types import classify_download, classify_media, extension_for_mime, is_direct_media_url, strip_url_fragment


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

    def test_classifies_supported_documents_archives_and_installers(self):
        cases = {
            "report.pdf": "DOCUMENT",
            "report.doc": "DOCUMENT",
            "report.docx": "DOCUMENT",
            "budget.xls": "DOCUMENT",
            "budget.xlsx": "DOCUMENT",
            "slides.ppt": "DOCUMENT",
            "slides.pptx": "DOCUMENT",
            "notes.txt": "DOCUMENT",
            "formatted.rtf": "DOCUMENT",
            "table.csv": "DOCUMENT",
            "writing.odt": "DOCUMENT",
            "sheet.ods": "DOCUMENT",
            "slides.odp": "DOCUMENT",
            "book.epub": "DOCUMENT",
            "book.mobi": "DOCUMENT",
            "bundle.zip": "ARCHIVE",
            "bundle.rar": "ARCHIVE",
            "bundle.7z": "ARCHIVE",
            "bundle.tar": "ARCHIVE",
            "bundle.gz": "ARCHIVE",
            "bundle.bz2": "ARCHIVE",
            "package.apk": "FILE",
            "program.exe": "FILE",
            "installer.msi": "FILE",
            "disk.iso": "FILE",
            "image.dmg": "FILE",
            "package.deb": "FILE",
            "package.rpm": "FILE",
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(classify_download(f"https://cdn.example/{filename}"), expected)

    def test_mime_wins_over_a_misleading_url_extension(self):
        self.assertEqual(classify_download("https://cdn.example/file.exe", "application/pdf"), "DOCUMENT")
        self.assertEqual(extension_for_mime("application/pdf; charset=binary"), ".pdf")

    def test_content_disposition_detects_extensionless_attachment(self):
        self.assertEqual(
            classify_download(
                "https://cdn.example/download",
                "application/octet-stream",
                "report.docx",
                'attachment; filename="report.docx"',
            ),
            "DOCUMENT",
        )
        self.assertIsNone(classify_media("https://example.com/logo.png", "image/png"))


if __name__ == "__main__":
    unittest.main()
