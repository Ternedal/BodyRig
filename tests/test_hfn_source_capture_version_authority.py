from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import bodyrig.hands_feet_nails_source_capture as hfn


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)
PERSON_ID = "person-0123456789abcdef0123456789abcdef"
BODY_REVISION = "body-r0001"
BODYRIG_REVISION = "1" * 40


def _png() -> bytes:
    return hfn.PNG_SIGNATURE + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1024, 1024)


def _install_source_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    files: dict[str, Path] = {}
    for index, region in enumerate(hfn.REQUIRED_REGIONS, start=1):
        path = tmp_path / f"scene-{index}.mp4"
        path.write_bytes(f"source-{region}".encode())
        files[f"scene-{index}"] = path

    monkeypatch.setattr(hfn, "load_profile", lambda root, person_id: {"person_id": person_id})

    def fake_source_files(root, profile, *, body_revision):
        return {
            "body_revision": body_revision,
            "manifest_path": str(tmp_path / "source-manifest.json"),
            "manifest_sha256": "a" * 64,
            "source_files": [
                {
                    "scene_id": scene_id,
                    "name": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "path": str(path),
                }
                for scene_id, path in files.items()
            ],
        }

    monkeypatch.setattr(hfn, "source_files_for_body", fake_source_files)
    return {
        region: {
            "scene_id": f"scene-{index}",
            "timestamp_ms": index * 1000,
            "crop_norm": [0.15, 0.20, 0.35, 0.35],
        }
        for index, region in enumerate(hfn.REQUIRED_REGIONS, start=1)
    }


def _runner(command, *, check, capture_output, text):
    assert check is True and capture_output is True and text is True
    if len(command) == 2 and command[1] == "-version":
        return SimpleNamespace(stdout="ffmpeg version 7.0-test\n")
    Path(command[-1]).write_bytes(_png())
    return SimpleNamespace(stdout="")


def _persist_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], Path]:
    selections = _install_source_fixture(tmp_path, monkeypatch)
    receipt = hfn.prepare_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        bodyrig_revision=BODYRIG_REVISION,
        selections=selections,
        runner=_runner,
    )
    path = hfn.capture_dir(tmp_path, PERSON_ID, BODY_REVISION, receipt["capture_id"]) / "source-capture.json"
    return receipt, path


def _rewrite_version(path: Path, version: Any) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    value["version"] = version
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_hfn_source_capture_readback_rejects_boolean_non_numeric_and_wrong_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: Any,
) -> None:
    receipt, path = _persist_capture(tmp_path, monkeypatch)
    _rewrite_version(path, version)

    with pytest.raises(
        hfn.HandsFeetNailsSourceCaptureError,
        match="hands/feet/nails source capture format/version/policy mismatch",
    ):
        hfn.read_source_capture(
            tmp_path,
            PERSON_ID,
            body_revision=BODY_REVISION,
            capture_id=receipt["capture_id"],
        )


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_hfn_source_capture_readback_preserves_numeric_v1_and_source_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: Any,
) -> None:
    receipt, path = _persist_capture(tmp_path, monkeypatch)
    _rewrite_version(path, version)

    value = hfn.read_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        capture_id=receipt["capture_id"],
    )

    assert value["version"] == version
    assert value["capture_id"] == receipt["capture_id"]
    assert value["person_id"] == PERSON_ID
    assert value["body_revision"] == BODY_REVISION
    assert value["bodyrig_revision"] == BODYRIG_REVISION
    assert value["source_manifest_sha256"] == "a" * 64
    assert set(value["regions"]) == set(hfn.REQUIRED_REGIONS)
    assert value["source_grounded"] is True
    assert value["comparison_only"] is True
    assert value["human_review_required"] is True
    assert value["production_activation"] is False
