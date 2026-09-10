import io
import json
import struct
import unittest

from native_host import encode_message, read_message, validate_download_request


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

    def test_empty_stream_signals_shutdown(self):
        self.assertIsNone(read_message(io.BytesIO()))


if __name__ == "__main__":
    unittest.main()
