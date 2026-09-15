from __future__ import annotations

import copy
import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from bodyrig.photoreal_teacher_review_renders import (
    EXAVATAR_RENDER_COUNT,
    PhotorealTeacherReviewRenderError,
    build_teacher_review_render_set,
)


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1024, 1024), (0, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def _teacher_output(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "teacher-output"
    render_root = root / "review" / "neutral-pose"
    render_root.mkdir(parents=True)
    payload = _png_bytes()
    artifacts: list[dict[str, object]] = []
    for index in range(EXAVATAR_RENDER_COUNT):
        path = render_root / f"{index}.png"
        path.write_bytes(payload)
        artifacts.append(
            {
                "kind": "neutral-pose-render",
                "relative_path": f"review/neutral-pose/{index}.png",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    artifacts.append(
        {
            "kind": "checkpoint",
            "relative_path": "checkpoint/snapshot_4.pth",
            "size_bytes": 123,
            "sha256": "a" * 64,
        }
    )
    manifest: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-manifest",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "b" * 64,
        "adapter": "exavatar-benchmark",
        "adapter_revision": "bodyrig-test",
        "upstream_repository": "https://github.com/mks0601/ExAvatar_RELEASE",
        "upstream_commit": "d45268730c779fae4118f1a361cf9ff639bc4d1e",
        "training_complete": True,
        "consumed_training_source_keys": ["scene:train:E:/train.mp4"],
        "consumed_training_observations": [
            {
                "source_key": "scene:train:E:/train.mp4",
                "frame_sha256": "c" * 64,
                "timestamp_seconds": 1.0,
                "eye": "mono",
            }
        ],
        "artifacts": artifacts,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "production_activation": False,
    }
    return root, manifest


def test_review_render_set_binds_all_exact_exavatar_orbit_renders(tmp_path: Path) -> None:
    root, manifest = _teacher_output(tmp_path)

    result = build_teacher_review_render_set(
        manifest,
        teacher_output_root=root,
        teacher_manifest_sha256="d" * 64,
    )

    assert result["render_count"] == 50
    assert result["render_bytes_verified"] is True
    assert result["camera_geometry_authority"] is True
    assert result["semantic_view_authority"] is False
    assert result["human_semantic_view_mapping_required"] is True
    assert result["held_out_reference_binding_present"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    assert len(result["renders"]) == 50
    assert [item["camera"]["orbit_index"] for item in result["renders"]] == list(range(50))
    assert result["renders"][0]["camera"]["azimuth_degrees"] == 180.0
    assert result["renders"][0]["camera"]["azimuth_degrees_normalized"] == 180.0
    assert result["renders"][25]["camera"]["azimuth_degrees"] == 360.0
    assert result["renders"][25]["camera"]["azimuth_degrees_normalized"] == 0.0
    assert result["renders"][49]["camera"]["azimuth_degrees"] == 532.8
    assert result["renders"][49]["camera"]["azimuth_degrees_normalized"] == 172.8
    assert all(item["semantic_view_label"] is None for item in result["renders"])
    assert all(item["semantic_view_authority"] is False for item in result["renders"])


def test_review_render_set_rejects_boolean_teacher_manifest_v1(tmp_path: Path) -> None:
    root, manifest = _teacher_output(tmp_path)
    manifest["version"] = True

    with pytest.raises(PhotorealTeacherReviewRenderError, match="numeric v1"):
        build_teacher_review_render_set(
            manifest,
            teacher_output_root=root,
            teacher_manifest_sha256="d" * 64,
        )


def test_review_render_set_rejects_wrong_exavatar_commit(tmp_path: Path) -> None:
    root, manifest = _teacher_output(tmp_path)
    manifest["upstream_commit"] = "1" * 40

    with pytest.raises(PhotorealTeacherReviewRenderError, match="commit mismatch"):
        build_teacher_review_render_set(
            manifest,
            teacher_output_root=root,
            teacher_manifest_sha256="d" * 64,
        )


def test_review_render_set_rejects_missing_calibrated_orbit_render(tmp_path: Path) -> None:
    root, manifest = _teacher_output(tmp_path)
    manifest["artifacts"] = [
        item
        for item in manifest["artifacts"]
        if item.get("relative_path") != "review/neutral-pose/17.png"
    ]

    with pytest.raises(PhotorealTeacherReviewRenderError, match="exactly 50"):
        build_teacher_review_render_set(
            manifest,
            teacher_output_root=root,
            teacher_manifest_sha256="d" * 64,
        )


def test_review_render_set_rejects_render_byte_tamper(tmp_path: Path) -> None:
    root, manifest = _teacher_output(tmp_path)
    (root / "review" / "neutral-pose" / "7.png").write_bytes(b"tampered")

    with pytest.raises(PhotorealTeacherReviewRenderError, match="size mismatch"):
        build_teacher_review_render_set(
            manifest,
            teacher_output_root=root,
            teacher_manifest_sha256="d" * 64,
        )


def test_review_render_set_rejects_noncanonical_extra_neutral_render_path(tmp_path: Path) -> None:
    root, manifest = _teacher_output(tmp_path)
    extra = copy.deepcopy(manifest["artifacts"][0])
    extra["relative_path"] = "review/neutral-pose/50.png"
    manifest["artifacts"].append(extra)

    with pytest.raises(PhotorealTeacherReviewRenderError, match="exactly 50"):
        build_teacher_review_render_set(
            manifest,
            teacher_output_root=root,
            teacher_manifest_sha256="d" * 64,
        )
