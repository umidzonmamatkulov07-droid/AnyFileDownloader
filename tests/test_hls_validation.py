import io
import unittest
import urllib.error

from hls_validation import MAX_VALIDATION_BYTES, request_headers, validate_hls_url


class FakeHeaders(dict):
    def get_content_charset(self):
        return None


class FakeResponse:
    def __init__(self, body, content_type, url="https://cdn.example/master.m3u8", status=200):
        self.body = io.BytesIO(body)
        self.headers = FakeHeaders({"Content-Type": content_type})
        self.url = url
        self.status = status
        self.last_read_size = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.last_read_size = size
        return self.body.read(size)


def opener_for(response, captured=None):
    def open_request(request, timeout):
        if captured is not None:
            captured["request"] = request
            captured["timeout"] = timeout
        return response
    return open_request


class HLSValidationTests(unittest.TestCase):
    def test_valid_master_manifest(self):
        response = FakeResponse(
            b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000\nvideo.m3u8\n",
            "application/vnd.apple.mpegurl",
        )
        result = validate_hls_url(response.url, opener=opener_for(response))
        self.assertTrue(result.valid)
        self.assertEqual(result.playlist_type, "hls_master")

    def test_valid_media_manifest(self):
        response = FakeResponse(b"#EXTM3U\n#EXTINF:6.0,\nsegment.ts\n", "application/x-mpegURL")
        result = validate_hls_url(response.url, opener=opener_for(response))
        self.assertTrue(result.valid)
        self.assertEqual(result.playlist_type, "hls_media")

    def test_fake_m3u8_returning_html(self):
        response = FakeResponse(b"<!doctype html><title>Denied</title>", "text/html")
        result = validate_hls_url(response.url, opener=opener_for(response))
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "html_response")

    def test_fake_m3u8_returning_json(self):
        response = FakeResponse(b'{"error":"expired"}', "application/json")
        result = validate_hls_url(response.url, opener=opener_for(response))
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "json_response")

    def test_redirected_webpage_is_identified(self):
        response = FakeResponse(
            b"<html>Login page</html>",
            "text/html",
            url="https://example.com/login",
        )
        result = validate_hls_url("https://cdn.example/master.m3u8?signature=abc", opener=opener_for(response))
        self.assertTrue(result.redirected)
        self.assertEqual(result.final_url, "https://example.com/login")
        self.assertEqual(result.reason, "redirected_to_webpage")

    def test_valid_redirect_retains_final_url(self):
        response = FakeResponse(
            b"#EXTM3U\n#EXTINF:4,\nsegment.ts",
            "application/vnd.apple.mpegurl",
            url="https://edge.example/final.m3u8?signature=xyz",
        )
        result = validate_hls_url("https://cdn.example/start.m3u8?signature=abc", opener=opener_for(response))
        self.assertTrue(result.valid)
        self.assertTrue(result.redirected)
        self.assertIn("signature=xyz", result.final_url)

    def test_missing_extm3u_is_rejected(self):
        response = FakeResponse(b"not a playlist", "text/plain")
        result = validate_hls_url(response.url, opener=opener_for(response))
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "missing_extm3u")

    def test_mime_mismatch_is_diagnostic_but_valid(self):
        response = FakeResponse(b"#EXTM3U\n#EXTINF:4,\nsegment.ts", "text/plain")
        result = validate_hls_url(response.url, opener=opener_for(response))
        self.assertTrue(result.valid)
        self.assertEqual(result.reason, "valid_playlist_mime_mismatch")

    def test_request_context_and_bounded_read(self):
        captured = {}
        response = FakeResponse(b"#EXTM3U\n#EXTINF:4,\nsegment.ts", "application/vnd.apple.mpegurl")
        context = {
            "referer": "https://example.com/watch",
            "origin": "https://example.com",
            "user_agent": "Browser Test",
            "accept": "*/*",
            "accept_language": "en-US,en;q=0.9",
            "Authorization": "Bearer should-not-be-forwarded",
            "Cookie": "session=should-not-be-forwarded",
        }
        validate_hls_url(response.url, context, opener_for(response, captured))
        request = captured["request"]
        self.assertEqual(request.get_header("Referer"), context["referer"])
        self.assertEqual(request.get_header("Origin"), context["origin"])
        self.assertEqual(request.get_header("User-agent"), context["user_agent"])
        self.assertEqual(request.get_header("Accept"), context["accept"])
        self.assertEqual(request.get_header("Accept-language"), context["accept_language"])
        self.assertIsNone(request.get_header("Range"))
        self.assertIsNone(request.get_header("Authorization"))
        self.assertIsNone(request.get_header("Cookie"))
        self.assertEqual(response.last_read_size, MAX_VALIDATION_BYTES)

    def test_http_forbidden_is_structured(self):
        def forbidden(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", FakeHeaders(), None)

        result = validate_hls_url("https://cdn.example/master.m3u8", opener=forbidden)
        self.assertFalse(result.valid)
        self.assertEqual(result.status_code, 403)
        self.assertEqual(result.reason, "http_error")

    def test_drm_marker_disables_fallback(self):
        response = FakeResponse(
            b"#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI=\"key\"\n#EXTINF:4,\nsegment.ts",
            "application/vnd.apple.mpegurl",
        )
        result = validate_hls_url(response.url, opener=opener_for(response))
        self.assertFalse(result.valid)
        self.assertTrue(result.drm_protected)
        self.assertEqual(result.reason, "drm_protected")


if __name__ == "__main__":
    unittest.main()
