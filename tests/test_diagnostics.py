import io
import logging
import unittest

from diagnostics import log_event, redact_diagnostic, redact_url


class DiagnosticsTests(unittest.TestCase):
    def test_query_values_are_redacted(self):
        redacted = redact_url("https://cdn.example/master.m3u8?token=secret&expires=123#fragment")
        self.assertIn("query-redacted", redacted)
        self.assertNotIn("secret", redacted)
        self.assertNotIn("123", redacted)

    def test_sensitive_headers_are_not_logged(self):
        stream = io.StringIO()
        logger = logging.Logger("diagnostics-test")
        logger.addHandler(logging.StreamHandler(stream))
        context = {
            "referer": "https://example.com/watch?token=referer-secret",
            "Authorization": "Bearer authorization-secret",
            "Cookie": "session=cookie-secret",
        }

        log_event(
            logger,
            "candidate_classified",
            "https://cdn.example/master.m3u8?token=url-secret",
            context,
            detected_type="HLS",
        )

        logged = stream.getvalue()
        self.assertNotIn("referer-secret", logged)
        self.assertNotIn("authorization-secret", logged)
        self.assertNotIn("cookie-secret", logged)
        self.assertNotIn("url-secret", logged)

    def test_urls_in_ffmpeg_diagnostics_are_redacted(self):
        text = (
            "Failed to open https://cdn.example/master.m3u8?signature=secret\n"
            "Authorization: Bearer authorization-secret\n"
            "Cookie: session=cookie-secret\n"
            "token=standalone-secret"
        )
        redacted = redact_diagnostic(text)
        self.assertNotIn("secret", redacted)
        self.assertIn("<redacted>", redacted)


if __name__ == "__main__":
    unittest.main()
