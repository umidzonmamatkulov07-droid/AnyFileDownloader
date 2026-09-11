import unittest

from download_errors import DownloadFailure
from retry_policy import RetryPolicy, is_transient_transport_error, run_with_retry


class RetryPolicyTests(unittest.TestCase):
    def test_transient_hls_operation_retries_serially(self):
        attempts = []
        retries = []

        def operation():
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                raise ConnectionResetError("connection reset")
            return "complete"

        result = run_with_retry(
            operation,
            RetryPolicy(max_attempts=3, delays=(0, 0)),
            lambda attempt, maximum, _error, _delay: retries.append((attempt, maximum)),
            sleep=lambda _delay: None,
        )
        self.assertEqual(result, "complete")
        self.assertEqual(attempts, [1, 2, 3])
        self.assertEqual(retries, [(2, 3), (3, 3)])

    def test_retry_count_is_bounded(self):
        attempts = []

        def operation():
            attempts.append(1)
            raise TimeoutError("timed out")

        with self.assertRaises(TimeoutError):
            run_with_retry(operation, RetryPolicy(max_attempts=3, delays=(0, 0)), sleep=lambda _delay: None)
        self.assertEqual(len(attempts), 3)

    def test_permanent_failures_are_not_retried(self):
        attempts = []

        def operation():
            attempts.append(1)
            raise DownloadFailure("http_forbidden", "The media server refused the request (HTTP 403).")

        with self.assertRaises(DownloadFailure):
            run_with_retry(operation, RetryPolicy(max_attempts=3, delays=(0, 0)), sleep=lambda _delay: None)
        self.assertEqual(len(attempts), 1)
        self.assertFalse(is_transient_transport_error(DownloadFailure("unsupported_media", "DRM protected")))

    def test_codec_and_container_failures_are_not_retried(self):
        for diagnostic in (
            "Unable to create decoder; dimensions not set",
            "Could not write header for output file",
        ):
            with self.subTest(diagnostic=diagnostic):
                attempts = []

                def operation():
                    attempts.append(1)
                    raise DownloadFailure("ffmpeg_failure", "FFmpeg could not save the validated HLS playlist.", diagnostic)

                with self.assertRaises(DownloadFailure):
                    run_with_retry(operation, RetryPolicy(max_attempts=3, delays=(0, 0)), sleep=lambda _delay: None)
                self.assertEqual(len(attempts), 1)


if __name__ == "__main__":
    unittest.main()
