import hashlib
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
            # _copy_hashing is the single-read copy seam (it replaced shutil.copyfile).
            with patch("bodyrig.stage_stash_sources._copy_hashing", side_effect=broken_copy):
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
                # The read side saw the true bytes, but the write landed corrupted.
                Path(dst).write_bytes(b"bad!!")
                return hashlib.sha256(Path(src).read_bytes()).hexdigest()
            with patch("bodyrig.stage_stash_sources._copy_hashing", side_effect=corrupt_copy):
                with self.assertRaisesRegex(OSError, "SHA256 mismatch"):
                    stage(manifest, base / "snapshot")
            self.assertFalse((base / "snapshot").exists())
            self.assertEqual(list(base.glob(".bodyrig-staging-*")), [])
            self.assertEqual(original.read_bytes(), b"video")


def _manifest(base, paths):
    manifest = base / "manifest.json"
    manifest.write_text(json.dumps({
        "format": "bodyrig-stash-source-manifest",
        "version": 1,
        "selected": [{"path": str(p)} for p in paths],
    }))
    return manifest


class TestSingleReadAndRecovery(unittest.TestCase):
    """Additions for the staging handover (BodyRig #1377, 28 Oct)."""

    def test_each_original_is_read_once(self):
        from bodyrig import stage_stash_sources as module
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            originals = [base / f"o{i}.mp4" for i in range(3)]
            for i, path in enumerate(originals):
                path.write_bytes(bytes([i]) * 1000)
            opened = []
            real_open = Path.open

            def counting_open(self, mode="r", *args, **kwargs):
                if "r" in mode and self in originals:
                    opened.append(self)
                return real_open(self, mode, *args, **kwargs)

            with patch.object(Path, "open", counting_open):
                module.stage(_manifest(base, originals), base / "snapshot")
            self.assertEqual(sorted(opened), sorted(originals), "every original must be opened exactly once")

    def test_source_changed_during_copy_fails_closed(self):
        from bodyrig import stage_stash_sources as module
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "source.mp4"
            original.write_bytes(b"video-bytes")
            real_copy = module._copy_hashing

            def copy_then_touch(src, dst):
                result = real_copy(src, dst)
                with src.open("ab") as f:
                    f.write(b"!")  # the original grows while BodyRig thinks it copied it
                return result

            with patch("bodyrig.stage_stash_sources._copy_hashing", side_effect=copy_then_touch):
                with self.assertRaisesRegex(OSError, "Source changed during copy"):
                    module.stage(_manifest(base, [original]), base / "snapshot")
            self.assertFalse((base / "snapshot").exists())
            self.assertEqual(list(base.glob(".bodyrig-staging-*")), [])

    def test_disk_margin_is_required(self):
        from bodyrig.stage_stash_sources import MIN_FREE_MARGIN_BYTES, required_free_bytes
        self.assertEqual(required_free_bytes(0), MIN_FREE_MARGIN_BYTES)
        self.assertEqual(required_free_bytes(100 * MIN_FREE_MARGIN_BYTES), 105 * MIN_FREE_MARGIN_BYTES)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "source.mp4"
            original.write_bytes(b"x" * 10)
            Usage = namedtuple("Usage", "total used free")
            just_enough_for_sources = Usage(10**12, 0, 10 + MIN_FREE_MARGIN_BYTES - 1)
            with patch("bodyrig.stage_stash_sources.shutil.disk_usage", return_value=just_enough_for_sources):
                with self.assertRaisesRegex(OSError, "Insufficient snapshot disk space"):
                    stage(_manifest(base, [original]), base / "snapshot")

    def test_unsafe_extension_becomes_bin(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            good = base / "a.MKV"
            odd = base / "b.weird ext;rm"
            good.write_bytes(b"1")
            odd.write_bytes(b"2")
            output = stage(_manifest(base, [good, odd]), base / "snapshot")
            names = [Path(item["path"]).name for item in json.loads(output.read_text())["selected"]]
            self.assertEqual(names, ["source-01.mkv", "source-02.bin"])

    def test_snapshot_carries_marker_and_timing_has_no_paths(self):
        from bodyrig.stage_stash_sources import MARKER_NAME
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "private-name.mp4"
            original.write_bytes(b"video")
            timing = base / "timing.json"
            stage(_manifest(base, [original]), base / "snapshot", timing_out=timing)
            self.assertTrue((base / "snapshot" / MARKER_NAME).is_file())
            data = json.loads(timing.read_text())
            self.assertEqual(data["format"], "bodyrig-staging-timing")
            self.assertEqual((data["files"], data["bytes"], data["staged"]), (1, 5, True))
            self.assertGreaterEqual(data["copy_seconds"], 0)
            self.assertGreaterEqual(data["verify_seconds"], 0)
            self.assertNotIn("private-name", timing.read_text())
            self.assertNotIn(str(base), timing.read_text())


class TestStaleCleanup(unittest.TestCase):
    def test_marked_snapshot_and_temp_dirs_from_a_killed_run_are_removed(self):
        from bodyrig.stage_stash_sources import MARKER_NAME, cleanup_stale
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            original = base / "source.mp4"
            original.write_bytes(b"video")
            stage(_manifest(base, [original]), base / "snapshot")
            orphan = base / ".bodyrig-staging-orphan"
            orphan.mkdir()
            (orphan / MARKER_NAME).write_text((base / "snapshot" / MARKER_NAME).read_text())
            self.assertEqual(cleanup_stale(base / "snapshot"), 2)
            self.assertFalse((base / "snapshot").exists())
            self.assertFalse(orphan.exists())
            self.assertEqual(original.read_bytes(), b"video")
            stage(_manifest(base, [original]), base / "snapshot")  # the next run can stage again

    def test_unmarked_directories_are_never_deleted(self):
        from bodyrig.stage_stash_sources import cleanup_stale
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user_data = base / "snapshot"
            user_data.mkdir()
            (user_data / "keep.txt").write_text("not ours")
            lookalike = base / ".bodyrig-staging-lookalike"
            lookalike.mkdir()
            (lookalike / "keep.txt").write_text("not ours either")
            with self.assertRaisesRegex(FileExistsError, "not a BodyRig local source snapshot"):
                cleanup_stale(user_data)
            self.assertTrue((user_data / "keep.txt").exists())
            self.assertTrue((lookalike / "keep.txt").exists())

    def test_nothing_to_clean_is_fine(self):
        from bodyrig.stage_stash_sources import cleanup_stale
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cleanup_stale(Path(tmp) / "snapshot"), 0)
