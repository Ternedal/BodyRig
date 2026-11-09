import json
import tempfile
import unittest
from pathlib import Path
from tools.asset3d_inventory import inventory

SOURCE = {"license": "CC0-1.0", "url": "https://example.org/asset"}


class AssetInventoryTests(unittest.TestCase):
    def check_rejected(self, name, data):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / name).write_bytes(data)
            with self.assertRaises(ValueError):
                inventory(root)

    def test_valid_asset_without_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.obj").write_bytes(b"v 0 0 0\n")
            result = inventory(root)
            self.assertEqual(len(result["assets"]), 1)
            self.assertEqual(result["assets"][0]["provenance_status"], "unknown")
            self.assertEqual(result["assets"][0]["readiness"], "INVENTORIED")
            self.assertEqual(len(result["assets"][0]["sha256"]), 64)
            self.assertIs(result["assets"][0]["likeness_authority"], False)

    def test_unknown_license_is_nonblocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.fbx").write_bytes(b"dummy")
            result = inventory(root, {"model.fbx": {"license": "unknown"}})
            self.assertEqual(result["assets"][0]["provenance_status"], "provided")

    def test_human_metadata_is_nonblocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.obj").write_bytes(b"v 0 0 0")
            result = inventory(root, {"model.obj": {"depicts_human": True}})
            self.assertIs(result["assets"][0]["likeness_authority"], False)

    def test_invalid_provenance_shape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.obj").write_bytes(b"v 0 0 0")
            with self.assertRaises(ValueError):
                inventory(root, {"model.obj": "invalid"})

    def test_gltf_external_uri_rejected(self):
        self.check_rejected("model.gltf", json.dumps({"buffers": [{"uri": "https://example.org/secret"}]}).encode())

    def test_gltf_traversal_rejected(self):
        self.check_rejected("model.gltf", json.dumps({"buffers": [{"uri": "../secret.bin"}]}).encode())

    def test_obj_traversal_rejected(self):
        self.check_rejected("model.obj", b"mtllib ../secret.mtl\n")

    def test_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("a.obj", "b.obj"):
                (root / name).write_bytes(b"same")
            result = inventory(root)
            self.assertFalse(result["assets"][0]["duplicate"])
            self.assertTrue(result["assets"][1]["duplicate"])

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "target.obj").write_bytes(b"data")
            try:
                (root / "alias.obj").symlink_to(root / "target.obj")
            except (OSError, NotImplementedError):
                self.skipTest("symlink unavailable")
            with self.assertRaises(ValueError):
                inventory(root)


if __name__ == "__main__":
    unittest.main()
