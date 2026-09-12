import threading
import unittest

from download_queue import SequentialDownloadQueue


class DownloadQueueTests(unittest.TestCase):
    def test_request_transitions_queued_active_completed(self):
        transitions = []
        queue = SequentialDownloadQueue(lambda job: f"done:{job.request['url']}", lambda job: transitions.append(job.status))
        queue.start()
        try:
            job = queue.enqueue({"url": "https://example.test/file.pdf"})
            self.assertTrue(queue.wait_idle())
            final = next(item for item in queue.jobs() if item.id == job.id)
            self.assertEqual(final.status, "completed")
            self.assertEqual(final.progress, 100.0)
            self.assertEqual(transitions, ["queued", "active", "completed"])
        finally:
            queue.stop()

    def test_failure_transition_retains_job(self):
        def fail(_job):
            raise RuntimeError("controlled failure")

        queue = SequentialDownloadQueue(fail)
        queue.start()
        try:
            job = queue.enqueue({"url": "https://example.test/fail"})
            self.assertTrue(queue.wait_idle())
            final = next(item for item in queue.jobs() if item.id == job.id)
            self.assertEqual(final.status, "failed")
            self.assertEqual(final.error, "controlled failure")
        finally:
            queue.stop()

    def test_multiple_concurrent_enqueues_are_retained_and_sequential(self):
        active = 0
        maximum_active = 0
        lock = threading.Lock()

        def worker(_job):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            with lock:
                active -= 1

        queue = SequentialDownloadQueue(worker)
        queue.start()
        try:
            threads = [threading.Thread(target=queue.enqueue, args=({"url": f"https://example.test/{index}"},)) for index in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertTrue(queue.wait_idle())
            self.assertEqual(len(queue.jobs()), 5)
            self.assertTrue(all(job.status == "completed" for job in queue.jobs()))
            self.assertEqual(maximum_active, 1)
        finally:
            queue.stop()

    def test_queued_request_can_be_cancelled(self):
        gate = threading.Event()
        queue = SequentialDownloadQueue(lambda _job: gate.wait(1.0))
        queue.start()
        try:
            queue.enqueue({"url": "https://example.test/active"})
            queued = queue.enqueue({"url": "https://example.test/cancel"})
            self.assertTrue(queue.cancel(queued.id))
            gate.set()
            self.assertTrue(queue.wait_idle())
            cancelled = next(job for job in queue.jobs() if job.id == queued.id)
            self.assertEqual(cancelled.status, "cancelled")
        finally:
            gate.set()
            queue.stop()


if __name__ == "__main__":
    unittest.main()
