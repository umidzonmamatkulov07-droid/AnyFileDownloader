import tempfile
import unittest
from pathlib import Path

from filename_resolver import (
    filename_from_response,
    finalize_download,
    reserve_download_path,
    resolve_filename,
    sanitize_filename,
    unique_path,
)


class FilenameResolverTests(unittest.TestCase):
    def test_sanitizes_paths_and_windows_unsafe_characters(self):
        self.assertEqual(sanitize_filename("../../bad:name?.mp4"), "bad_name_.mp4")
        self.assertEqual(sanitize_filename(r"..\..\CON.txt"), "_CON.txt")
        self.assertEqual(sanitize_filename("NUL.archive.zip"), "_NUL.archive.zip")

    def test_server_filename_is_preferred_and_sanitized(self):
        name = filename_from_response(
            "https://example.com/fallback.bin",
            "attachment; filename*=UTF-8''A%20Useful%20File.pdf",
            "Page title",
        )
        self.assertEqual(name, "A Useful File.pdf")

    def test_browser_filename_precedes_url_and_link_text(self):
        name = filename_from_response(
            "https://example.com/url-name.pdf",
            browser_filename="browser-name.pdf",
            link_text="link name",
            mime_type="application/pdf",
        )
        self.assertEqual(name, "browser-name.pdf")

    def test_mime_corrects_a_misleading_extension(self):
        name = filename_from_response("https://example.com/report.exe", mime_type="application/pdf")
        self.assertEqual(name, "report.pdf")

    def test_known_mime_adds_missing_extension(self):
        name = filename_from_response(
            "https://cdn.example/download",
            suggested_title="Recorded session",
            mime_type="video/mp4; charset=binary",
        )
        self.assertEqual(name, "Recorded session.mp4")

    def test_browser_title_cannot_escape_destination(self):
        name = filename_from_response(
            "https://cdn.example/",
            suggested_title="../../outside.mp4",
            mime_type="video/mp4",
        )
        self.assertEqual(name, "outside.mp4")

    def test_page_metadata_replaces_generic_hls_name(self):
        name = resolve_filename(
            "https://cdn.example/master.m3u8?token=secret",
            page_title="Series Name - Episode 12",
            extractor_title="master",
            extension=".mp4",
        )
        self.assertEqual(name, "Series Name - Episode 12.mp4")

    def test_extractor_title_beats_meaningful_url_basename(self):
        name = resolve_filename(
            "https://cdn.example/opaque-video.mp4",
            extractor_title="Recovered Episode 4",
            extension=".mp4",
        )
        self.assertEqual(name, "Recovered Episode 4.mp4")

    def test_duplicate_names_get_numbered_suffixes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "file.mp4").touch()
            (directory / "file (1).mp4").touch()

            self.assertEqual(unique_path(directory, "file.mp4").name, "file (2).mp4")

    def test_reserved_part_is_only_finalized_after_success(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            final_path, part_path = reserve_download_path(temporary_directory, "safe.pdf")
            part_path.write_bytes(b"complete")

            self.assertFalse(final_path.exists())
            completed_path = finalize_download(part_path, final_path)

            self.assertEqual(completed_path.read_bytes(), b"complete")
            self.assertFalse(part_path.exists())


if __name__ == "__main__":
    unittest.main()
