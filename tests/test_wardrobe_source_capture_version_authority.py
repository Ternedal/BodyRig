from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

import bodyrig.wardrobe_source_capture as wardrobe


PERSON_ID = "person-0123456789abcdef0123456789abcdef"
BODY_REVISION = "body-r0001"
BODYRIG_REVISION = "1" * 40
SOURCE_SHA = "2" * 64


def _views() -> dict:
    return {
        "front": {"scene_id": "scene-front", "timestamp_ms": 1000, "crop_norm": [0.1, 0.05, 0.8, 0.9]},
        "left_side": {"scene_id": "scene-left", "timestamp_ms": 2000, "crop_norm": [0.1, 0.05, 0.8, 0.9]},
        "right_side": {"scene_id": "scene-right", "timestamp_ms": 3000, "crop_norm": [0.1, 0.05, 0.8, 0.9]},
        "back": {"scene_id": "scene-back", "timestamp_ms": 4000, "crop_norm": [0.1, 0.05, 0.8, 0.9]},
    }


def _garments() -> list[dict]:
    return [
        {
            "slot": "upper",
            "layer": 1,
            "description": "Dark source-visible shirt",
            "source_views": ["front", "left_side", "right_side", "back"],
        },
        {
            "slot": "lower",
            "layer": 1,
            "description": "Source-visible trousers",
            "source_views": ["front", "left_side", "right_side", "back"],
        },
    ]


def _source(tmp_path: Path) -> dict:
    files = {}
    for view in wardrobe.REQUIRED_VIEWS:
        scene = f"scene-{view.replace('_side', '')}"
        media = tmp_path / f"{scene}.mp4"
        media.write_bytes(view.encode("utf-8"))
        files[scene] = {
            "scene_id": scene,
            "name": media.name,
            "sha256": (str(wardrobe.REQUIRED_VIEWS.index(view) + 3) * 64)[:64],
            "path": str(media),
        }
    return {"manifest_sha256": SOURCE_SHA, "by_scene": files}


def _fake_png(path: Path, suffix: bytes = b"") -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1024, 1024)
        + suffix
    )


def _prepare_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, Path]:
    source = _source(tmp_path)
    monkeypatch.setattr(wardrobe, "_source_authority", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(wardrobe, "_run_version", lambda *_args, **_kwargs: "ffmpeg version fixture")
    monkeypatch.setattr(
        wardrobe,
        "_extract",
        lambda *, output, media, **_kwargs: _fake_png(output, media.name.encode("utf-8")),
    )
    receipt = wardrobe.prepare_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        bodyrig_revision=BODYRIG_REVISION,
        views=_views(),
        garments=_garments(),
    )
    manifest = (
        wardrobe.capture_dir(tmp_path, PERSON_ID, BODY_REVISION, receipt["capture_id"])
        / "source-capture.json"
    )
    return receipt, manifest


@pytest.mark.parametrize("version", [True, False, "1", None, [], {}, 2])
def test_read_source_capture_rejects_non_numeric_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: object,
) -> None:
    receipt, manifest = _prepare_capture(tmp_path, monkeypatch)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["version"] = version
    manifest.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(wardrobe.WardrobeSourceCaptureError, match="format/version/policy mismatch"):
        wardrobe.read_source_capture(
            tmp_path,
            PERSON_ID,
            body_revision=BODY_REVISION,
            capture_id=receipt["capture_id"],
        )


@pytest.mark.parametrize("version", [1, 1.0])
def test_read_source_capture_accepts_numeric_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: object,
) -> None:
    receipt, manifest = _prepare_capture(tmp_path, monkeypatch)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["version"] = version
    manifest.write_text(json.dumps(value), encoding="utf-8")

    loaded = wardrobe.read_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        capture_id=receipt["capture_id"],
    )

    assert loaded["version"] == version
    assert loaded["capture_id"] == receipt["capture_id"]
    assert loaded["source_manifest_sha256"] == SOURCE_SHA
    assert loaded["source_grounded"] is True
    assert loaded["comparison_only"] is True
    assert loaded["human_review_required"] is True
    assert loaded["production_activation"] is False
