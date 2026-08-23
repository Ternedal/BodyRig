from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from bodyrig.avatar import ProceduralAvatarFitter
from bodyrig.materialize import RUNTIME_MANIFEST, materialize_runtime
from bodyrig.materialize_cli import main as materialize_main
from bodyrig.package import MRBodyError, build_package


BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "shape": {
        "shoulder_to_height": 0.24,
        "hip_to_height": 0.19,
        "arm_to_height": 0.44,
        "leg_to_height": 0.53,
    },
    "motion": {
        "energy": 0.42,
        "gesture_amplitude": 0.31,
        "head_motion": 0.21,
    },
}

PROVENANCE = {
    "format": "modelrig-body-provenance",
    "version": 1,
    "created_at": "2026-08-23T10:00:00Z",
    "source": {"kind": "user-supplied-local-media", "count": 2},
    "synthetic_avatar": True,
    "pipeline": [
        {"stage": "body-recovery", "adapter": "fixture", "revision": "fixture-recovery-v1"},
        {"stage": "avatar-fitting", "adapter": "procedural-vrm1", "revision": "fixture-fitting-v1"},
    ],
}


def _package(path: Path) -> Path:
    fitted = ProceduralAvatarFitter().fit(BODYPRINT, name="Fixture Person")
    return build_package(
        path,
        body_id="fixture-person",
        name="Fixture Person",
        avatar_vrm=fitted.avatar_vrm,
        bodyprint=BODYPRINT,
        provenance=PROVENANCE,
        thumbnail_png=fitted.thumbnail_png,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_materialize_runtime_binds_assets_to_package_sha(tmp_path: Path):
    package = _package(tmp_path / "fixture.mrbody")
    result = materialize_runtime(package, tmp_path / "runtime")

    assert result.root.is_dir()
    assert result.avatar.is_file()
    assert result.bodyprint.is_file()
    manifest_path = result.root / RUNTIME_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == "bodyrig-runtime-assets"
    assert manifest["version"] == 1
    assert manifest["body_id"] == "fixture-person"
    assert manifest["package_sha256"] == _sha256(package)
    assert manifest["avatar"] == "avatar.vrm"
    assert manifest["bodyprint"] == "bodyprint.json"
    assert sorted(manifest["payloads"]) == sorted(
        ["avatar.vrm", "bodyprint.json", "provenance.json", "thumbnail.png"]
    )

    with zipfile.ZipFile(package, "r") as archive:
        assert result.avatar.read_bytes() == archive.read("avatar.vrm")
        assert result.bodyprint.read_bytes() == archive.read("bodyprint.json")


def test_materialize_cli_reports_exact_runtime_identity(tmp_path: Path, capsys):
    package = _package(tmp_path / "fixture.mrbody")
    target = tmp_path / "runtime"
    exit_code = materialize_main([str(package), "--out", str(target)])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["format"] == "bodyrig-materialize-result"
    assert payload["body_id"] == "fixture-person"
    assert payload["package_sha256"] == _sha256(package)
    assert Path(payload["avatar"]).resolve() == (target / "avatar.vrm").resolve()
    assert Path(payload["runtime_manifest"]).resolve() == (target / RUNTIME_MANIFEST).resolve()


def test_materialize_refuses_existing_destination(tmp_path: Path):
    package = _package(tmp_path / "fixture.mrbody")
    target = tmp_path / "runtime"
    target.mkdir()
    marker = target / "do-not-touch.txt"
    marker.write_text("existing", encoding="utf-8")
    with pytest.raises(MRBodyError, match="already exists"):
        materialize_runtime(package, target)
    assert marker.read_text(encoding="utf-8") == "existing"


def test_materialize_rejects_tampered_package_without_output(tmp_path: Path):
    package = _package(tmp_path / "fixture.mrbody")
    tampered = tmp_path / "tampered.mrbody"
    with zipfile.ZipFile(package, "r") as source, zipfile.ZipFile(tampered, "w") as target_archive:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "avatar.vrm":
                data += b"tamper"
            target_archive.writestr(info, data)

    target = tmp_path / "runtime"
    with pytest.raises(MRBodyError, match="checksum mismatch"):
        materialize_runtime(tampered, target)
    assert not target.exists()


def test_materialized_runtime_contains_no_unvalidated_extra_files(tmp_path: Path):
    package = _package(tmp_path / "fixture.mrbody")
    result = materialize_runtime(package, tmp_path / "runtime")
    relative_files = sorted(
        path.relative_to(result.root).as_posix()
        for path in result.root.rglob("*")
        if path.is_file()
    )
    assert relative_files == [
        "avatar.vrm",
        "bodyprint.json",
        "provenance.json",
        RUNTIME_MANIFEST,
        "thumbnail.png",
    ]
