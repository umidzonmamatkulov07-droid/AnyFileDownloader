import io
import json
import os
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

from native_host import desktop_command, encode_message, handle_message, read_message, run, validate_download_request


class NativeMessageTests(unittest.TestCase):
    def test_round_trip_uses_little_endian_length_prefix(self):
        message = {"action": "download", "url": "https://example.com/video", "title": "Example"}
        encoded = encode_message(message)
        payload_length = struct.unpack("<I", encoded[:4])[0]

        self.assertEqual(payload_length, len(encoded) - 4)
        self.assertEqual(read_message(io.BytesIO(encoded)), message)

    def test_reads_known_framed_json(self):
        payload = json.dumps({"ok": True}).encode("utf-8")
        framed = struct.pack("<I", len(payload)) + payload
        self.assertEqual(read_message(io.BytesIO(framed)), {"ok": True})

    def test_rejects_unsupported_action(self):
        with self.assertRaisesRegex(ValueError, "Unsupported action"):
            validate_download_request({"action": "ping", "url": "https://example.com"})

    def test_rejects_url_without_a_host(self):
        with self.assertRaisesRegex(ValueError, "valid HTTP"):
            validate_download_request({"action": "download", "url": "https://"})

    def test_rejects_null_characters_before_process_launch(self):
        with self.assertRaisesRegex(ValueError, "null character"):
            validate_download_request({
                "action": "download",
                "url": "https://example.com/video.mp4",
                "title": "bad\x00title",
            })

    def test_extended_request_metadata_is_validated_and_preserved(self):
        request = validate_download_request({
            "action": "download",
            "url": "https://cdn.example/master.m3u8?token=abc",
            "page_url": "https://example.com/watch",
            "title": "Example",
            "media_title": "Episode 9",
            "browser_filename": "episode-nine.mp4",
            "link_text": "Download episode nine",
            "detected_type": "HLS",
            "mime_type": "application/vnd.apple.mpegurl",
            "source": "webRequest",
            "referer": "https://example.com/watch",
            "origin": "https://example.com",
            "user_agent": "Test browser",
            "accept": "*/*",
            "accept_language": "en-US,en;q=0.9",
            "range": "bytes=0-",
            "sec_fetch_site": "cross-site",
        })
        self.assertEqual(request["detected_type"], "HLS")
        self.assertEqual(request["source"], "webRequest")
        self.assertEqual(request["media_title"], "Episode 9")
        self.assertEqual(request["browser_filename"], "episode-nine.mp4")
        self.assertEqual(request["accept_language"], "en-US,en;q=0.9")
        self.assertEqual(request["range"], "bytes=0-")
        self.assertIn("token=abc", request["url"])

    def test_rejects_header_newline_injection(self):
        with self.assertRaisesRegex(ValueError, "invalid newline"):
            validate_download_request({
                "action": "download",
                "url": "https://cdn.example/master.m3u8",
                "accept": "*/*\r\nCookie: injected",
            })

    def test_anchor_document_metadata_is_accepted(self):
        request = validate_download_request({
            "action": "download",
            "url": "https://files.example/download?id=7",
            "detected_type": "DOCUMENT",
            "source": "anchor_link",
            "browser_filename": "report.docx",
            "link_text": "Quarterly report",
        })
        self.assertEqual(request["source"], "anchor_link")
        self.assertEqual(request["detected_type"], "DOCUMENT")
        command = desktop_command(request)
        self.assertIn("--browser-filename", command)
        self.assertIn("report.docx", command)

    def test_browser_event_and_download_anchor_sources_are_accepted(self):
        for source in ("chrome_download", "anchor_download"):
            request = validate_download_request({
                "action": "download",
                "url": "https://files.example/report.pdf",
                "detected_type": "DOCUMENT",
                "source": source,
            })
            self.assertEqual(request["source"], source)

    def test_development_launch_path_is_absolute_and_not_cwd_dependent(self):
        request = validate_download_request({
            "action": "download",
            "url": "https://example.com/video.mp4",
        })
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANYFILEDOWNLOADER_APP", None)
            command = desktop_command(request)
        desktop_script = Path(command[1])
        self.assertTrue(desktop_script.is_absolute())
        self.assertEqual(desktop_script.name, "downloader.py")

    def test_ping_does_not_launch_downloader(self):
        with patch("native_host.forward_download_request") as forward:
            response = handle_message({"action": "ping"})
        self.assertTrue(response["ok"])
        forward.assert_not_called()

    def test_framed_ping_response_is_ready(self):
        output = io.BytesIO()
        run(io.BytesIO(encode_message({"action": "ping"})), output)
        output.seek(0)
        response = read_message(output)
        self.assertTrue(response["ok"])
        self.assertEqual(response["status"], "ready")

    def test_launch_failure_is_structured(self):
        with self.assertLogs("anyfiledownloader.native_host", level="INFO"):
            with patch("native_host.forward_download_request", side_effect=OSError("missing app")):
                response = handle_message({"action": "download", "url": "https://example.com/video.mp4"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "launch_failed")

    def test_empty_stream_signals_shutdown(self):
        self.assertIsNone(read_message(io.BytesIO()))


if __name__ == "__main__":
    unittest.main()
