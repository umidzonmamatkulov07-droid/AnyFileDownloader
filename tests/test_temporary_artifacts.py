import tempfile
import unittest
from pathlib import Path

from temporary_artifacts import (
    final_media_files,
    is_temporary_artifact,
    looks_like_mpegts,
    normalize_hls_container_extensions,
    promote_downloaded_files,
)


class TemporaryArtifactTests(unittest.TestCase):
    def test_mpegts_content_gets_accurate_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "episode.mp4"
            packet = bytes([0x47]) + bytes(187)
            source.write_bytes(packet * 3)

            normalized = normalize_hls_container_extensions([source])

            self.assertEqual(normalized[0].name, "episode.ts")
            self.assertTrue(looks_like_mpegts(normalized[0]))
            self.assertFalse(source.exists())

    def test_real_mp4_is_not_renamed_as_transport_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "episode.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(600))

            normalized = normalize_hls_container_extensions([source])

            self.assertEqual(normalized, [source])

    def test_temporary_patterns_are_excluded(self):
        self.assertTrue(is_temporary_artifact(Path("video.mp4.part")))
        self.assertTrue(is_temporary_artifact(Path("video.f137.mp4")))
        self.assertFalse(is_temporary_artifact(Path("video.mp4")))

    def test_only_final_files_are_promoted_and_duplicates_are_safe(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            staging = root_path / "staging"
            output = root_path / "output"
            staging.mkdir()
            output.mkdir()
            (output / "Episode 7.mp4").write_bytes(b"existing")
            source = staging / "master.mp4"
            source.write_bytes(b"media")
            (staging / "master.mp4.part").write_bytes(b"partial")

            sources = final_media_files(staging)
            promoted = promote_downloaded_files(
                sources,
                output,
                "https://cdn.test/master.m3u8?token=secret",
                {"title": "Episode 7"},
            )

            self.assertEqual([path.name for path in promoted], ["Episode 7 (1).mp4"])
            self.assertEqual(promoted[0].read_bytes(), b"media")
            self.assertTrue((staging / "master.mp4.part").exists())


if __name__ == "__main__":
    unittest.main()
