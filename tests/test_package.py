import hashlib
import json
import struct
import zipfile
from pathlib import Path

import pytest

from bodyrig.avatar import ProceduralAvatarFitter
from bodyrig.package import MRBodyError, build_package, install_package, validate_package


def glb(payload: bytes = b"") -> bytes:
    return b"glTF" + struct.pack("<II", 2, 12 + len(payload)) + payload


def plain_glb() -> bytes:
    document = json.dumps({"asset": {"version": "2.0"}}, separators=(",", ":")).encode("utf-8")
    document += b" " * ((-len(document)) % 4)
    chunk = struct.pack("<I4s", len(document), b"JSON") + document
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunk)) + chunk


PNG = b"\x89PNG\r\n\x1a\n" + b"test"
BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "shape": {
        "shoulder_to_height": 0.24,
        "hip_to_height": 0.19,
        "arm_to_height": 0.44,
        "leg_to_height": 0.53,
    },
    "motion": {"energy": 0.42},
}
PROVENANCE = {
    "format": "modelrig-body-provenance",
    "version": 1,
    "created_at": "2026-08-23T10:00:00Z",
    "source": {"kind": "user-supplied-local-media", "count": 2},
    "synthetic_avatar": True,
    "pipeline": [{"stage": "body-recovery", "adapter": "fixture", "revision": "fixture-v1"}],
}


def avatar() -> bytes:
    return ProceduralAvatarFitter().fit(BODYPRINT, name="Test Body").avatar_vrm


def make_package(path: Path) -> Path:
    return build_package(
        path,
        body_id="test-body",
        name="Test Body",
        avatar_vrm=avatar(),
        bodyprint=BODYPRINT,
        provenance=PROVENANCE,
        thumbnail_png=PNG,
        motions={"motions/idle.vrma": glb(b"idle")},
    )


def test_roundtrip(tmp_path: Path):
    result = validate_package(make_package(tmp_path / "test.mrbody"))
    assert result.manifest["id"] == "test-body"


def test_checksum_tamper_fails(tmp_path: Path):
    package = make_package(tmp_path / "test.mrbody")
    tampered = tmp_path / "tampered.mrbody"
    with zipfile.ZipFile(package, "r") as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename) + (b"tamper" if info.filename == "thumbnail.png" else b"")
            target.writestr(info, data)
    with pytest.raises(MRBodyError, match="checksum mismatch"):
        validate_package(tampered)


def test_unknown_payload_fails(tmp_path: Path):
    package = make_package(tmp_path / "test.mrbody")
    bad = tmp_path / "bad.mrbody"
    with zipfile.ZipFile(package, "r") as source, zipfile.ZipFile(bad, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr("evil.exe", b"nope")
    with pytest.raises(MRBodyError, match="unknown payload"):
        validate_package(bad)


def test_path_traversal_fails(tmp_path: Path):
    bad = tmp_path / "traversal.mrbody"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../avatar.vrm", glb())
    with pytest.raises(MRBodyError, match="unsafe archive path"):
        validate_package(bad)


def test_nan_fails_build(tmp_path: Path):
    bp = {"format": "modelrig-bodyprint", "version": 1, "motion": {"energy": float("nan")}}
    with pytest.raises(MRBodyError):
        build_package(
            tmp_path / "nan.mrbody",
            body_id="nan-body",
            name="NaN",
            avatar_vrm=avatar(),
            bodyprint=bp,
            provenance=PROVENANCE,
            thumbnail_png=PNG,
        )


def test_plain_glb_cannot_masquerade_as_vrm(tmp_path: Path):
    with pytest.raises(MRBodyError, match="VRMC_vrm|VRM"):
        build_package(
            tmp_path / "plain-glb.mrbody",
            body_id="plain-glb",
            name="Plain GLB",
            avatar_vrm=plain_glb(),
            bodyprint=BODYPRINT,
            provenance=PROVENANCE,
            thumbnail_png=PNG,
        )


def test_install_package_accepts_exact_expected_sha256(tmp_path: Path):
    package = make_package(tmp_path / "source.mrbody")
    expected = hashlib.sha256(package.read_bytes()).hexdigest()
    library = tmp_path / "library"

    installed = install_package(package, library, expected_sha256=expected)

    assert installed == library / "test-body.mrbody"
    assert installed.read_bytes() == package.read_bytes()
    assert hashlib.sha256(installed.read_bytes()).hexdigest() == expected


def test_install_package_hash_mismatch_cannot_overwrite_existing_target(tmp_path: Path):
    package = make_package(tmp_path / "source.mrbody")
    library = tmp_path / "library"
    library.mkdir()
    existing = library / "test-body.mrbody"
    existing.write_bytes(b"existing-trusted-library-bytes")

    with pytest.raises(MRBodyError, match="expected SHA-256 authority"):
        install_package(package, library, expected_sha256="0" * 64)

    assert existing.read_bytes() == b"existing-trusted-library-bytes"
