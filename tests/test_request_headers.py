import unittest

from request_headers import media_request_headers


class RequestHeaderTests(unittest.TestCase):
    def test_browser_media_headers_are_preserved_exactly(self):
        context = {
            "referer": "https://page.test/watch?episode=4",
            "origin": "https://page.test",
            "user_agent": "Test Browser/1.0",
            "accept": "*/*",
            "accept_language": "en-US,en;q=0.9",
            "Authorization": "Bearer forbidden",
            "Cookie": "session=forbidden",
        }
        headers = media_request_headers(context)
        self.assertEqual(headers["Referer"], context["referer"])
        self.assertEqual(headers["Origin"], context["origin"])
        self.assertEqual(headers["User-Agent"], context["user_agent"])
        self.assertEqual(headers["Accept"], context["accept"])
        self.assertEqual(headers["Accept-Language"], context["accept_language"])
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Cookie", headers)

    def test_header_newlines_are_not_forwarded(self):
        headers = media_request_headers({"accept": "*/*\r\nCookie: injected"})
        self.assertNotIn("Accept", headers)
        self.assertNotIn("Cookie", headers)


if __name__ == "__main__":
    unittest.main()
