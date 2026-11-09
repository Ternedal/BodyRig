import json
import struct
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
            result = inventory(root)
            self.assertEqual(result["assets"][0]["status"], "rejected")
            self.assertTrue(result["assets"][0]["reasons"])

    def test_valid_asset_without_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.obj").write_bytes(b"v 0 0 0\n")
            result = inventory(root)
            self.assertEqual(len(result["assets"]), 1)
            self.assertGreaterEqual(result["inventory_total_ms"], 0)
            self.assertGreaterEqual(result["assets"][0]["inventory_ms"], 0)
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

    def test_invalid_asset_does_not_block_valid_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.obj").write_bytes(b"mtllib ../secret.mtl\n")
            (root / "good.obj").write_bytes(b"v 0 0 0\n")
            result = inventory(root)
            self.assertEqual([asset["status"] for asset in result["assets"]], ["rejected", "ok"])

    def test_glb_traversal_rejected_without_blocking_other_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = json.dumps({"buffers": [{"uri": "../secret.bin"}]}).encode()
            payload += b" " * (-len(payload) % 4)
            total = 20 + len(payload)
            glb = struct.pack("<4sIIII", b"glTF", 2, total, len(payload), 0x4E4F534A) + payload
            (root / "bad.glb").write_bytes(glb)
            (root / "good.obj").write_bytes(b"v 0 0 0\n")
            result = inventory(root)
            self.assertEqual([a["status"] for a in result["assets"]], ["rejected", "ok"])

    def test_truncated_glb_rejected(self):
        self.check_rejected("bad.glb", b"glTF")

    def test_mtl_options_and_spaced_texture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.obj").write_text("mtllib materials.mtl\n")
            (root / "materials.mtl").write_text("map_Bump -bm 1.0 my skin.png\n")
            (root / "my skin.png").write_bytes(b"texture")
            result = inventory(root)
            self.assertEqual(result["assets"][0]["status"], "ok")
            self.assertEqual(len(result["assets"][0]["dependencies"]), 2)

    def test_missing_texture_is_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.obj").write_text("mtllib materials.mtl\n")
            (root / "materials.mtl").write_text("map_Kd missing.png\n")
            result = inventory(root)
            self.assertEqual(result["assets"][0]["status"], "degraded")
            self.assertTrue(result["assets"][0]["sha256"])

    def test_multiple_material_libraries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.obj").write_text("mtllib first.mtl second.mtl\n")
            (root / "first.mtl").write_text("newmtl first\n")
            (root / "second.mtl").write_text("newmtl second\n")
            result = inventory(root)
            self.assertEqual(result["assets"][0]["status"], "ok")
            self.assertEqual(len(result["assets"][0]["dependencies"]), 2)

    def test_spaced_material_library_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.obj").write_text("mtllib my materials.mtl\n")
            (root / "my materials.mtl").write_text("newmtl material\n")
            result = inventory(root)
            self.assertEqual(result["assets"][0]["status"], "ok")
            self.assertEqual(len(result["assets"][0]["dependencies"]), 1)

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
