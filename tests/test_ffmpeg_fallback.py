import unittest
from pathlib import Path

from ffmpeg_fallback import build_ffmpeg_hls_command


class FFmpegFallbackTests(unittest.TestCase):
    def test_command_is_argument_list_with_request_context(self):
        url = "https://cdn.example/master.m3u8?signature=abc"
        output = Path("video.mp4.part")
        context = {
            "referer": "https://example.com/watch",
            "origin": "https://example.com",
            "user_agent": "Browser Test",
            "Authorization": "Bearer should-not-be-forwarded",
            "Cookie": "session=should-not-be-forwarded",
        }
        command = build_ffmpeg_hls_command("/usr/bin/ffmpeg", url, output, context)

        self.assertIsInstance(command, list)
        self.assertIn(url, command)
        self.assertIn(context["referer"], command)
        self.assertIn(context["user_agent"], command)
        self.assertEqual(command[-1], str(output))
        self.assertNotIn("shell=True", command)
        self.assertNotIn(context["Authorization"], command)
        self.assertNotIn(context["Cookie"], command)


if __name__ == "__main__":
    unittest.main()
