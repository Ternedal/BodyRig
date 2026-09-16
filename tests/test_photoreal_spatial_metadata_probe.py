from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from bodyrig.photoreal_spatial_metadata_probe import (
    build_spatial_container_probe,
    probe_isobmff_file,
)


def _box(box_type: str, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type.encode("ascii")) + payload


def _spatial_mp4(*, projection: str = "mshp", stereo_mode: int = 2, camm: bool = True) -> bytes:
    full = b"\x00\x00\x00\x00"
    st3d = _box("st3d", full + bytes([stereo_mode]))
    svhd = _box("svhd", full + b"BodyRig-test\x00")
    prhd = _box("prhd", full + b"\x00" * 12)
    if projection == "mshp":
        projection_box = _box("mshp", full + b"\x00" * 4 + b"raw ")
    elif projection == "equi":
        projection_box = _box("equi", full + b"\x00" * 16)
    else:
        projection_box = _box("cbmp", full + b"\x00" * 8)
    sv3d = _box("sv3d", svhd + _box("proj", prhd + projection_box))
    video_entry = _box("avc1", b"\x00" * 78 + st3d + sv3d)
    video_stsd = _box("stsd", full + struct.pack(">I", 1) + video_entry)
    video_track = _box("trak", _box("mdia", _box("minf", _box("stbl", video_stsd))))
    metadata_track = b""
    if camm:
        camm_entry = _box("camm")
        camm_stsd = _box("stsd", full + struct.pack(">I", 1) + camm_entry)
        metadata_track = _box("trak", _box("mdia", _box("minf", _box("stbl", camm_stsd))))
    moov = _box("moov", video_track + metadata_track)
    ftyp = _box("ftyp", b"isom" + b"\x00" * 4 + b"isom")
    return ftyp + moov + _box("mdat", b"payload")


def test_probe_reads_spherical_v2_mesh_stereo_and_camm(tmp_path: Path) -> None:
    path = tmp_path / "vr180.mp4"
    path.write_bytes(_spatial_mp4())

    result = probe_isobmff_file(path)

    assert result["probe_status"] == "parsed-isobmff"
    assert result["sample_entry_types"] == ["avc1", "camm"]
    assert result["st3d_present"] is True
    assert result["stereo_mode_code"] == 2
    assert result["stereo_mode"] == "left-right"
    assert result["sv3d_present"] is True
    assert result["svhd_present"] is True
    assert result["svhd_metadata_source_present"] is True
    assert result["svhd_metadata_source_sha256"] == hashlib.sha256(b"BodyRig-test").hexdigest()
    assert result["proj_present"] is True
    assert result["prhd_present"] is True
    assert result["projection_type"] == "mshp"
    assert result["mesh_projection_encoding"] == "raw "
    assert result["camm_sample_entry_present"] is True
    assert result["projection_metadata_status"] == "spherical-v2-mshp"


def test_probe_reads_equirectangular_projection(tmp_path: Path) -> None:
    path = tmp_path / "equi.mov"
    path.write_bytes(_spatial_mp4(projection="equi", stereo_mode=1, camm=False))

    result = probe_isobmff_file(path)

    assert result["projection_type"] == "equi"
    assert result["stereo_mode"] == "top-bottom"
    assert result["camm_sample_entry_present"] is False
    assert result["projection_metadata_status"] == "spherical-v2-equi"


def test_probe_fails_closed_on_malformed_isobmff(tmp_path: Path) -> None:
    path = tmp_path / "broken.mp4"
    path.write_bytes(struct.pack(">I4s", 4096, b"ftyp") + b"tiny")

    result = probe_isobmff_file(path)

    assert result["probe_status"] == "invalid-or-unreadable-isobmff"
    assert result["projection_metadata_status"] == "invalid-or-unreadable-isobmff"


def test_build_probe_is_path_private_and_receipt_bound(tmp_path: Path) -> None:
    source = tmp_path / "private" / "performer42.mp4"
    source.parent.mkdir()
    source.write_bytes(_spatial_mp4())
    source_key = "scene:s1:E:/private/performer42.mp4"
    inventory = {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "videos": [
            {
                "scene_id": "s1",
                "path": "E:/private/performer42.mp4",
                "projection": "vr180",
                "stereo_layout": "side-by-side",
            }
        ],
        "images": [],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    receipt = {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "sources": [
            {
                "kind": "video",
                "source_id": "s1",
                "source_key": source_key,
                "resolved_path": str(source),
                "size_bytes": source.stat().st_size,
                "sha256": "a" * 64,
            }
        ],
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }

    result = build_spatial_container_probe(inventory, receipt, receipt_sha256="b" * 64)

    assert result["source_receipt_sha256"] == "b" * 64
    assert result["mesh_projection_source_count"] == 1
    assert result["camm_source_count"] == 1
    assert result["diagnostic_only"] is True
    assert result["deprojection_authority"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    encoded = json.dumps(result, sort_keys=True)
    assert str(source) not in encoded
    assert "E:/private" not in encoded
    assert source_key not in encoded
    assert result["sources"][0]["source_key_sha256"] == hashlib.sha256(source_key.encode("utf-8")).hexdigest()
    assert result["sources"][0]["source_size_matches_receipt"] is True
    assert result["sources"][0]["inventory_projection"] == "vr180"
    assert result["sources"][0]["inventory_stereo_layout"] == "side-by-side"
