import os
import tempfile
import unittest

from core.key_scanner import KeyScanner


class KeyPathTests(unittest.TestCase):
    def test_latest_key_uses_timestamp_before_sequence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            older_high_sequence = os.path.join(
                temp_dir, "nvidia_api_key_9_20260706_235959.txt"
            )
            newer_low_sequence = os.path.join(
                temp_dir, "nvidia_api_key_1_20260707_000001.txt"
            )
            with open(older_high_sequence, "w", encoding="utf-8") as f:
                f.write("older")
            with open(newer_low_sequence, "w", encoding="utf-8") as f:
                f.write("newer")

            latest = KeyScanner(temp_dir).get_latest_key_file()

        self.assertEqual(latest, newer_low_sequence)

    def test_configured_key_scan_dir_resolves_directory_or_file_target(self):
        from core.key_paths import resolve_key_save_target, resolve_key_scan_dir

        with tempfile.TemporaryDirectory() as temp_dir:
            default_dir = os.path.join(temp_dir, "default-keys")
            configured_dir = os.path.join(temp_dir, "chosen-keys")
            configured_file = os.path.join(temp_dir, "single", "latest-key.txt")

            self.assertEqual(resolve_key_scan_dir("", default_dir), default_dir)
            self.assertEqual(
                resolve_key_scan_dir(configured_dir, default_dir),
                configured_dir,
            )
            self.assertEqual(
                resolve_key_scan_dir(configured_file, default_dir),
                os.path.dirname(configured_file),
            )
            save_target = resolve_key_save_target(configured_dir, default_dir)
            self.assertTrue(save_target.is_directory)
            self.assertEqual(save_target.path, configured_dir)

            file_target = resolve_key_save_target(configured_file, default_dir)
            self.assertFalse(file_target.is_directory)
            self.assertEqual(file_target.path, configured_file)


if __name__ == "__main__":
    unittest.main()
