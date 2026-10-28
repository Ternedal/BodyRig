import json
import tempfile
import unittest
from unittest.mock import patch
from collections import namedtuple
from pathlib import Path
from bodyrig.stage_stash_sources import stage

class TestLocalSnapshot(unittest.TestCase):
    def test_copy_and_offline_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "original.mp4"
            source.write_bytes(b"example")
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({"format": "bodyrig-stash-source-manifest", "version": 1, "selected": [{"path": str(source)}]}))
            output = stage(manifest, base / "snapshot")
            source.unlink()
            selected = json.loads(output.read_text())["selected"]
            self.assertEqual(Path(selected[0]["path"]).read_bytes(), b"example")

    def test_missing_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({"format": "bodyrig-stash-source-manifest", "version": 1, "selected": [{"path": str(base / "absent.mp4")}]}))
            with self.assertRaises(FileNotFoundError):
                stage(manifest, base / "snapshot")
            self.assertFalse((base / "snapshot").exists())

    def test_insufficient_disk_space_cleans_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "source.mp4"
            original.write_bytes(b"video-bytes")
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "selected": [{"path": str(original)}],
            }))
            Usage = namedtuple("Usage", "total used free")
            with patch("bodyrig.stage_stash_sources.shutil.disk_usage", return_value=Usage(100, 100, 0)):
                with self.assertRaisesRegex(OSError, "Insufficient snapshot disk space"):
                    stage(manifest, base / "snapshot")
            self.assertFalse((base / "snapshot").exists())
            self.assertEqual(list(base.glob(".bodyrig-staging-*")), [])

    def test_later_missing_source_cleans_partial_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "first.mp4"
            original.write_bytes(b"first")
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "selected": [{"path": str(original)}, {"path": str(base / "missing.mp4")}],
            }))
            with self.assertRaises(FileNotFoundError):
                stage(manifest, base / "snapshot")
            self.assertFalse((base / "snapshot").exists())
            self.assertEqual(list(base.glob(".bodyrig-staging-*")), [])
            self.assertEqual(original.read_bytes(), b"first")

    def test_duplicate_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "source.mp4"
            original.write_bytes(b"video")
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "selected": [{"path": str(original)}, {"path": str(original)}],
            }))
            with self.assertRaisesRegex(ValueError, "Duplicate source path"):
                stage(manifest, base / "snapshot")
            self.assertFalse((base / "snapshot").exists())

    def test_existing_destination_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "source.mp4"
            original.write_bytes(b"video")
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "selected": [{"path": str(original)}],
            }))
            output = base / "snapshot"
            output.mkdir()
            marker = output / "marker.txt"
            marker.write_text("keep")
            with self.assertRaises(FileExistsError):
                stage(manifest, output)
            self.assertEqual(marker.read_text(), "keep")

    def test_copy_failure_removes_partial_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "source.mp4"
            original.write_bytes(b"video")
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "selected": [{"path": str(original)}],
            }))
            def broken_copy(src, dst):
                Path(dst).write_bytes(b"partial")
                raise OSError("simulated interrupted copy")
            with patch("bodyrig.stage_stash_sources.shutil.copyfile", side_effect=broken_copy):
                with self.assertRaisesRegex(OSError, "simulated interrupted copy"):
                    stage(manifest, base / "snapshot")
            self.assertFalse((base / "snapshot").exists())
            self.assertEqual(list(base.glob(".bodyrig-staging-*")), [])
            self.assertEqual(original.read_bytes(), b"video")

    def test_corrupted_copy_is_rejected_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "source.mp4"
            original.write_bytes(b"video")
            manifest = base / "manifest.json"
            manifest.write_text(json.dumps({
                "format": "bodyrig-stash-source-manifest",
                "version": 1,
                "selected": [{"path": str(original)}],
            }))
            def corrupt_copy(src, dst):
                Path(dst).write_bytes(b"bad!!")
            with patch("bodyrig.stage_stash_sources.shutil.copyfile", side_effect=corrupt_copy):
                with self.assertRaisesRegex(OSError, "SHA256 mismatch"):
                    stage(manifest, base / "snapshot")
            self.assertFalse((base / "snapshot").exists())
            self.assertEqual(list(base.glob(".bodyrig-staging-*")), [])
            self.assertEqual(original.read_bytes(), b"video")
