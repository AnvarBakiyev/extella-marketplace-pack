import importlib.util
import json
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


if __name__ == "__main__":
    unittest.main()
