import tempfile
import unittest
from pathlib import Path
from tools.asset3d_inventory import inventory

SOURCE = {"license": "CC0-1.0", "url": "https://example.org/asset", "rights_verified": True}


class AssetInventoryTests(unittest.TestCase):
    def test_valid_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.obj").write_bytes(b"v 0 0 0\n")
            result = inventory(root, {"model.obj": SOURCE})
            self.assertEqual(len(result["assets"]), 1)
            self.assertEqual(len(result["assets"][0]["sha256"]), 64)

    def test_missing_provenance_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.fbx").write_bytes(b"dummy")
            with self.assertRaises(ValueError):
                inventory(root, {})

    def test_unapproved_license_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.glb").write_bytes(b"dummy")
            with self.assertRaises(ValueError):
                inventory(root, {"model.glb": {**SOURCE, "license": "unknown"}})

    def test_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("a.obj", "b.obj"):
                (root / name).write_bytes(b"same")
            result = inventory(root, {"a.obj": SOURCE, "b.obj": SOURCE})
            self.assertFalse(result["assets"][0]["duplicate"])
            self.assertTrue(result["assets"][1]["duplicate"])

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "target.obj").write_bytes(b"data")
            (root / "alias.obj").symlink_to(root / "target.obj")
            with self.assertRaises(ValueError):
                inventory(root, {"target.obj": SOURCE})


if __name__ == "__main__":
    unittest.main()
