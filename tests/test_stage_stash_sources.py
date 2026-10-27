import json
import tempfile
import unittest
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
