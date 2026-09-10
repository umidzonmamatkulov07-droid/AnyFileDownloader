import tempfile
import unittest
from pathlib import Path

from native_manifest import HOST_NAME, build_host_manifest, write_host_manifest, write_launcher


EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"


class NativeManifestTests(unittest.TestCase):
    def test_builds_expected_allowed_origin(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            host = Path(temporary_directory) / "native_host.py"
            host.touch()
            manifest = build_host_manifest(EXTENSION_ID, host)

            self.assertEqual(manifest["name"], HOST_NAME)
            self.assertEqual(manifest["allowed_origins"], [f"chrome-extension://{EXTENSION_ID}/"])
            self.assertEqual(manifest["path"], str(host.resolve()))

    def test_rejects_invalid_extension_id(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            host = Path(temporary_directory) / "native_host.py"
            host.touch()
            with self.assertRaisesRegex(ValueError, "32 lowercase"):
                build_host_manifest("not-an-extension-id", host)

    def test_writes_valid_manifest(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            host = directory / "native_host.py"
            output = directory / "host.json"
            host.touch()
            write_host_manifest(EXTENSION_ID, host, output)
            self.assertIn(HOST_NAME, output.read_text(encoding="utf-8"))

    def test_writes_executable_launcher_with_quoted_paths(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            python_path = directory / "python executable"
            host = directory / "native host.py"
            launcher = directory / "launcher.sh"
            python_path.touch()
            host.touch()

            write_launcher(python_path, host, launcher)

            launcher_text = launcher.read_text(encoding="utf-8")
            self.assertIn("'", launcher_text)
            self.assertTrue(launcher.stat().st_mode & 0o100)


if __name__ == "__main__":
    unittest.main()
