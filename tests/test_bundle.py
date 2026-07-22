import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from installer.bundle import BundleVerificationError, verify_bundle
from tools.build_client_bundle import _scan


class BundleVerificationTests(unittest.TestCase):
    def _bundle(self, root: Path):
        payload = root / "payload" / "file.txt"
        payload.parent.mkdir(parents=True)
        payload.write_text("safe", encoding="utf-8")
        manifest = {
            "schemaVersion": 1,
            "releaseVersion": "2.0.0-rc.1",
            "supportedPlatforms": ["macos-x86_64", "macos-arm64", "windows11-x86_64"],
            "sourceRepositories": [
                {"id": "marketplace", "revision": "1" * 40},
                {"id": "toolbar", "revision": "2" * 40},
                {"id": "wizard", "revision": "3" * 40},
            ],
            "packagingRepositoryRevision": "4" * 40,
            "files": [
                {
                    "path": "payload/file.txt",
                    "bytes": 4,
                    "sha256": hashlib.sha256(b"safe").hexdigest(),
                }
            ],
        }
        (root / "bundle-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_exact_bundle_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bundle(root)
            result = verify_bundle(root)
            self.assertEqual(result.files, 1)
            self.assertEqual(result.bytes, 4)
            self.assertEqual(result.packaging_repository_revision, "4" * 40)

    def test_packaging_revision_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bundle(root)
            manifest_path = root / "bundle-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest.pop("packagingRepositoryRevision")
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(BundleVerificationError):
                verify_bundle(root)

    def test_modified_or_extra_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bundle(root)
            (root / "payload" / "file.txt").write_text("changed", encoding="utf-8")
            with self.assertRaises(BundleVerificationError):
                verify_bundle(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bundle(root)
            (root / "extra.txt").write_text("extra", encoding="utf-8")
            with self.assertRaises(BundleVerificationError):
                verify_bundle(root)

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bundle(root)
            manifest_path = root / "bundle-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["files"][0]["path"] = "../outside"
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(BundleVerificationError):
                verify_bundle(root)

    def test_source_scan_rejects_personal_home_but_allows_documented_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "example.txt"
            source.write_text(
                "Откройте /Users/имя/Downloads, marker /Users/, API /users/{id}, placeholder agent_XXXXXXXX",
                encoding="utf-8",
            )
            _scan(source, "example.txt")
            source.write_text("/Users/anvarbakiyev/Downloads/private", encoding="utf-8")
            with self.assertRaises(SystemExit):
                _scan(source, "example.txt")
            source.write_text("agent_AbCd0123456789", encoding="utf-8")
            with self.assertRaises(SystemExit):
                _scan(source, "example.txt")


if __name__ == "__main__":
    unittest.main()
