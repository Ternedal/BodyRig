from __future__ import annotations

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
        {"slot": "upper", "layer": 1, "description": "Dark source-visible shirt", "source_views": ["front", "left_side", "right_side", "back"]},
        {"slot": "lower", "layer": 1, "description": "Source-visible trousers", "source_views": ["front", "left_side", "right_side", "back"]},
        {"slot": "footwear", "layer": 1, "description": "Source-visible shoes", "source_views": ["front", "left_side", "right_side", "back"]},
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
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1024, 1024) + suffix)


def test_prepare_and_readback_bind_four_real_source_views_and_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    monkeypatch.setattr(wardrobe, "_source_authority", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(wardrobe, "_run_version", lambda *_args, **_kwargs: "ffmpeg version fixture")

    def fake_extract(*, output: Path, media: Path, **_kwargs) -> None:
        _fake_png(output, media.name.encode("utf-8"))

    monkeypatch.setattr(wardrobe, "_extract", fake_extract)

    receipt = wardrobe.prepare_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        bodyrig_revision=BODYRIG_REVISION,
        views=_views(),
        garments=_garments(),
    )

    assert receipt["source_grounded"] is True
    assert receipt["comparison_only"] is True
    assert receipt["human_review_required"] is True
    assert receipt["production_activation"] is False
    assert receipt["footwear_present"] is True
    assert set(receipt["views"]) == set(wardrobe.REQUIRED_VIEWS)
    for view in wardrobe.REQUIRED_VIEWS:
        assert receipt["views"][view]["scene_id"] == _views()[view]["scene_id"]
        assert receipt["views"][view]["image_sha256"]
    assert [item["slot"] for item in receipt["garments"]] == ["footwear", "lower", "upper"]
    assert all(item["garment_id"].startswith("garment-") for item in receipt["garments"])

    reread = wardrobe.read_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        capture_id=receipt["capture_id"],
    )
    assert reread == receipt


def test_source_capture_requires_real_back_view() -> None:
    views = _views()
    views.pop("back")
    with pytest.raises(wardrobe.WardrobeSourceCaptureError, match="exactly front, left_side, right_side and back"):
        wardrobe._normalize_views(views)


def test_inventory_rejects_ambiguous_slot_layer_pair() -> None:
    garments = _garments()
    garments.append({
        "slot": "upper",
        "layer": 1,
        "description": "Ambiguous second upper garment on same layer",
        "source_views": ["front"],
    })
    with pytest.raises(wardrobe.WardrobeSourceCaptureError, match="ambiguous slot/layer pair"):
        wardrobe._normalize_garments(garments)


def test_inventory_never_infers_footwear_when_not_listed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path)
    monkeypatch.setattr(wardrobe, "_source_authority", lambda *_args, **_kwargs: source)
    monkeypatch.setattr(wardrobe, "_run_version", lambda *_args, **_kwargs: "ffmpeg version fixture")
    monkeypatch.setattr(wardrobe, "_extract", lambda *, output, media, **_kwargs: _fake_png(output, media.name.encode("utf-8")))
    garments = [item for item in _garments() if item["slot"] != "footwear"]

    receipt = wardrobe.prepare_source_capture(
        tmp_path,
        PERSON_ID,
        body_revision=BODY_REVISION,
        bodyrig_revision=BODYRIG_REVISION,
        views=_views(),
        garments=garments,
    )

    assert receipt["footwear_present"] is False
