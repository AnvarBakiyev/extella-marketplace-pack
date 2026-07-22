import argparse
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

from runtime.extella_runtime.platforms import detect_platform
from tools.external_matrix import (
    MatrixError,
    SUPPORTED_IDS,
    _install_supported_plugins,
    _sha256_bytes_for_evidence,
    run,
)


class ExternalMatrixTests(unittest.TestCase):
    def _candidate(self, root):
        candidate = root / "extella-client-2.0.0-rc.1.zip"
        sources = {
            "marketplace": "1" * 40,
            "toolbar": "2" * 40,
            "wizard": "3" * 40,
        }
        bundle_manifest = {
            "schemaVersion": 1,
            "releaseVersion": "2.0.0-rc.1",
            "sourceRepositories": [
                {"id": key, "revision": value} for key, value in sources.items()
            ],
            "files": [{"path": "payload/example", "bytes": 1, "sha256": "a" * 64}],
        }
        with zipfile.ZipFile(candidate, "w") as archive:
            archive.writestr("bundle-manifest.json", json.dumps(bundle_manifest))
        release = {
            "version": "2.0.0-rc.1",
            "distribution": {
                "status": "candidate",
                "fileName": candidate.name,
                "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                "bytes": candidate.stat().st_size,
                "fileCount": 1,
            },
            "sourceRepositories": [
                {"id": key, "revision": value} for key, value in sources.items()
            ],
        }
        manifest = root / "release-manifest.json"
        manifest.write_text(json.dumps(release), encoding="utf-8")
        return candidate, manifest

    def test_clean_baseline_is_bound_to_exact_candidate_and_platform(self):
        mac = detect_platform(system="Darwin", architecture="arm64", release="15")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, manifest = self._candidate(root)
            result = root / "evidence.json"
            args = argparse.Namespace(
                phase="baseline",
                expected_platform="macos-arm64",
                candidate=candidate,
                release_manifest=manifest,
                result=result,
                desktop_evidence=None,
            )
            paths = SimpleNamespace(state_root=root / "empty-state")
            with (
                patch("tools.external_matrix.detect_platform", return_value=mac),
                patch("tools.external_matrix.client_paths", return_value=paths),
                patch("tools.external_matrix._boot_marker", return_value="b" * 64),
                patch("tools.external_matrix._port_open", return_value=False),
            ):
                event = run(args)
            evidence = json.loads(result.read_text(encoding="utf-8"))
            candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
        self.assertEqual(event["status"], "passed")
        self.assertEqual(evidence["platform"], "macos-arm64")
        self.assertEqual(evidence["candidate"]["sha256"], candidate_sha256)
        self.assertEqual(evidence["evidenceSha256"], _sha256_bytes_for_evidence(evidence))

    def test_candidate_hash_mismatch_fails_before_phase_recording(self):
        mac = detect_platform(system="Darwin", architecture="arm64", release="15")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, manifest = self._candidate(root)
            release = json.loads(manifest.read_text(encoding="utf-8"))
            release["distribution"]["sha256"] = "0" * 64
            manifest.write_text(json.dumps(release), encoding="utf-8")
            args = argparse.Namespace(
                phase="baseline",
                expected_platform="macos-arm64",
                candidate=candidate,
                release_manifest=manifest,
                result=root / "evidence.json",
                desktop_evidence=None,
            )
            with patch("tools.external_matrix.detect_platform", return_value=mac):
                with self.assertRaises(MatrixError):
                    run(args)

    def test_installs_exact_supported_inventory_through_protected_lifecycle(self):
        ids = sorted(SUPPORTED_IDS)
        before = {"status": "ok", "plugins": [{"id": plugin_id} for plugin_id in ids]}
        after = {
            "status": "ok",
            "plugins": [
                {"id": plugin_id, "installed": True, "needsRepair": False}
                for plugin_id in ids
            ],
        }
        replies = [
            {"status": "ok", "controlToken": "x" * 32},
            before,
            *(
                {
                    "status": "installed",
                    "pluginId": plugin_id,
                    "service": {"status": "running", "pid": index + 100},
                    "ui": {"status": "ready"},
                    "account": {"status": "installed"},
                }
                for index, plugin_id in enumerate(ids)
            ),
            after,
        ]
        with patch("tools.external_matrix._http_json", side_effect=replies) as request:
            result = _install_supported_plugins()
        self.assertEqual(result, {"plugins": 3, "healthyServices": 3, "readyUis": 3})
        install_calls = [
            call
            for call in request.call_args_list
            if call.args[0].endswith("/install")
        ]
        self.assertEqual(len(install_calls), 3)
        self.assertTrue(all(call.kwargs["token"] == "x" * 32 for call in install_calls))


if __name__ == "__main__":
    unittest.main()
