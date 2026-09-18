from __future__ import annotations

import struct
import zlib
from pathlib import Path

from bodyrig.photoreal_spatial_metadata_probe import probe_isobmff_file


def _box(box_type: str, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type.encode("ascii")) + payload


def _fixed_16_16(value: float) -> bytes:
    return int(round(value * 65536.0)).to_bytes(4, "big", signed=True)


def _video_with_projection(projection_box: bytes, *, yaw: float = 12.5, pitch: float = -2.25, roll: float = 30.0) -> bytes:
    full = b"\x00\x00\x00\x00"
    st3d = _box("st3d", full + b"\x02")
    svhd = _box("svhd", full + b"BodyRig-params-test\x00")
    prhd = _box(
        "prhd",
        full + _fixed_16_16(yaw) + _fixed_16_16(pitch) + _fixed_16_16(roll),
    )
    sv3d = _box("sv3d", svhd + _box("proj", prhd + projection_box))
    avc1 = _box("avc1", b"\x00" * 78 + st3d + sv3d)
    stsd = _box("stsd", full + struct.pack(">I", 1) + avc1)
    moov = _box("moov", _box("trak", _box("mdia", _box("minf", _box("stbl", stsd)))))
    return _box("ftyp", b"isom" + b"\x00" * 4 + b"isom") + moov + _box("mdat", b"payload")


def test_probe_extracts_projection_pose_and_equirectangular_bounds(tmp_path: Path) -> None:
    full = b"\x00\x00\x00\x00"
    bounds = (0x10000000, 0x08000000, 0, 0x20000000)
    equi = _box("equi", full + b"".join(value.to_bytes(4, "big") for value in bounds))
    path = tmp_path / "equi.mp4"
    path.write_bytes(_video_with_projection(equi))

    result = probe_isobmff_file(path)

    assert result["prhd_version"] == 0
    assert result["prhd_flags"] == 0
    assert result["projection_pose_yaw_degrees"] == 12.5
    assert result["projection_pose_pitch_degrees"] == -2.25
    assert result["projection_pose_roll_degrees"] == 30.0
    assert result["projection_type"] == "equi"
    assert result["projection_data_version"] == 0
    assert result["projection_data_flags"] == 0
    assert result["equirectangular_bounds_raw"] == {
        "top": 0x10000000,
        "bottom": 0x08000000,
        "left": 0,
        "right": 0x20000000,
    }
    assert result["equirectangular_bounds_fraction"] == {
        "top": 0.0625,
        "bottom": 0.03125,
        "left": 0.0,
        "right": 0.125,
    }
    assert result["equirectangular_bounds_valid"] is True


def test_probe_marks_invalid_equirectangular_crop_pair_without_granting_authority(tmp_path: Path) -> None:
    full = b"\x00\x00\x00\x00"
    bounds = (0xFFFFFFFF, 1, 0, 0)
    equi = _box("equi", full + b"".join(value.to_bytes(4, "big") for value in bounds))
    path = tmp_path / "invalid-equi.mp4"
    path.write_bytes(_video_with_projection(equi))

    result = probe_isobmff_file(path)

    assert result["projection_type"] == "equi"
    assert result["equirectangular_bounds_valid"] is False
    assert result["projection_metadata_status"] == "spherical-v2-equi"


def test_probe_extracts_cubemap_layout_and_padding(tmp_path: Path) -> None:
    full = b"\x00\x00\x00\x00"
    cbmp = _box("cbmp", full + struct.pack(">II", 0, 8))
    path = tmp_path / "cubemap.mp4"
    path.write_bytes(_video_with_projection(cbmp, yaw=0.0, pitch=0.0, roll=0.0))

    result = probe_isobmff_file(path)

    assert result["projection_type"] == "cbmp"
    assert result["cubemap_layout"] == 0
    assert result["cubemap_layout_known"] is True
    assert result["cubemap_padding_pixels"] == 8


def test_probe_verifies_mesh_crc_encoding_and_payload_size(tmp_path: Path) -> None:
    full = b"\x00\x00\x00\x00"
    mesh_payload = _box("mesh", b"synthetic-mesh")
    crc_region = b"raw " + mesh_payload
    stored_crc = zlib.crc32(crc_region) & 0xFFFFFFFF
    mshp = _box("mshp", full + struct.pack(">I", stored_crc) + crc_region)
    path = tmp_path / "mesh.mp4"
    path.write_bytes(_video_with_projection(mshp))

    result = probe_isobmff_file(path)

    assert result["projection_type"] == "mshp"
    assert result["mesh_projection_encoding"] == "raw "
    assert result["mesh_projection_encoding_supported"] is True
    assert result["mesh_projection_payload_bytes"] == len(mesh_payload)
    assert result["mesh_projection_crc32"] == f"{stored_crc:08x}"
    assert result["mesh_projection_crc32_computed"] == f"{stored_crc:08x}"
    assert result["mesh_projection_crc32_matches"] is True


def test_probe_detects_mesh_crc_mismatch_without_rejecting_diagnostic_read(tmp_path: Path) -> None:
    full = b"\x00\x00\x00\x00"
    mesh_payload = _box("mesh", b"synthetic-mesh")
    mshp = _box("mshp", full + struct.pack(">I", 0) + b"raw " + mesh_payload)
    path = tmp_path / "mesh-bad-crc.mp4"
    path.write_bytes(_video_with_projection(mshp))

    result = probe_isobmff_file(path)

    assert result["probe_status"] == "parsed-isobmff"
    assert result["projection_type"] == "mshp"
    assert result["mesh_projection_crc32_matches"] is False
