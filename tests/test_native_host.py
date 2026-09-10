import io
import json
import struct
import unittest
from unittest.mock import patch

from native_host import encode_message, handle_message, read_message, run, validate_download_request


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
            "detected_type": "HLS",
            "mime_type": "application/vnd.apple.mpegurl",
            "source": "webRequest",
            "referer": "https://example.com/watch",
            "origin": "https://example.com",
            "user_agent": "Test browser",
        })
        self.assertEqual(request["detected_type"], "HLS")
        self.assertEqual(request["source"], "webRequest")
        self.assertIn("token=abc", request["url"])

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
        with self.assertLogs("anyfiledownloader.native_host", level="ERROR"):
            with patch("native_host.forward_download_request", side_effect=OSError("missing app")):
                response = handle_message({"action": "download", "url": "https://example.com/video.mp4"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "launch_failed")

    def test_empty_stream_signals_shutdown(self):
        self.assertIsNone(read_message(io.BytesIO()))


if __name__ == "__main__":
    unittest.main()
