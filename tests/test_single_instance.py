import concurrent.futures
import os
import tempfile
import unittest
from pathlib import Path

from single_instance import InstanceLock, SingleInstanceService, instance_paths, send_ipc_message


class SingleInstanceTests(unittest.TestCase):
    def test_stale_lock_text_does_not_block_recovery(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = instance_paths(Path(temporary_directory))
            paths.directory.mkdir(parents=True)
            paths.lock_path.write_text("999999", encoding="ascii")
            lock = InstanceLock(paths.lock_path)
            self.assertTrue(lock.acquire())
            lock.release()

    def test_live_lock_allows_only_one_owner(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = instance_paths(Path(temporary_directory))
            first = InstanceLock(paths.lock_path)
            second = InstanceLock(paths.lock_path)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_stale_socket_is_replaced_and_user_only(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = instance_paths(Path(temporary_directory))
            paths.directory.mkdir(parents=True)
            paths.socket_path.write_text("stale", encoding="ascii")
            service = SingleInstanceService(lambda message: {"ok": True, "value": message["value"]}, Path(temporary_directory))
            try:
                self.assertTrue(service.start())
                self.assertEqual(send_ipc_message({"value": 7}, paths.socket_path)["value"], 7)
                self.assertEqual(paths.socket_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(paths.directory.stat().st_mode & 0o777, 0o700)
            finally:
                service.stop()

    def test_five_concurrent_requests_reach_one_server(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = instance_paths(Path(temporary_directory))
            received = []

            def handler(message):
                received.append(message["number"])
                return {"ok": True}

            service = SingleInstanceService(handler, Path(temporary_directory))
            try:
                self.assertTrue(service.start())
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    responses = list(executor.map(
                        lambda number: send_ipc_message({"number": number}, paths.socket_path),
                        range(5),
                    ))
                self.assertTrue(all(response["ok"] for response in responses))
                self.assertCountEqual(received, range(5))
            finally:
                service.stop()

    def test_close_and_relaunch_reuses_paths(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            first = SingleInstanceService(lambda _message: {"ok": True}, Path(temporary_directory))
            self.assertTrue(first.start())
            socket_path = first.paths.socket_path
            first.stop()
            self.assertFalse(socket_path.exists())

            second = SingleInstanceService(lambda _message: {"ok": True}, Path(temporary_directory))
            try:
                self.assertTrue(second.start())
                self.assertTrue(send_ipc_message({"action": "activate"}, socket_path)["ok"])
            finally:
                second.stop()


if __name__ == "__main__":
    unittest.main()
