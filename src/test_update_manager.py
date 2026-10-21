import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from update_manager import UpdateError, fetch_manifest, update_files


class UpdateManagerTests(unittest.TestCase):
    def test_rejects_http_manifest_without_network_access(self):
        with patch("update_manager._download") as download:
            with self.assertRaises(UpdateError):
                fetch_manifest("http://example.test/api/manifest")
            download.assert_not_called()

    def test_rejects_cross_host_download_url(self):
        manifest = {
            "files": [{
                "path": "system/test.dat",
                "size": 4,
                "sha256": hashlib.sha256(b"safe").hexdigest(),
                "download": "https://evil.example/test.dat",
            }]
        }
        with patch(
            "update_manager._download",
            return_value=json.dumps(manifest).encode(),
        ) as download:
            with self.assertRaises(UpdateError):
                fetch_manifest("https://example.test/api/manifest")
            download.assert_called_once()

    def test_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = b"safe"
            manifest = {
                "files": [{
                    "path": "../outside.txt",
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "download": "/files/outside.txt",
                }]
            }
            with patch("update_manager._download", return_value=json.dumps(manifest).encode()):
                with self.assertRaises(UpdateError):
                    fetch_manifest("https://example.test/api/manifest")

    def test_rejects_hash_mismatch_without_writing_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "client"
            root.mkdir()
            body = b"new content"
            manifest = {
                "files": [{
                    "path": "system/l2.ini",
                    "size": len(body),
                    "sha256": "0" * 64,
                    "download": "/files/l2.ini",
                }]
            }
            with patch("update_manager._download", side_effect=[
                json.dumps(manifest).encode(), body
            ]):
                with self.assertRaises(UpdateError):
                    update_files("https://example.test/api/manifest", root)
            self.assertFalse((root / "system/l2.ini").exists())

    def test_installs_verified_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "client"
            root.mkdir()
            body = b"verified update"
            manifest = {
                "files": [{
                    "path": "system/test.dat",
                    "size": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "download": "/api/v1/files/system/test.dat",
                }]
            }
            with patch("update_manager._download", side_effect=[
                json.dumps(manifest).encode(), body
            ]):
                changed = update_files("https://example.test/api/v1/manifest", root)
            self.assertEqual((root / "system/test.dat").read_bytes(), body)
            self.assertEqual(changed, [root / "system/test.dat"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
