from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.hands_feet_nails_authority as authority
import bodyrig.hands_feet_nails_source_capture as source_capture


PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-0123456789abcdef0123456789abcdef"
BODYRIG_REVISION = "1" * 40
ASSEMBLY_SHA = "a" * 64
PACKAGE_SHA = "b" * 64


def _png(extra: bytes = b"") -> bytes:
    return source_capture.PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1024, 1024) + extra


def _assembly() -> dict:
    return {
        "format": "bodyrig-person-assembly-receipt",
        "version": 2,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body": {
            "revision_id": BODY_REVISION,
            "body_id": BODY_ID,
            "package_sha256": "c" * 64,
        },
        "voice": {},
        "personality": {},
        "audition": {},
    }


def _body_release(package_sha: str = PACKAGE_SHA) -> dict:
    return {
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "package_sha256": package_sha,
        "production_ready": False,
        "production_activation": False,
    }


def _setup_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    media: dict[str, Path] = {}
    for index, region in enumerate(source_capture.REQUIRED_REGIONS, start=1):
        path = tmp_path / f"scene-{index}.mp4"
        path.write_bytes(f"source-{region}".encode())
        media[f"scene-{index}"] = path

    monkeypatch.setattr(source_capture, "load_profile", lambda root, person_id: {"person_id": person_id})

    def fake_source_files(root, profile, *, body_revision):
        return {
            "body_revision": body_revision,
            "manifest_path": str(tmp_path / "source-manifest.json"),
            "manifest_sha256": "d" * 64,
            "source_files": [
                {
                    "scene_id": scene_id,
                    "name": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "path": str(path),
                }
                for scene_id, path in media.items()
            ],
        }

    monkeypatch.setattr(source_capture, "source_files_for_body", fake_source_files)

    def runner(command, *, check, capture_output, text):
        if len(command) == 2 and command[1] == "-version":
            return SimpleNamespace(stdout="ffmpeg version 7.0-test\n")
        Path(command[-1]).write_bytes(_png())
        return SimpleNamespace(stdout="")

    selections = {
        region: {
            "scene_id": f"scene-{index}",
            "timestamp_ms": index * 1000,
            "crop_norm": [0.1, 0.1, 0.4, 0.4],
        }
        for index, region in enumerate(source_capture.REQUIRED_REGIONS, start=1)
    }
    return source_capture.prepare_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        bodyrig_revision=BODYRIG_REVISION,
        selections=selections,
        runner=runner,
    )


def _render_manifest(tmp_path: Path, package_sha: str = PACKAGE_SHA) -> Path:
    root = tmp_path / "render"
    root.mkdir()
    snapshots = []
    for region in source_capture.REQUIRED_REGIONS:
        filename = f"{region}.png"
        path = root / filename
        path.write_bytes(_png())
        snapshots.append(
            {
                "view": region,
                "file": filename,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "width": 1024,
                "height": 1024,
            }
        )
    manifest = {
        "format": authority.RENDER_FORMAT,
        "version": authority.RENDER_VERSION,
        "body_id": BODY_ID,
        "package_sha256": package_sha,
        "semantics": authority.RENDER_SEMANTICS,
        "snapshots": snapshots,
    }
    path = root / "hands-feet-nails-render-set.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def _checklist() -> dict:
    return {field: True for field in authority.CHECKLIST_FIELDS}


def test_write_and_read_authority_binds_source_render_and_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _setup_source(tmp_path, monkeypatch)
    render = _render_manifest(tmp_path)
    receipt = authority.write_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        source_capture_id=source["capture_id"],
        render_manifest_path=render,
        bodyrig_revision=BODYRIG_REVISION,
        checklist=_checklist(),
        quality_note="Finger, toe and nail detail matches the reviewed source closeups.",
    )

    assert receipt["state"] == "complete"
    assert receipt["source_grounded"] is True
    assert receipt["operator_supplied"] is True
    assert receipt["production_activation"] is False
    assert receipt["body_package_sha256"] == PACKAGE_SHA
    reread = authority.read_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        review_id=receipt["review_id"],
    )
    assert reread == receipt


def test_render_tamper_revokes_frozen_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _setup_source(tmp_path, monkeypatch)
    render = _render_manifest(tmp_path)
    receipt = authority.write_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        source_capture_id=source["capture_id"],
        render_manifest_path=render,
        bodyrig_revision=BODYRIG_REVISION,
        checklist=_checklist(),
        quality_note="Detail review passed against source closeups.",
    )
    root = authority.authority_dir(tmp_path, PERSON_ID, PERSON_REVISION, receipt["review_id"])
    (root / "render" / "left_hand.png").write_bytes(_png(b"tamper"))

    with pytest.raises(authority.HandsFeetNailsAuthorityError, match="render bytes no longer match"):
        authority.read_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            review_id=receipt["review_id"],
        )


def test_source_capture_tamper_revokes_review_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _setup_source(tmp_path, monkeypatch)
    render = _render_manifest(tmp_path)
    receipt = authority.write_authority(
        tmp_path,
        assembly_receipt=_assembly(),
        body_release_status=_body_release(),
        source_capture_id=source["capture_id"],
        render_manifest_path=render,
        bodyrig_revision=BODYRIG_REVISION,
        checklist=_checklist(),
        quality_note="Detail review passed against source closeups.",
    )
    root = source_capture.capture_dir(tmp_path, PERSON_ID, BODY_REVISION, source["capture_id"])
    (root / "right-foot.png").write_bytes(_png(b"tamper"))

    with pytest.raises(authority.HandsFeetNailsAuthorityError, match="source capture authority failed during readback"):
        authority.read_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            review_id=receipt["review_id"],
        )


def test_review_rejects_render_from_different_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _setup_source(tmp_path, monkeypatch)
    render = _render_manifest(tmp_path, package_sha="e" * 64)

    with pytest.raises(authority.HandsFeetNailsAuthorityError, match="different body package"):
        authority.write_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            source_capture_id=source["capture_id"],
            render_manifest_path=render,
            bodyrig_revision=BODYRIG_REVISION,
            checklist=_checklist(),
            quality_note="Review passed.",
        )


def test_review_rejects_generated_placeholder_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _setup_source(tmp_path, monkeypatch)
    render = _render_manifest(tmp_path)

    with pytest.raises(authority.HandsFeetNailsAuthorityError, match="non-placeholder quality note"):
        authority.write_authority(
            tmp_path,
            assembly_receipt=_assembly(),
            body_release_status=_body_release(),
            source_capture_id=source["capture_id"],
            render_manifest_path=render,
            bodyrig_revision=BODYRIG_REVISION,
            checklist=_checklist(),
            quality_note="<your hand/foot review>",
        )
