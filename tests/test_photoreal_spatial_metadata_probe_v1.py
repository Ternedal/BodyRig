from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from bodyrig.photoreal_spatial_metadata_probe import (
    LEGACY_SPHERICAL_V1_UUID,
    probe_isobmff_file,
)


def _box(box_type: str, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type.encode("ascii")) + payload


def _legacy_xml(*, projection: str = "equirectangular", stereo: str = "left-right") -> bytes:
    return (
        '<rdf:SphericalVideo xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:GSpherical="http://ns.google.com/videos/1.0/spherical/">'
        '<GSpherical:Spherical>true</GSpherical:Spherical>'
        '<GSpherical:Stitched>true</GSpherical:Stitched>'
        f'<GSpherical:ProjectionType>{projection}</GSpherical:ProjectionType>'
        f'<GSpherical:StereoMode>{stereo}</GSpherical:StereoMode>'
        '</rdf:SphericalVideo>'
    ).encode("utf-8")


def _legacy_uuid(xml: bytes) -> bytes:
    return _box("uuid", LEGACY_SPHERICAL_V1_UUID + xml)


def _v2_video_entry() -> bytes:
    full = b"\x00\x00\x00\x00"
    st3d = _box("st3d", full + b"\x02")
    svhd = _box("svhd", full + b"test\x00")
    prhd = _box("prhd", full + b"\x00" * 12)
    equi = _box("equi", full + b"\x00" * 16)
    sv3d = _box("sv3d", svhd + _box("proj", prhd + equi))
    return _box("avc1", b"\x00" * 78 + st3d + sv3d)


def _mp4(*, legacy_xml: bytes | None, with_v2: bool = False) -> bytes:
    children = b""
    if legacy_xml is not None:
        children += _legacy_uuid(legacy_xml)
    if with_v2:
        full = b"\x00\x00\x00\x00"
        stsd = _box("stsd", full + struct.pack(">I", 1) + _v2_video_entry())
        children += _box("mdia", _box("minf", _box("stbl", stsd)))
    trak = _box("trak", children)
    return _box("ftyp", b"isom" + b"\x00" * 4 + b"isom") + _box("moov", trak) + _box("mdat", b"payload")


def test_probe_detects_conforming_legacy_v1_without_granting_v2_authority(tmp_path: Path) -> None:
    xml = _legacy_xml()
    path = tmp_path / "legacy.mp4"
    path.write_bytes(_mp4(legacy_xml=xml))

    result = probe_isobmff_file(path)

    assert result["probe_status"] == "parsed-isobmff"
    assert result["spherical_v1_present"] is True
    assert result["spherical_v1_xml_valid"] is True
    assert result["spherical_v1_xml_sha256"] == hashlib.sha256(xml).hexdigest()
    assert result["spherical_v1_spherical"] is True
    assert result["spherical_v1_stitched"] is True
    assert result["spherical_v1_projection_type"] == "equirectangular"
    assert result["spherical_v1_stereo_mode"] == "left-right"
    assert result["spherical_v1_parse_status"] == "valid-v1-equirectangular"
    assert result["sv3d_present"] is False
    assert result["metadata_precedence"] == "v1"
    assert result["projection_metadata_status"] == "spherical-v1-equirectangular-diagnostic"


def test_v2_takes_precedence_when_v1_and_v2_coexist(tmp_path: Path) -> None:
    path = tmp_path / "dual.mp4"
    path.write_bytes(_mp4(legacy_xml=_legacy_xml(), with_v2=True))

    result = probe_isobmff_file(path)

    assert result["spherical_v1_present"] is True
    assert result["sv3d_present"] is True
    assert result["projection_type"] == "equi"
    assert result["metadata_precedence"] == "v2"
    assert result["projection_metadata_status"] == "spherical-v2-equi"


def test_invalid_v1_xml_is_detected_without_exposing_payload(tmp_path: Path) -> None:
    raw = b"<broken private='E:/secret/path'>"
    path = tmp_path / "broken-v1.mp4"
    path.write_bytes(_mp4(legacy_xml=raw))

    result = probe_isobmff_file(path)

    assert result["spherical_v1_present"] is True
    assert result["spherical_v1_xml_valid"] is False
    assert result["spherical_v1_parse_status"] == "invalid-xml"
    assert result["spherical_v1_xml_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["projection_metadata_status"] == "spherical-v1-incomplete-or-nonconforming"
    assert "secret" not in str(result)
    assert "E:/" not in str(result)


def test_nonconforming_v1_never_becomes_projection_authority(tmp_path: Path) -> None:
    path = tmp_path / "nonconforming.mp4"
    path.write_bytes(_mp4(legacy_xml=_legacy_xml(projection="fisheye", stereo="diagonal")))

    result = probe_isobmff_file(path)

    assert result["spherical_v1_parse_status"] == "xml-valid-but-nonconforming-v1"
    assert result["spherical_v1_projection_type"] == "fisheye"
    assert result["spherical_v1_stereo_mode"] == "unsupported-or-unknown"
    assert result["projection_metadata_status"] == "spherical-v1-incomplete-or-nonconforming"
