import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from diagnostics import redact_url
from direct_download import download_direct_file
from download_errors import DownloadFailure
from retry_policy import RetryPolicy, run_with_retry


PDF_BODY = b"%PDF-1.7\ncontrolled fixture\n%%EOF\n"


class _DownloadHandler(BaseHTTPRequestHandler):
    retry_requests = 0
    requested_targets = []

    def log_message(self, _format, *_args):
        pass

    def _send_file(self, body, mime_type, disposition="", include_length=True):
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        if disposition:
            self.send_header("Content-Disposition", disposition)
        if include_length:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.__class__.requested_targets.append(self.path)
        path = urlsplit(self.path).path
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/final/report")
            self.end_headers()
        elif path == "/final/report":
            self._send_file(PDF_BODY, "application/pdf", 'attachment; filename="redirected.pdf"')
        elif path == "/normal.pdf":
            self._send_file(PDF_BODY, "application/pdf")
        elif path == "/report.docx":
            self._send_file(b"controlled docx fixture", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        elif path == "/budget.xlsx":
            self._send_file(b"controlled xlsx fixture", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        elif path == "/archive.zip":
            self._send_file(b"controlled zip fixture", "application/zip")
        elif path == "/movie.mp4":
            self._send_file(b"controlled mp4 fixture", "video/mp4")
        elif path == "/no-extension":
            self._send_file(
                PDF_BODY,
                "application/octet-stream",
                "attachment; filename*=UTF-8''%D0%9E%D1%82%D1%87%D1%91%D1%82%202026.pdf",
            )
        elif path == "/no-length":
            self._send_file(b"plain text without length", "text/plain", include_length=False)
        elif path == "/misleading.exe":
            self._send_file(PDF_BODY, "application/pdf")
        elif path == "/fake.pdf":
            self._send_file(b"<html>not a document</html>", "text/html")
        elif path == "/traversal":
            self._send_file(PDF_BODY, "application/pdf", 'attachment; filename="../../outside.pdf"')
        elif path == "/signed":
            self._send_file(PDF_BODY, "application/pdf", 'attachment; filename="signed.pdf"')
        elif path == "/incomplete":
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="broken.zip"')
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"short")
            self.close_connection = True
        elif path == "/retry":
            self.__class__.retry_requests += 1
            if self.__class__.retry_requests < 3:
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="retry.zip"')
                self.send_header("Content-Length", "20")
                self.end_headers()
                self.wfile.write(b"short")
                self.close_connection = True
            else:
                self._send_file(b"complete zip fixture", "application/zip", 'attachment; filename="retry.zip"')
        else:
            self.send_response(404)
            self.end_headers()


class DirectDownloadHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _DownloadHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        _DownloadHandler.requested_targets = []
        _DownloadHandler.retry_requests = 0

    def download(self, path, directory, context=None):
        return download_direct_file(f"{self.base_url}{path}", directory, context)

    def test_pdf_with_normal_url_and_content_length(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = self.download("/normal.pdf", directory)
            self.assertEqual(completed.name, "normal.pdf")
            self.assertEqual(completed.read_bytes(), PDF_BODY)

    def test_docx_xlsx_zip_and_direct_mp4_use_direct_transfer(self):
        cases = {
            "/report.docx": b"controlled docx fixture",
            "/budget.xlsx": b"controlled xlsx fixture",
            "/archive.zip": b"controlled zip fixture",
            "/movie.mp4": b"controlled mp4 fixture",
        }
        with tempfile.TemporaryDirectory() as directory:
            for path, expected in cases.items():
                with self.subTest(path=path):
                    completed = self.download(path, directory)
                    self.assertEqual(completed.read_bytes(), expected)

    def test_no_extension_uses_unicode_content_disposition(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = self.download("/no-extension", directory)
            self.assertEqual(completed.name, "Отчёт 2026.pdf")

    def test_duplicate_filename_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.download("/normal.pdf", directory)
            second = self.download("/normal.pdf", directory)
            self.assertEqual((first.name, second.name), ("normal.pdf", "normal (1).pdf"))

    def test_redirect_uses_final_response_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = self.download("/redirect", directory)
            self.assertEqual(completed.name, "redirected.pdf")
            self.assertEqual(_DownloadHandler.requested_targets, ["/redirect", "/final/report"])

    def test_missing_content_length_completes_normally(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = self.download("/no-length", directory, {"link_text": "release notes"})
            self.assertEqual(completed.name, "no-length.txt")
            self.assertEqual(completed.read_bytes(), b"plain text without length")

    def test_incomplete_download_is_rejected_and_part_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises((DownloadFailure, OSError)):
                self.download("/incomplete", directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_incomplete_download_retries_then_promotes_once(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = run_with_retry(
                lambda: self.download("/retry", directory),
                RetryPolicy(max_attempts=3, delays=(0, 0)),
            )
            self.assertEqual(_DownloadHandler.retry_requests, 3)
            self.assertEqual(completed.read_bytes(), b"complete zip fixture")
            self.assertEqual([path.name for path in Path(directory).iterdir()], ["retry.zip"])

    def test_signed_query_is_preserved_but_redactable(self):
        signed_url = f"{self.base_url}/signed?token=secret&expires=123"
        with tempfile.TemporaryDirectory() as directory:
            completed = download_direct_file(signed_url, directory)
            self.assertEqual(completed.name, "signed.pdf")
        self.assertEqual(_DownloadHandler.requested_targets, ["/signed?token=secret&expires=123"])
        self.assertNotIn("secret", redact_url(signed_url))

    def test_mime_corrects_misleading_url_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = self.download("/misleading.exe", directory)
            self.assertEqual(completed.name, "misleading.pdf")

    def test_html_disguised_as_pdf_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(DownloadFailure, "not a recognized direct file"):
                self.download("/fake.pdf", directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_traversal_filename_stays_inside_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = self.download("/traversal", directory)
            self.assertEqual(completed.name, "outside.pdf")
            self.assertEqual(completed.parent, Path(directory))


if __name__ == "__main__":
    unittest.main()
