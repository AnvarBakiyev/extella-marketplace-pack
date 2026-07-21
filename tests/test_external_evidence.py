import json
import tempfile
import unittest
from pathlib import Path

from tools.import_external_evidence import (
    CLEAN_PHASES,
    UPGRADE_PHASES,
    EvidenceImportError,
    _digest_payload,
    import_evidence,
)


class ExternalEvidenceImportTests(unittest.TestCase):
    def _contracts(self, root):
        candidate = {
            "fileName": "extella-client-2.0.0-rc.1.zip",
            "sha256": "a" * 64,
            "bytes": 123,
            "fileCount": 10,
            "releaseVersion": "2.0.0-rc.1",
            "sourceRepositories": {"marketplace": "1" * 40},
        }
        release = {
            "version": candidate["releaseVersion"],
            "distribution": {
                "status": "candidate",
                "fileName": candidate["fileName"],
                "sha256": candidate["sha256"],
                "bytes": candidate["bytes"],
                "fileCount": candidate["fileCount"],
            },
            "sourceRepositories": [
                {"id": "marketplace", "revision": "1" * 40}
            ],
            "verification": {
                "matrix": {
                    "macos-x86_64": "pending",
                    "macos-arm64": "pending",
                    "windows11-x86_64": "pending",
                }
            },
        }
        scenarios = {
            "native_bootstrap": "blocked_external",
            "clean_os_install": "blocked_external",
            "clean_account": "blocked_external",
            "service_control": "blocked_external",
            "reinstall_repair_uninstall": "blocked_external",
            "cold_restart": "blocked_external",
            "upgrade_previous": "blocked_external",
            "ui_live_extella": "blocked_external",
        }
        evidence = {
            "platformMatrix": {
                "macos-x86_64": dict(scenarios),
                "macos-arm64": dict(scenarios),
                "windows11-x86_64": dict(scenarios),
            },
            "externalRuns": {},
        }
        release_path = root / "release.json"
        evidence_path = root / "evidence.json"
        release_path.write_text(json.dumps(release), encoding="utf-8")
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        return candidate, release_path, evidence_path

    def _run(self, path, candidate, phases):
        events = []
        for phase in sorted(phases):
            event = {
                "phase": phase,
                "status": "passed",
                "bootId": "b" * 64 if phase == "restarted" else "a" * 64,
                "checks": {},
            }
            if phase == "live-ui":
                event["checks"] = {
                    "desktopEvidence": {"sha256": "c" * 64, "bytes": 20_000}
                }
            events.append(event)
        value = {
            "schemaVersion": 1,
            "sessionId": path.stem,
            "platform": "macos-arm64",
            "candidate": candidate,
            "phases": events,
        }
        value["evidenceSha256"] = _digest_payload(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_accepts_only_complete_clean_and_upgrade_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, release, evidence = self._contracts(root)
            clean = root / "clean.json"
            upgrade = root / "upgrade.json"
            self._run(clean, candidate, CLEAN_PHASES)
            self._run(upgrade, candidate, UPGRADE_PHASES)
            report = import_evidence(
                platform="macos-arm64",
                clean_result=clean,
                upgrade_result=upgrade,
                release_manifest=release,
                verification_evidence=evidence,
            )
            accepted = json.loads(evidence.read_text(encoding="utf-8"))
            updated_release = json.loads(release.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "accepted")
        self.assertTrue(
            all(value == "passed" for value in accepted["platformMatrix"]["macos-arm64"].values())
        )
        self.assertEqual(updated_release["verification"]["matrix"]["macos-arm64"], "passed")

    def test_rejects_tampered_external_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, release, evidence = self._contracts(root)
            clean = root / "clean.json"
            upgrade = root / "upgrade.json"
            self._run(clean, candidate, CLEAN_PHASES)
            self._run(upgrade, candidate, UPGRADE_PHASES)
            value = json.loads(clean.read_text(encoding="utf-8"))
            value["phases"][0]["status"] = "failed"
            clean.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(EvidenceImportError):
                import_evidence(
                    platform="macos-arm64",
                    clean_result=clean,
                    upgrade_result=upgrade,
                    release_manifest=release,
                    verification_evidence=evidence,
                )


if __name__ == "__main__":
    unittest.main()
