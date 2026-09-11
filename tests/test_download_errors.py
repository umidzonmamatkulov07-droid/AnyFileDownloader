import unittest
import urllib.error

from download_errors import hls_validation_failure, map_exception


class DownloadErrorTests(unittest.TestCase):
    def test_http_categories(self):
        forbidden = urllib.error.HTTPError("https://example.com", 403, "Forbidden", {}, None)
        missing = urllib.error.HTTPError("https://example.com", 404, "Missing", {}, None)
        try:
            self.assertEqual(map_exception(forbidden).category, "http_forbidden")
            self.assertEqual(map_exception(missing).category, "http_not_found")
        finally:
            forbidden.close()
            missing.close()

    def test_hls_error_category(self):
        failure = hls_validation_failure("html_response")
        self.assertEqual(failure.category, "invalid_hls_manifest")
        self.assertIn("HTML", failure.message)

    def test_exception_messages_redact_signed_urls(self):
        failure = map_exception(OSError("failed https://cdn.test/master.m3u8?token=secret"))
        self.assertNotIn("secret", failure.message)
        self.assertIn("query-redacted", failure.message)


if __name__ == "__main__":
    unittest.main()
