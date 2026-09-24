import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "snapshot", Path(__file__).with_name("sqlite-migration-snapshot.py"))
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


class MigrationSnapshotTests(unittest.TestCase):
    def test_wal_history_and_notes_survive_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source, target, manifest = [Path(root) / name for name in
                                        ("source.db", "copy.db", "manifest.json")]
            with sqlite3.connect(source) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE history(id INTEGER PRIMARY KEY, note TEXT)")
                db.execute("INSERT INTO history VALUES(42, 'original review note')")
                db.commit()
                record = snapshot.snapshot(source, target, manifest)
                self.assertEqual(record["tables"]["history"], 1)
                self.assertEqual(snapshot.verify(target, manifest), record)
                with sqlite3.connect(target) as restored:
                    self.assertEqual(restored.execute("SELECT * FROM history").fetchone(),
                                     (42, "original review note"))
                    restored.execute("UPDATE history SET note='changed'")
                with self.assertRaises(RuntimeError):
                    snapshot.verify(target, manifest)
                self.assertEqual(db.execute("SELECT note FROM history").fetchone()[0],
                                 "original review note")

    def test_existing_recovery_point_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            source, target, manifest = [Path(root) / name for name in
                                        ("source.db", "copy.db", "manifest.json")]
            with sqlite3.connect(source) as db:
                db.execute("CREATE TABLE history(id INTEGER)")
            snapshot.snapshot(source, target, manifest)
            original = target.read_bytes()
            with self.assertRaises(FileExistsError):
                snapshot.snapshot(source, target, manifest)
            self.assertEqual(target.read_bytes(), original)
            with self.assertRaises(ValueError):
                snapshot.snapshot(source, source, manifest)


if __name__ == "__main__":
    unittest.main()
