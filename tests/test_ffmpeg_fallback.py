import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from download_errors import DownloadFailure
from ffmpeg_fallback import (
    HLS_ALLOWED_SEGMENT_EXTENSIONS,
    build_ffmpeg_hls_command,
    run_ffmpeg_hls_fallback,
)


class FFmpegFallbackTests(unittest.TestCase):
    def test_command_is_argument_list_with_request_context(self):
        url = "https://cdn.example/master.m3u8?signature=abc"
        output = Path("video.mp4.part")
        context = {
            "referer": "https://example.com/watch",
            "origin": "https://example.com",
            "user_agent": "Browser Test",
            "accept": "*/*",
            "accept_language": "en-US,en;q=0.9",
            "Authorization": "Bearer should-not-be-forwarded",
            "Cookie": "session=should-not-be-forwarded",
        }
        command = build_ffmpeg_hls_command("/usr/bin/ffmpeg", url, output, context)

        self.assertIsInstance(command, list)
        self.assertIn(url, command)
        self.assertIn(context["referer"], command)
        self.assertIn(context["user_agent"], command)
        combined_headers = command[command.index("-headers") + 1]
        self.assertIn("Origin: https://example.com", combined_headers)
        self.assertIn("Accept: */*", combined_headers)
        self.assertIn("Accept-Language: en-US,en;q=0.9", combined_headers)
        allowed_extensions = command[command.index("-allowed_segment_extensions") + 1]
        self.assertEqual(allowed_extensions, HLS_ALLOWED_SEGMENT_EXTENSIONS)
        for disguised_extension in ("jpg", "jpeg", "png", "webp", "ico", "txt", "css", "js", "html"):
            self.assertIn(disguised_extension, allowed_extensions.split(","))
        self.assertNotIn("ALL", allowed_extensions)
        self.assertLess(command.index("-allowed_segment_extensions"), command.index("-i"))
        self.assertEqual(command[command.index("-extension_picky") + 1], "0")
        self.assertLess(command.index("-extension_picky"), command.index("-i"))
        self.assertEqual(command[-1], str(output))
        self.assertNotIn("shell=True", command)
        self.assertNotIn(context["Authorization"], command)
        self.assertNotIn(context["Cookie"], command)

    def test_mp4_header_failure_falls_back_to_mpegts(self):
        calls = []

        def run(command, **_kwargs):
            calls.append(command)
            if command[command.index("-f") + 1] == "mp4":
                return SimpleNamespace(returncode=1, stderr="dimensions not set; Could not write header")
            Path(command[-1]).write_bytes(b"complete transport stream")
            return SimpleNamespace(returncode=0, stderr="")

        with tempfile.TemporaryDirectory() as directory, patch("ffmpeg_fallback.subprocess.run", side_effect=run):
            completed = run_ffmpeg_hls_fallback(
                "/usr/bin/ffmpeg", "https://cdn.test/index.m3u8", directory, "Episode 4"
            )

            self.assertEqual(completed.name, "Episode 4.ts")
            self.assertEqual(completed.read_bytes(), b"complete transport stream")
            self.assertEqual([call[call.index("-f") + 1] for call in calls], ["mp4", "mpegts"])

    def test_transport_failure_does_not_switch_container(self):
        result = SimpleNamespace(returncode=1, stderr="HTTP error 503: temporarily unavailable")
        with tempfile.TemporaryDirectory() as directory, patch(
            "ffmpeg_fallback.subprocess.run", return_value=result
        ) as run:
            with self.assertRaises(DownloadFailure):
                run_ffmpeg_hls_fallback(
                    "/usr/bin/ffmpeg", "https://cdn.test/index.m3u8", directory, "Episode 5"
                )

        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
