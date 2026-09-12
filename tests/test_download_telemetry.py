import unittest
from unittest.mock import Mock

from download_telemetry import DownloadTelemetry, hud_degrees_per_tick
from downloader import AnyFileDownloaderApp


class DownloadTelemetryTests(unittest.TestCase):
    def test_real_progress_elapsed_and_eta(self):
        telemetry = DownloadTelemetry(smoothing_seconds=0.1)
        telemetry.start(1_000, now=10.0)
        snapshot = telemetry.update(500, 1_000, speed_bps=250, now=12.0)
        self.assertEqual(snapshot.progress_percent, 50.0)
        self.assertEqual(snapshot.elapsed_seconds, 2.0)
        self.assertAlmostEqual(snapshot.speed_bps, 250, delta=1)
        self.assertAlmostEqual(snapshot.eta_seconds, 2.0, delta=0.1)

    def test_stall_slows_and_recovery_speeds_up(self):
        telemetry = DownloadTelemetry(smoothing_seconds=0.5)
        telemetry.start(now=0.0)
        fast = telemetry.update(4_000_000, speed_bps=4_000_000, now=1.0)
        stalled = telemetry.mark_stalled(now=3.0)
        recovered = telemetry.update(8_000_000, speed_bps=8_000_000, now=4.0)
        self.assertLess(stalled.speed_bps, fast.speed_bps)
        self.assertGreater(recovered.speed_bps, stalled.speed_bps)

    def test_hud_speed_mapping_is_monotonic_and_clamped(self):
        idle = hud_degrees_per_tick(0, False)
        stalled = hud_degrees_per_tick(0, True)
        low = hud_degrees_per_tick(128 * 1024, True)
        medium = hud_degrees_per_tick(2 * 1024 * 1024, True)
        high = hud_degrees_per_tick(20 * 1024 * 1024, True)
        extreme = hud_degrees_per_tick(1024 * 1024 * 1024, True)
        self.assertLess(idle, stalled)
        self.assertLess(stalled, low)
        self.assertLess(low, medium)
        self.assertLess(medium, high)
        self.assertLessEqual(extreme, 14.0)

    def test_every_byte_update_is_measured_while_queue_ui_is_coalesced(self):
        app = type("TelemetryUI", (), {})()
        app.telemetry = DownloadTelemetry(smoothing_seconds=0.1)
        app.current_speed_mbps = 0.0
        app.current_progress_pct = 0
        app.current_job_id = "job"
        app._last_queue_progress_at = 0.0
        app.download_queue = Mock()

        for downloaded in range(64 * 1024, 1024 * 1024 + 1, 64 * 1024):
            AnyFileDownloaderApp._accept_telemetry(app, downloaded, 1024 * 1024)

        self.assertEqual(app.telemetry.downloaded_bytes, 1024 * 1024)
        self.assertLess(app.download_queue.update_progress.call_count, 16)
        self.assertGreaterEqual(app.download_queue.update_progress.call_count, 1)


if __name__ == "__main__":
    unittest.main()
