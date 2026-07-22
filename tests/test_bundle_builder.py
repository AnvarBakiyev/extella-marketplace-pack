import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "build_client_bundle.py"
SPEC = importlib.util.spec_from_file_location("build_client_bundle", MODULE_PATH)
assert SPEC and SPEC.loader
bundle_builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bundle_builder
SPEC.loader.exec_module(bundle_builder)


class ExpertClassificationTests(unittest.TestCase):
    def roots(self, *, inventory: dict | None = None) -> tuple[Path, Path, tempfile.TemporaryDirectory]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        marketplace = root / "marketplace"
        wizard = root / "wizard"
        (marketplace / "experts").mkdir(parents=True)
        (marketplace / "release/plugins").mkdir(parents=True)
        (wizard / "experts").mkdir(parents=True)
        (marketplace / "experts/bundled_one.py").write_text("def bundled_one(): return 'ok'\n")
        (wizard / "experts/unverified_one.py").write_text("def unverified_one(): return 'ok'\n")
        (marketplace / "release/plugins/core.json").write_text(
            json.dumps(
                {
                    "classification": "bundled",
                    "experts": {"required": ["bundled_one"], "smoke": []},
                }
            )
        )
        classification = inventory or {
            "schemaVersion": 1,
            "bundled": ["bundled_one"],
            "supportedOnDemand": [],
            "thirdPartyUnverified": ["unverified_one"],
        }
        (marketplace / "release/expert-classification.json").write_text(
            json.dumps(classification)
        )
        return marketplace, wizard, temporary

    def test_exact_three_way_inventory_passes(self):
        marketplace, wizard, temporary = self.roots()
        self.addCleanup(temporary.cleanup)
        self.assertEqual(
            {
                "bundled": 1,
                "supportedOnDemand": 0,
                "thirdPartyUnverified": 1,
            },
            bundle_builder._validate_expert_classification(marketplace, wizard),
        )

    def test_unclassified_source_fails_closed(self):
        marketplace, wizard, temporary = self.roots(
            inventory={
                "schemaVersion": 1,
                "bundled": ["bundled_one"],
                "supportedOnDemand": [],
                "thirdPartyUnverified": [],
            }
        )
        self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(SystemExit, "not exact"):
            bundle_builder._validate_expert_classification(marketplace, wizard)

    def test_manifest_and_bundled_inventory_must_match(self):
        marketplace, wizard, temporary = self.roots(
            inventory={
                "schemaVersion": 1,
                "bundled": [],
                "supportedOnDemand": [],
                "thirdPartyUnverified": ["bundled_one", "unverified_one"],
            }
        )
        self.addCleanup(temporary.cleanup)
        with self.assertRaisesRegex(SystemExit, "bundled expert classification"):
            bundle_builder._validate_expert_classification(marketplace, wizard)


class DeclaredRevisionTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> str:
        completed = subprocess.run(
            ("git", "-C", str(root), *args),
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    def commit(self, root: Path, message: str) -> str:
        self.git(root, "add", "-A")
        self.git(
            root,
            "-c", "user.name=Extella Test",
            "-c", "user.email=test@example.invalid",
            "commit", "-m", message,
        )
        return self.git(root, "rev-parse", "HEAD")

    def test_marketplace_allows_only_release_metadata_after_declared_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.git(root, "init", "-q")
            (root / "code.py").write_text("v1\n", encoding="utf-8")
            source = self.commit(root, "source")
            (root / "release").mkdir()
            (root / "release/release-manifest.json").write_text("{}\n", encoding="utf-8")
            packaging = self.commit(root, "release metadata")
            bundle_builder._require_declared_checkout(root, "marketplace", source, packaging)

            (root / "code.py").write_text("v2\n", encoding="utf-8")
            changed = self.commit(root, "late code change")
            with self.assertRaisesRegex(SystemExit, "outside release metadata"):
                bundle_builder._require_declared_checkout(root, "marketplace", source, changed)

    def test_component_checkout_must_equal_declared_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(SystemExit, "differs from declared"):
                bundle_builder._require_declared_checkout(root, "wizard", "1" * 40, "2" * 40)

if __name__ == "__main__":
    unittest.main()
