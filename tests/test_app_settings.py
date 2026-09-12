import json
import tempfile
import unittest
from pathlib import Path

from app_settings import AppSettings, SettingsStore


class SettingsStoreTests(unittest.TestCase):
    def test_settings_survive_save_and_load(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.json"
            store = SettingsStore(path)
            expected = AppSettings(
                download_directory="/tmp/downloads",
                quality="720p MP4",
                playlist=True,
                queue_mode="Sequential",
                sort_order="Oldest to Newest",
                window_geometry="1180x820+25+40",
                window_opacity=0.88,
            )

            store.save(expected)

            self.assertEqual(store.load(), expected)

    def test_corrupted_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.json"
            path.write_text("{not valid json", encoding="utf-8")

            self.assertEqual(SettingsStore(path).load(), AppSettings())

    def test_invalid_values_are_replaced_with_safe_defaults(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.json"
            path.write_text(json.dumps({"quality": "Impossible", "playlist": "yes"}), encoding="utf-8")

            loaded = SettingsStore(path).load()

            self.assertEqual(loaded.quality, "Auto")
            self.assertFalse(loaded.playlist)
            self.assertEqual(loaded.window_geometry, "1180x820")
            self.assertEqual(loaded.window_opacity, 0.88)


if __name__ == "__main__":
    unittest.main()
