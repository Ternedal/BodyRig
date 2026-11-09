import json
import tempfile
import unittest
from pathlib import Path
from tools.asset3d_inventory import inventory

SOURCE = {"license": "CC0-1.0", "url": "https://example.org/asset",
          "rights_verified": True, "depicts_human": False}


class AssetInventoryTests(unittest.TestCase):
    def check_rejected(self, name, data, source=SOURCE):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / name).write_bytes(data)
            with self.assertRaises(ValueError):
                inventory(root, {name: source})

    def test_valid_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.obj").write_bytes(b"v 0 0 0\n")
            result = inventory(root, {"model.obj": SOURCE})
            self.assertEqual(len(result["assets"]), 1)
            self.assertEqual(len(result["assets"][0]["sha256"]), 64)
            self.assertIs(result["assets"][0]["likeness_authority"], False)

    def test_missing_provenance_rejected(self):
        self.check_rejected("model.fbx", b"dummy", None)

    def test_unapproved_license_rejected(self):
        self.check_rejected("model.glb", b"dummy", {**SOURCE, "license": "unknown"})

    def test_false_string_rights_rejected(self):
        self.check_rejected("model.obj", b"v 0 0 0", {**SOURCE, "rights_verified": "false"})

    def test_human_without_age_rejected(self):
        self.check_rejected("model.obj", b"v 0 0 0", {**SOURCE, "depicts_human": True})

    def test_attribution_required(self):
        self.check_rejected("model.obj", b"v 0 0 0", {**SOURCE, "license": "CC-BY-4.0"})

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
            result = inventory(root, {"a.obj": SOURCE, "b.obj": SOURCE})
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
                inventory(root, {"target.obj": SOURCE})


if __name__ == "__main__":
    unittest.main()
