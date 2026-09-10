import tempfile
import unittest
from pathlib import Path

from filename_resolver import (
    filename_from_response,
    finalize_download,
    reserve_download_path,
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
