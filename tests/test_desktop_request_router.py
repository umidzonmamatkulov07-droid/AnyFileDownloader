import threading
import unittest

from downloader import DesktopRequestRouter


class _FakeApp:
    def __init__(self):
        self.requests = []
        self.activated = 0

    def after(self, _delay, callback):
        callback()

    def activate_window(self):
        self.activated += 1

    def enqueue_request_threadsafe(self, request):
        self.requests.append(dict(request))
        return {"ok": True, "status": "queued"}

    def ipc_status(self):
        return {"ok": True, "pid": 99, "jobs": []}


class DesktopRequestRouterTests(unittest.TestCase):
    def test_startup_requests_are_retained_until_app_attaches(self):
        router = DesktopRequestRouter()
        for index in range(5):
            response = router.handle({"action": "download", "url": f"https://example.test/{index}.pdf"})
            self.assertTrue(response["ok"])
        app = _FakeApp()
        router.attach(app)
        self.assertEqual(len(app.requests), 5)

    def test_concurrent_requests_reach_same_app(self):
        router = DesktopRequestRouter()
        app = _FakeApp()
        router.attach(app)
        threads = [
            threading.Thread(
                target=router.handle,
                args=({"action": "download", "url": f"https://example.test/{index}.pdf"},),
            )
            for index in range(5)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(app.requests), 5)

    def test_manual_second_launch_activates_existing_window(self):
        router = DesktopRequestRouter()
        app = _FakeApp()
        router.attach(app)
        self.assertTrue(router.handle({"action": "activate"})["ok"])
        self.assertEqual(app.activated, 1)

    def test_status_reports_same_attached_process(self):
        router = DesktopRequestRouter()
        app = _FakeApp()
        router.attach(app)
        self.assertEqual(router.handle({"action": "status"})["pid"], 99)

    def test_startup_status_contains_no_request_data(self):
        router = DesktopRequestRouter()
        router.handle({
            "action": "download",
            "url": "https://example.test/report.pdf?token=private",
        })
        status = router.handle({"action": "status"})
        self.assertEqual(status, {"ok": True, "status": "starting", "jobs": []})
        self.assertNotIn("private", repr(status))


if __name__ == "__main__":
    unittest.main()
