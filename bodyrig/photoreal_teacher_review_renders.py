from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

FORMAT = "bodyrig-photoreal-teacher-review-render-set"
VERSION = 1
TEACHER_MANIFEST_FORMAT = "bodyrig-photoreal-teacher-manifest"
TEACHER_MANIFEST_VERSION = 1
EXAVATAR_ADAPTER = "exavatar-benchmark"
EXAVATAR_UPSTREAM_REPOSITORY = "https://github.com/mks0601/ExAvatar_RELEASE"
EXAVATAR_UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"
EXAVATAR_CAMERA_SOURCE = "avatar/main/get_neutral_pose.py"
EXAVATAR_RENDER_KIND = "neutral-pose-render"
EXAVATAR_RENDER_COUNT = 50
EXAVATAR_RENDER_WIDTH = 1024
EXAVATAR_RENDER_HEIGHT = 1024
EXAVATAR_FOCAL_PX = 1500.0
EXAVATAR_PRINCIPAL_X_PX = 512.0
EXAVATAR_PRINCIPAL_Y_PX = 512.0
EXAVATAR_ELEVATION_RADIANS = -math.pi / 6.0


class PhotorealTeacherReviewRenderError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealTeacherReviewRenderError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherReviewRenderError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealTeacherReviewRenderError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealTeacherReviewRenderError(f"{label} is invalid")
    return result


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealTeacherReviewRenderError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum:
        raise PhotorealTeacherReviewRenderError(f"{label} is invalid")
    return result


def _numeric_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealTeacherReviewRenderError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealTeacherReviewRenderError(f"{label} version must be numeric v1")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_artifact_path(root: Path, relative: Any) -> tuple[str, Path]:
    value = _text(relative, label="teacher render relative path", maximum=4096).replace("\\", "/")
    if value.startswith("/") or value.startswith("../") or "/../" in f"/{value}/" or ":" in value.split("/", 1)[0]:
        raise PhotorealTeacherReviewRenderError("teacher render path escapes output root")
    target = (root / Path(value)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealTeacherReviewRenderError("teacher render path escapes output root") from exc
    return value, target


def _validate_manifest(value: Mapping[str, Any]) -> tuple[str, str, str, list[Mapping[str, Any]]]:
    required = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "adapter",
        "adapter_revision",
        "upstream_repository",
        "upstream_commit",
        "training_complete",
        "consumed_training_source_keys",
        "consumed_training_observations",
        "artifacts",
        "photoreal_acceptance_authority",
        "human_visual_acceptance_required",
        "production_activation",
    }
    if set(value) != required:
        raise PhotorealTeacherReviewRenderError("teacher manifest fields must match v1 exactly")
    if value.get("format") != TEACHER_MANIFEST_FORMAT:
        raise PhotorealTeacherReviewRenderError("teacher manifest format mismatch")
    _numeric_v1(value.get("version"), label="teacher manifest")
    if value.get("training_complete") is not True:
        raise PhotorealTeacherReviewRenderError("teacher manifest does not report complete training")
    if value.get("adapter") != EXAVATAR_ADAPTER:
        raise PhotorealTeacherReviewRenderError("teacher review render calibration only supports the pinned ExAvatar benchmark")
    if value.get("upstream_repository") != EXAVATAR_UPSTREAM_REPOSITORY:
        raise PhotorealTeacherReviewRenderError("teacher manifest ExAvatar repository mismatch")
    if value.get("upstream_commit") != EXAVATAR_UPSTREAM_COMMIT:
        raise PhotorealTeacherReviewRenderError("teacher manifest ExAvatar commit mismatch")
    if value.get("photoreal_acceptance_authority") is not False:
        raise PhotorealTeacherReviewRenderError("teacher manifest crossed photoreal authority")
    if value.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherReviewRenderError("teacher manifest removed human visual acceptance")
    if value.get("production_activation") is not False:
        raise PhotorealTeacherReviewRenderError("teacher manifest crossed production authority")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealTeacherReviewRenderError("teacher manifest contains no artifacts")
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {"kind", "relative_path", "size_bytes", "sha256"}:
            raise PhotorealTeacherReviewRenderError("teacher artifact fields must match v1 exactly")
    return (
        _text(value.get("performer_id"), label="teacher performer id", maximum=256),
        _text(value.get("selected_epoch_id"), label="teacher selected epoch id", maximum=256),
        _sha(value.get("teacher_input_sha256"), label="teacher input SHA-256"),
        artifacts,
    )


def _validate_png(path: Path, *, relative: str) -> None:
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise PhotorealTeacherReviewRenderError(f"teacher review render is not PNG: {relative}")
            if image.size != (EXAVATAR_RENDER_WIDTH, EXAVATAR_RENDER_HEIGHT):
                raise PhotorealTeacherReviewRenderError(
                    f"teacher review render dimensions mismatch: {relative}"
                )
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise PhotorealTeacherReviewRenderError(
            f"teacher review render is unreadable: {relative}"
        ) from exc


def _camera_for_index(index: int) -> dict[str, Any]:
    azimuth_radians = math.pi + math.pi * 2.0 * index / EXAVATAR_RENDER_COUNT
    azimuth_degrees = math.degrees(azimuth_radians)
    normalized = azimuth_degrees % 360.0
    return {
        "orbit_index": index,
        "azimuth_radians": round(azimuth_radians, 12),
        "azimuth_degrees": round(azimuth_degrees, 9),
        "azimuth_degrees_normalized": round(normalized, 9),
        "elevation_radians": round(EXAVATAR_ELEVATION_RADIANS, 12),
        "elevation_degrees": -30.0,
        "render_width": EXAVATAR_RENDER_WIDTH,
        "render_height": EXAVATAR_RENDER_HEIGHT,
        "focal_x_px": EXAVATAR_FOCAL_PX,
        "focal_y_px": EXAVATAR_FOCAL_PX,
        "principal_x_px": EXAVATAR_PRINCIPAL_X_PX,
        "principal_y_px": EXAVATAR_PRINCIPAL_Y_PX,
        "look_at_target": "neutral-smplx-template-mean",
        "up_axis": "positive-y",
    }


def build_teacher_review_render_set(
    teacher_manifest: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
    teacher_manifest_sha256: str,
) -> dict[str, Any]:
    performer_id, selected_epoch_id, teacher_input_sha256, artifacts = _validate_manifest(teacher_manifest)
    root = Path(teacher_output_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealTeacherReviewRenderError(f"teacher output root not found: {root}")
    manifest_sha = _sha(teacher_manifest_sha256, label="teacher manifest SHA-256")

    render_artifacts = [item for item in artifacts if item.get("kind") == EXAVATAR_RENDER_KIND]
    if len(render_artifacts) != EXAVATAR_RENDER_COUNT:
        raise PhotorealTeacherReviewRenderError(
            f"teacher manifest must contain exactly {EXAVATAR_RENDER_COUNT} ExAvatar neutral-pose renders"
        )
    by_path: dict[str, Mapping[str, Any]] = {}
    for raw in render_artifacts:
        relative = _text(raw.get("relative_path"), label="teacher render relative path").replace("\\", "/")
        if relative in by_path:
            raise PhotorealTeacherReviewRenderError("teacher manifest repeats review render path")
        by_path[relative] = raw

    renders: list[dict[str, Any]] = []
    for index in range(EXAVATAR_RENDER_COUNT):
        expected_relative = f"review/neutral-pose/{index}.png"
        raw = by_path.get(expected_relative)
        if raw is None:
            raise PhotorealTeacherReviewRenderError(
                f"teacher manifest is missing calibrated review render: {expected_relative}"
            )
        relative, path = _safe_artifact_path(root, raw.get("relative_path"))
        if not path.is_file():
            raise PhotorealTeacherReviewRenderError(f"teacher review render is missing: {relative}")
        observed_size = path.stat().st_size
        declared_size = raw.get("size_bytes")
        if isinstance(declared_size, bool) or not isinstance(declared_size, int) or declared_size < 1:
            raise PhotorealTeacherReviewRenderError(f"teacher review render size is invalid: {relative}")
        if declared_size != observed_size:
            raise PhotorealTeacherReviewRenderError(f"teacher review render size mismatch: {relative}")
        observed_sha = _hash_file(path)
        if _sha(raw.get("sha256"), label="teacher review render SHA-256") != observed_sha:
            raise PhotorealTeacherReviewRenderError(f"teacher review render SHA-256 mismatch: {relative}")
        _validate_png(path, relative=relative)
        renders.append(
            {
                "relative_path": relative,
                "size_bytes": observed_size,
                "sha256": observed_sha,
                "camera": _camera_for_index(index),
                "semantic_view_label": None,
                "semantic_view_authority": False,
                "human_semantic_view_mapping_required": True,
            }
        )

    if set(by_path) != {item["relative_path"] for item in renders}:
        raise PhotorealTeacherReviewRenderError("teacher review render path universe is not canonical")

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "selected_epoch_id": selected_epoch_id,
        "teacher_input_sha256": teacher_input_sha256,
        "teacher_manifest_sha256": manifest_sha,
        "adapter": EXAVATAR_ADAPTER,
        "upstream_repository": EXAVATAR_UPSTREAM_REPOSITORY,
        "upstream_commit": EXAVATAR_UPSTREAM_COMMIT,
        "camera_calibration_source": EXAVATAR_CAMERA_SOURCE,
        "camera_calibration_formula": "azim=pi+2*pi*i/50;elev=-pi/6;view_num=50",
        "render_count": EXAVATAR_RENDER_COUNT,
        "renders": renders,
        "render_bytes_verified": True,
        "camera_geometry_authority": True,
        "semantic_view_authority": False,
        "human_semantic_view_mapping_required": True,
        "held_out_reference_binding_present": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["review_render_set_sha256"] = _digest(result)
    return result


def build_teacher_review_render_set_files(
    teacher_manifest_path: str | Path,
    teacher_output_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    manifest_path = Path(teacher_manifest_path).expanduser().resolve()
    manifest = _read_json(manifest_path, label="photoreal teacher manifest")
    manifest_sha = _hash_file(manifest_path)
    result = build_teacher_review_render_set(
        manifest,
        teacher_output_root=teacher_output_root,
        teacher_manifest_sha256=manifest_sha,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealTeacherReviewRenderError(f"review render set already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
