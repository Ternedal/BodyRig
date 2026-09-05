from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.hands_feet_nails_source_capture as hfn


PERSON_ID = "person-0123456789abcdef0123456789abcdef"
BODY_REVISION = "body-r0001"
BODYRIG_REVISION = "1" * 40


def _png(extra: bytes = b"") -> bytes:
    return hfn.PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1024, 1024) + extra


def _source_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Path], dict]:
    files: dict[str, Path] = {}
    for index, region in enumerate(hfn.REQUIRED_REGIONS, start=1):
        path = tmp_path / f"scene-{index}.mp4"
        path.write_bytes(f"source-{region}".encode())
        files[f"scene-{index}"] = path

    monkeypatch.setattr(hfn, "load_profile", lambda root, person_id: {"person_id": person_id})

    def fake_source_files(root, profile, *, body_revision):
        source_files = []
        for scene_id, path in files.items():
            source_files.append(
                {
                    "scene_id": scene_id,
                    "name": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "path": str(path),
                }
            )
        return {
            "body_revision": body_revision,
            "manifest_path": str(tmp_path / "source-manifest.json"),
            "manifest_sha256": "a" * 64,
            "source_files": source_files,
        }

    monkeypatch.setattr(hfn, "source_files_for_body", fake_source_files)

    selections = {
        region: {
            "scene_id": f"scene-{index}",
            "timestamp_ms": 1000 * index,
            "crop_norm": [0.15, 0.20, 0.35, 0.35],
        }
        for index, region in enumerate(hfn.REQUIRED_REGIONS, start=1)
    }
    return files, selections


def _runner(command, *, check, capture_output, text):
    assert check is True and capture_output is True and text is True
    if len(command) == 2 and command[1] == "-version":
        return SimpleNamespace(stdout="ffmpeg version 7.0-test\n")
    output = Path(command[-1])
    output.write_bytes(_png())
    return SimpleNamespace(stdout="")


def test_prepare_and_read_source_capture_revalidates_exact_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files, selections = _source_fixture(tmp_path, monkeypatch)
    receipt = hfn.prepare_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        bodyrig_revision=BODYRIG_REVISION,
        selections=selections,
        runner=_runner,
    )

    assert receipt["source_grounded"] is True
    assert receipt["production_activation"] is False
    assert set(receipt["regions"]) == set(hfn.REQUIRED_REGIONS)
    reread = hfn.read_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        capture_id=receipt["capture_id"],
    )
    assert reread == receipt

    files["scene-1"].write_bytes(b"tampered-source")
    with pytest.raises(hfn.HandsFeetNailsSourceCaptureError, match="source media no longer matches"):
        hfn.read_source_capture(
            tmp_path,
            PERSON_ID,
            body_revision=BODY_REVISION,
            capture_id=receipt["capture_id"],
        )


def test_source_capture_image_tamper_revokes_authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, selections = _source_fixture(tmp_path, monkeypatch)
    receipt = hfn.prepare_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        bodyrig_revision=BODYRIG_REVISION,
        selections=selections,
        runner=_runner,
    )
    root = hfn.capture_dir(tmp_path, PERSON_ID, BODY_REVISION, receipt["capture_id"])
    (root / "left-hand.png").write_bytes(_png(b"tamper"))

    with pytest.raises(hfn.HandsFeetNailsSourceCaptureError, match="closeup bytes no longer match"):
        hfn.read_source_capture(
            tmp_path,
            PERSON_ID,
            body_revision=BODY_REVISION,
            capture_id=receipt["capture_id"],
        )


def test_source_capture_rejects_crop_outside_frame(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, selections = _source_fixture(tmp_path, monkeypatch)
    selections["left_hand"]["crop_norm"] = [0.9, 0.2, 0.2, 0.3]

    with pytest.raises(hfn.HandsFeetNailsSourceCaptureError, match="normalized frame bounds"):
        hfn.prepare_source_capture(
            tmp_path,
            PERSON_ID,
            body_revision=BODY_REVISION,
            bodyrig_revision=BODYRIG_REVISION,
            selections=selections,
            runner=_runner,
        )


def test_source_capture_rejects_scene_outside_exact_body_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, selections = _source_fixture(tmp_path, monkeypatch)
    selections["right_foot"]["scene_id"] = "not-bound-to-body"

    with pytest.raises(hfn.HandsFeetNailsSourceCaptureError, match="outside the exact body source set"):
        hfn.prepare_source_capture(
            tmp_path,
            PERSON_ID,
            body_revision=BODY_REVISION,
            bodyrig_revision=BODYRIG_REVISION,
            selections=selections,
            runner=_runner,
        )
