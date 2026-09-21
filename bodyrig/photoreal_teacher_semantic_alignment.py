from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_teacher_authority import validate_external_teacher_files_strict
from .photoreal_teacher_runner import PhotorealTeacherRunnerError

CAMERA_FORMAT = "bodyrig-photoreal-exavatar-neutral-camera-manifest"
CAMERA_VERSION = 1
HANDOFF_FORMAT = "bodyrig-photoreal-p1-semantic-camera-alignment-handoff"
HANDOFF_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-p1-semantic-camera-alignment"
RECEIPT_VERSION = 1

REQUIRED_SEMANTIC_LABELS = (
    "front",
    "front-left-three-quarter",
    "left-profile",
    "rear",
    "right-profile",
    "front-right-three-quarter",
)


class PhotorealTeacherSemanticAlignmentError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealTeacherSemanticAlignmentError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherSemanticAlignmentError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealTeacherSemanticAlignmentError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum or "\n" in result or "\r" in result:
        raise PhotorealTeacherSemanticAlignmentError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealTeacherSemanticAlignmentError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealTeacherSemanticAlignmentError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealTeacherSemanticAlignmentError(f"{label} format/version mismatch")


def _finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealTeacherSemanticAlignmentError(f"{label} is invalid")
    number = float(value)
    if not math.isfinite(number):
        raise PhotorealTeacherSemanticAlignmentError(f"{label} is invalid")
    return number


def _sha256_file(path: str | Path) -> str:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise PhotorealTeacherSemanticAlignmentError(f"required file is missing or not regular: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_artifact_path(root: Path, relative: str) -> Path:
    rel = Path(relative.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise PhotorealTeacherSemanticAlignmentError("teacher artifact path escapes output root")
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PhotorealTeacherSemanticAlignmentError("teacher artifact path escapes output root") from exc
    return path


def _camera_and_views(
    validated_teacher: Mapping[str, Any],
    teacher_output: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    output = Path(teacher_output).expanduser().resolve()
    artifacts = validated_teacher.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealTeacherSemanticAlignmentError("validated teacher contains no artifacts")
    camera_artifacts = [
        item
        for item in artifacts
        if isinstance(item, Mapping) and item.get("kind") == "neutral-pose-camera-manifest"
    ]
    if len(camera_artifacts) != 1:
        raise PhotorealTeacherSemanticAlignmentError(
            "validated teacher must contain exactly one neutral-pose camera manifest"
        )
    camera_artifact = camera_artifacts[0]
    relative = _text(camera_artifact.get("relative_path"), label="camera manifest relative path")
    if relative != "review/neutral-pose/cameras.json":
        raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera manifest path is noncanonical")
    camera_path = _safe_artifact_path(output, relative)
    if _sha(camera_artifact.get("sha256"), label="camera artifact SHA-256") != _sha256_file(camera_path):
        raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera manifest file SHA mismatch")
    camera = _read_json(camera_path, label="neutral-pose camera manifest")
    if camera.get("format") != CAMERA_FORMAT:
        raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera manifest format/version mismatch")
    _strict_v1(camera.get("version"), label="neutral-pose camera manifest")
    if CAMERA_VERSION != 1:
        raise PhotorealTeacherSemanticAlignmentError("unsupported compiled camera-manifest version")
    if camera.get("upstream_repository") != validated_teacher.get("upstream_repository"):
        raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera manifest upstream repository mismatch")
    if camera.get("upstream_commit") != validated_teacher.get("upstream_commit"):
        raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera manifest upstream commit mismatch")
    claimed = _sha(camera.get("camera_manifest_sha256"), label="camera manifest canonical SHA-256")
    if _digest(camera, omit="camera_manifest_sha256") != claimed:
        raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera manifest digest mismatch")
    if camera.get("semantic_view_labels_machine_assigned") is not False:
        raise PhotorealTeacherSemanticAlignmentError("camera manifest unexpectedly machine-assigned semantic labels")
    if camera.get("human_semantic_alignment_required") is not True:
        raise PhotorealTeacherSemanticAlignmentError("camera manifest removed human semantic alignment")
    if camera.get("photoreal_acceptance_authority") is not False or camera.get("production_activation") is not False:
        raise PhotorealTeacherSemanticAlignmentError("camera manifest crossed downstream authority")

    render_artifacts: dict[str, Mapping[str, Any]] = {}
    for item in artifacts:
        if not isinstance(item, Mapping) or item.get("kind") != "neutral-pose-render":
            continue
        render_relative = _text(item.get("relative_path"), label="neutral render relative path")
        if render_relative in render_artifacts:
            raise PhotorealTeacherSemanticAlignmentError("validated teacher repeats neutral render artifact")
        render_artifacts[render_relative] = item

    views_raw = camera.get("views")
    view_count = camera.get("view_count")
    if isinstance(view_count, bool) or not isinstance(view_count, int) or view_count != 50:
        raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera manifest view count mismatch")
    if not isinstance(views_raw, list) or len(views_raw) != view_count:
        raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera manifest views are incomplete")

    views: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for raw in views_raw:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera view is invalid")
        index = raw.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < view_count or index in seen_indices:
            raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera view index is invalid/duplicated")
        seen_indices.add(index)
        expected_relative = f"review/neutral-pose/{index}.png"
        if _text(raw.get("render_relative_path"), label="camera view render path") != expected_relative:
            raise PhotorealTeacherSemanticAlignmentError("camera view render path/index mismatch")
        if raw.get("semantic_view_label") is not None:
            raise PhotorealTeacherSemanticAlignmentError("camera view unexpectedly contains machine semantic label")
        artifact = render_artifacts.get(expected_relative)
        if artifact is None:
            raise PhotorealTeacherSemanticAlignmentError("camera view has no hash-bound neutral render artifact")
        render_path = _safe_artifact_path(output, expected_relative)
        if _sha(artifact.get("sha256"), label="neutral render SHA-256") != _sha256_file(render_path):
            raise PhotorealTeacherSemanticAlignmentError("neutral render file SHA mismatch")
        views.append(
            {
                "index": index,
                "render_relative_path": expected_relative,
                "render_sha256": _sha(artifact.get("sha256"), label="neutral render SHA-256"),
                "upstream_azimuth_radians": _finite_number(
                    raw.get("upstream_azimuth_radians"),
                    label="camera upstream azimuth radians",
                ),
                "upstream_azimuth_degrees": _finite_number(
                    raw.get("upstream_azimuth_degrees"),
                    label="camera upstream azimuth degrees",
                ),
                "normalized_azimuth_degrees": _finite_number(
                    raw.get("normalized_azimuth_degrees"),
                    label="camera normalized azimuth degrees",
                ),
                "elevation_radians": _finite_number(raw.get("elevation_radians"), label="camera elevation radians"),
                "elevation_degrees": _finite_number(raw.get("elevation_degrees"), label="camera elevation degrees"),
            }
        )
    if seen_indices != set(range(view_count)):
        raise PhotorealTeacherSemanticAlignmentError("neutral-pose camera indices are not complete 0..49")
    views.sort(key=lambda item: item["index"])
    return camera, views, _sha256_file(camera_path)


def build_semantic_alignment_handoff(
    validated_teacher: Mapping[str, Any],
    teacher_output: str | Path,
) -> dict[str, Any]:
    output = Path(teacher_output).expanduser().resolve()
    if validated_teacher.get("training_complete") is not True:
        raise PhotorealTeacherSemanticAlignmentError("semantic alignment requires a completed teacher")
    if validated_teacher.get("photoreal_acceptance_authority") is not False:
        raise PhotorealTeacherSemanticAlignmentError("teacher already crossed photoreal acceptance authority")
    if validated_teacher.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherSemanticAlignmentError("teacher removed human visual acceptance")
    if validated_teacher.get("production_activation") is not False:
        raise PhotorealTeacherSemanticAlignmentError("teacher crossed production authority")

    camera, views, camera_file_sha = _camera_and_views(validated_teacher, output)
    teacher_manifest_path = output / "teacher-manifest.json"
    teacher_manifest_file_sha = _sha256_file(teacher_manifest_path)

    handoff: dict[str, Any] = {
        "format": HANDOFF_FORMAT,
        "version": HANDOFF_VERSION,
        "performer_id": _text(validated_teacher.get("performer_id"), label="teacher performer id", maximum=256),
        "selected_epoch_id": _text(validated_teacher.get("selected_epoch_id"), label="teacher epoch id", maximum=256),
        "teacher_input_sha256": _sha(validated_teacher.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "adapter": _text(validated_teacher.get("adapter"), label="teacher adapter", maximum=256),
        "adapter_revision": _text(validated_teacher.get("adapter_revision"), label="teacher adapter revision", maximum=256),
        "upstream_repository": _text(
            validated_teacher.get("upstream_repository"),
            label="teacher upstream repository",
            maximum=4096,
        ),
        "upstream_commit": _text(validated_teacher.get("upstream_commit"), label="teacher upstream commit", maximum=256),
        "teacher_manifest_file_sha256": teacher_manifest_file_sha,
        "camera_manifest_sha256": _sha(camera.get("camera_manifest_sha256"), label="camera manifest SHA-256"),
        "camera_manifest_file_sha256": camera_file_sha,
        "required_semantic_labels": list(REQUIRED_SEMANTIC_LABELS),
        "view_count": len(views),
        "views": views,
        "operator_requirements": {
            "assign_every_required_semantic_label": True,
            "use_unique_render_index_per_label": True,
            "review_actual_hash_bound_teacher_renders": True,
            "keep_likeness_acceptance_separate": True,
        },
        "human_semantic_alignment_required": True,
        "human_semantic_alignment_complete": False,
        "semantic_camera_alignment_authority": False,
        "human_visual_likeness_acceptance": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    handoff["semantic_alignment_handoff_sha256"] = _digest(
        handoff,
        omit="semantic_alignment_handoff_sha256",
    )
    return handoff


def build_semantic_alignment_handoff_files(
    config_path: str | Path,
    teacher_input_path: str | Path,
    teacher_workspace: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    workspace = Path(teacher_workspace).expanduser().resolve()
    result_root = workspace / "output"
    try:
        validated = validate_external_teacher_files_strict(config_path, teacher_input_path, workspace)
    except PhotorealTeacherRunnerError as exc:
        raise PhotorealTeacherSemanticAlignmentError(f"teacher strict readback failed: {exc}") from exc
    handoff = build_semantic_alignment_handoff(validated, result_root)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        existing = _read_json(output, label="semantic camera alignment handoff")
        if _digest(existing, omit="semantic_alignment_handoff_sha256") != _digest(
            handoff,
            omit="semantic_alignment_handoff_sha256",
        ) or existing != handoff:
            raise PhotorealTeacherSemanticAlignmentError(
                f"existing semantic camera alignment handoff differs from canonical state: {output}"
            )
        return handoff
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(handoff, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return handoff


def record_semantic_alignment(
    validated_teacher: Mapping[str, Any],
    teacher_output: str | Path,
    handoff: Mapping[str, Any],
    *,
    semantic_view_indices: Mapping[str, int],
    reviewed_by: str,
    review_notes: str,
    approve_human_review: bool,
) -> dict[str, Any]:
    canonical = build_semantic_alignment_handoff(validated_teacher, teacher_output)
    if dict(handoff) != canonical:
        raise PhotorealTeacherSemanticAlignmentError("semantic alignment handoff is not canonical for teacher output")
    if approve_human_review is not True:
        raise PhotorealTeacherSemanticAlignmentError("explicit human semantic-alignment approval is required")
    if set(semantic_view_indices) != set(REQUIRED_SEMANTIC_LABELS):
        raise PhotorealTeacherSemanticAlignmentError("semantic alignment must assign every required label exactly once")
    indices: dict[str, int] = {}
    for label in REQUIRED_SEMANTIC_LABELS:
        value = semantic_view_indices.get(label)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < canonical["view_count"]:
            raise PhotorealTeacherSemanticAlignmentError(f"semantic view index is invalid: {label}")
        indices[label] = value
    if len(set(indices.values())) != len(indices):
        raise PhotorealTeacherSemanticAlignmentError("semantic alignment must use unique render indices")
    reviewer = _text(reviewed_by, label="semantic alignment reviewer", maximum=256)
    if not isinstance(review_notes, str) or not review_notes.strip() or len(review_notes) > 8192:
        raise PhotorealTeacherSemanticAlignmentError("semantic alignment review notes are invalid")

    by_index = {item["index"]: item for item in canonical["views"]}
    alignments = [
        {
            "semantic_label": label,
            **by_index[indices[label]],
        }
        for label in REQUIRED_SEMANTIC_LABELS
    ]
    receipt: dict[str, Any] = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "performer_id": canonical["performer_id"],
        "selected_epoch_id": canonical["selected_epoch_id"],
        "teacher_input_sha256": canonical["teacher_input_sha256"],
        "teacher_manifest_file_sha256": canonical["teacher_manifest_file_sha256"],
        "camera_manifest_sha256": canonical["camera_manifest_sha256"],
        "camera_manifest_file_sha256": canonical["camera_manifest_file_sha256"],
        "semantic_alignment_handoff_sha256": canonical["semantic_alignment_handoff_sha256"],
        "alignments": alignments,
        "reviewed_by": reviewer,
        "review_notes": review_notes.strip(),
        "human_semantic_alignment_required": True,
        "human_semantic_alignment_complete": True,
        "semantic_camera_alignment_authority": True,
        "human_visual_likeness_acceptance": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["semantic_alignment_sha256"] = _digest(receipt, omit="semantic_alignment_sha256")
    return receipt


def record_semantic_alignment_files(
    config_path: str | Path,
    teacher_input_path: str | Path,
    teacher_workspace: str | Path,
    handoff_path: str | Path,
    output_path: str | Path,
    *,
    semantic_view_indices: Mapping[str, int],
    reviewed_by: str,
    review_notes: str,
    approve_human_review: bool,
) -> dict[str, Any]:
    workspace = Path(teacher_workspace).expanduser().resolve()
    result_root = workspace / "output"
    try:
        validated = validate_external_teacher_files_strict(config_path, teacher_input_path, workspace)
    except PhotorealTeacherRunnerError as exc:
        raise PhotorealTeacherSemanticAlignmentError(f"teacher strict readback failed: {exc}") from exc
    handoff = _read_json(handoff_path, label="semantic camera alignment handoff")
    receipt = record_semantic_alignment(
        validated,
        result_root,
        handoff,
        semantic_view_indices=semantic_view_indices,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
        approve_human_review=approve_human_review,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealTeacherSemanticAlignmentError(f"semantic camera alignment receipt already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def _parse_mapping(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise PhotorealTeacherSemanticAlignmentError("semantic view mapping must use LABEL=INDEX")
        label, raw_index = value.split("=", 1)
        label = label.strip()
        if not label or label in result:
            raise PhotorealTeacherSemanticAlignmentError("semantic view mapping label is empty/duplicated")
        try:
            index = int(raw_index)
        except ValueError as exc:
            raise PhotorealTeacherSemanticAlignmentError("semantic view mapping index is not an integer") from exc
        result[label] = index
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create and record human semantic orientation alignment for a completed Photoreal V2 teacher."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    handoff = sub.add_parser("handoff")
    handoff.add_argument("--config", type=Path, required=True)
    handoff.add_argument("--teacher-input", type=Path, required=True)
    handoff.add_argument("--teacher-workspace", type=Path, required=True)
    handoff.add_argument("--out", type=Path, required=True)

    record = sub.add_parser("record")
    record.add_argument("--config", type=Path, required=True)
    record.add_argument("--teacher-input", type=Path, required=True)
    record.add_argument("--teacher-workspace", type=Path, required=True)
    record.add_argument("--handoff", type=Path, required=True)
    record.add_argument("--map", action="append", default=[])
    record.add_argument("--reviewed-by", required=True)
    record.add_argument("--review-notes", required=True)
    record.add_argument("--approve-human-review", action="store_true")
    record.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "handoff":
            result = build_semantic_alignment_handoff_files(
                args.config,
                args.teacher_input,
                args.teacher_workspace,
                args.out,
            )
            print(
                json.dumps(
                    {
                        "status": "HUMAN_REVIEW_REQUIRED",
                        "view_count": result["view_count"],
                        "required_semantic_labels": result["required_semantic_labels"],
                        "handoff": str(args.out.expanduser().resolve()),
                        "photoreal_acceptance_authority": False,
                        "production_activation": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 2

        mapping = _parse_mapping(list(args.map))
        result = record_semantic_alignment_files(
            args.config,
            args.teacher_input,
            args.teacher_workspace,
            args.handoff,
            args.out,
            semantic_view_indices=mapping,
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            approve_human_review=args.approve_human_review,
        )
        print(
            json.dumps(
                {
                    "status": "SEMANTIC_ALIGNMENT_RECORDED",
                    "alignment_count": len(result["alignments"]),
                    "semantic_camera_alignment_authority": result["semantic_camera_alignment_authority"],
                    "human_visual_likeness_acceptance": result["human_visual_likeness_acceptance"],
                    "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                    "production_activation": result["production_activation"],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except PhotorealTeacherSemanticAlignmentError as exc:
        print(f"BodyRig P1 semantic camera alignment: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
