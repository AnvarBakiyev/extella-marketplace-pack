import json
import tempfile
import unittest
from pathlib import Path

from runtime.extella_runtime.transaction import (
    InstallationError,
    InstallTransaction,
    uninstall_from_state,
)


class InstallTransactionTests(unittest.TestCase):
    def test_directory_tree_rolls_back_and_uninstalls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            state = root / "state"
            source.mkdir()
            target.mkdir()
            (source / "new.txt").write_text("new", encoding="utf-8")
            (target / "old.txt").write_text("old", encoding="utf-8")

            failed = InstallTransaction(release_version="2.0.0", state_root=state / "failed")
            with self.assertRaises(InstallationError):
                failed.run("tree", lambda: failed.atomic_tree(source, target))
                failed.run("fail", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
            self.assertEqual((target / "old.txt").read_text(encoding="utf-8"), "old")
            self.assertFalse((target / "new.txt").exists())

            installed = InstallTransaction(release_version="2.0.0", state_root=state / "ok")
            installed.run("tree", lambda: installed.atomic_tree(source, target))
            installed.commit()
            self.assertEqual((target / "new.txt").read_text(encoding="utf-8"), "new")
            report = uninstall_from_state(state / "ok" / "install-state.json")
            self.assertEqual(report["status"], "uninstalled")
            self.assertEqual((target / "old.txt").read_text(encoding="utf-8"), "old")

    def test_required_failure_rolls_back_replaced_and_created_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            source = root / "source.txt"
            target = root / "target.txt"
            created = root / "created.txt"
            source.write_text("new", encoding="utf-8")
            target.write_text("old", encoding="utf-8")
            tx = InstallTransaction(release_version="2.0.0", state_root=state)
            tx.run("replace", lambda: tx.atomic_copy(source, target))
            tx.run("create", lambda: tx.atomic_write(b"created", created))
            with self.assertRaises(InstallationError):
                tx.run("fail", lambda: (_ for _ in ()).throw(ValueError("boom")))
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertFalse(created.exists())
            report = json.loads((state / "last-install-report.json").read_text())
            self.assertEqual(report["status"], "rolled_back")
            self.assertEqual(report["steps"][0]["status"], "rolled_back")

    def test_optional_failure_is_reported_but_can_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tx = InstallTransaction(release_version="2.0.0", state_root=root / "state")
            result = tx.run(
                "optional", lambda: (_ for _ in ()).throw(RuntimeError("offline")), required=False
            )
            self.assertFalse(result)
            report = tx.commit()
            self.assertEqual(report["status"], "installed")
            self.assertEqual(report["steps"][0]["status"], "failed")
            self.assertFalse(report["steps"][0]["required"])

    def test_identical_file_is_skipped_without_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            source.write_text("same", encoding="utf-8")
            target.write_text("same", encoding="utf-8")
            tx = InstallTransaction(release_version="2.0.0", state_root=root / "state")
            tx.run("same", lambda: tx.atomic_copy(source, target))
            report = tx.commit()
            self.assertEqual(report["steps"][0]["status"], "skipped")
            self.assertEqual(report["files"], [])

    def test_uninstall_restores_previous_file_and_removes_owned_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            previous = root / "previous"
            owned = root / "owned"
            source.write_text("new", encoding="utf-8")
            previous.write_text("old", encoding="utf-8")
            tx = InstallTransaction(release_version="2.0.0", state_root=root / "state")
            tx.run("replace", lambda: tx.atomic_copy(source, previous))
            tx.run("create", lambda: tx.atomic_copy(source, owned))
            tx.commit()
            result = uninstall_from_state(root / "state" / "install-state.json")
            self.assertEqual(result["status"], "uninstalled")
            self.assertEqual(previous.read_text(encoding="utf-8"), "old")
            self.assertFalse(owned.exists())

    def test_reinstall_chain_uninstalls_back_to_pre_extella_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_v1 = root / "v1.txt"
            source_v2 = root / "v2.txt"
            target = root / "installed" / "owned.txt"
            state_root = root / "state"
            source_v1.write_text("version one", encoding="utf-8")
            source_v2.write_text("version two", encoding="utf-8")

            first = InstallTransaction(release_version="1.0.0", state_root=state_root)
            first.run("install-v1", lambda: first.atomic_copy(source_v1, target))
            first.commit()
            second = InstallTransaction(release_version="2.0.0", state_root=state_root)
            second.run("install-v2", lambda: second.atomic_copy(source_v2, target))
            second.commit()

            state = json.loads((state_root / "install-state.json").read_text())
            self.assertEqual(state["previousState"]["releaseVersion"], "1.0.0")
            report = uninstall_from_state(state_root / "install-state.json")
            self.assertEqual(report["status"], "uninstalled")
            self.assertFalse(target.exists())
            self.assertFalse((state_root / "install-state.json").exists())

    def test_committed_local_phase_can_be_compensated_if_account_commit_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "new.txt"
            target = root / "target.txt"
            state_root = root / "state"
            source.write_text("new")
            target.write_text("old")
            transaction = InstallTransaction(release_version="2.0.0", state_root=state_root)
            transaction.run("local", lambda: transaction.atomic_copy(source, target))
            transaction.commit()
            self.assertEqual(target.read_text(), "new")

            transaction.rollback(failed_step="account.commit")

            self.assertEqual(target.read_text(), "old")
            self.assertFalse((state_root / "install-state.json").exists())
            report = json.loads((state_root / "last-install-report.json").read_text())
            self.assertEqual(report["status"], "rolled_back")


if __name__ == "__main__":
    unittest.main()
