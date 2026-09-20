from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from bodyrig.photoreal_equirectangular_deprojection import (
    build_equirectangular_remap,
    build_equirectangular_viewports,
)
from bodyrig import photoreal_identity_group_review as review


FORMAT = "bodyrig-photoreal-identity-representation-diagnostic"
VERSION = 1
ATTESTATION_FORMAT = "bodyrig-photoreal-identity-group-attestation"
FOV_SWEEP = (110.0, 90.0, 75.0, 60.0)


class PhotorealIdentityRepresentationDiagnosticError(RuntimeError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityRepresentationDiagnosticError(
            f"{label} is unreadable: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityRepresentationDiagnosticError(
            f"{label} must be a JSON object"
        )
    return value


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotorealIdentityRepresentationDiagnosticError(
            f"required file is missing: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _request_transport_equivalent(
    origin: Mapping[str, Any],
    execution: Mapping[str, Any],
) -> None:
    origin_copy = json.loads(json.dumps(origin, allow_nan=False))
    execution_copy = json.loads(json.dumps(execution, allow_nan=False))
    origin_sources = origin_copy.get("sources")
    execution_sources = execution_copy.get("sources")
    if not isinstance(origin_sources, list) or not isinstance(execution_sources, list):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity request transport sources are invalid"
        )
    if len(origin_sources) != len(execution_sources):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity request transport changed source count"
        )
    for origin_source, execution_source in zip(
        origin_sources,
        execution_sources,
        strict=True,
    ):
        if not isinstance(origin_source, dict) or not isinstance(execution_source, dict):
            raise PhotorealIdentityRepresentationDiagnosticError(
                "identity request transport source is invalid"
            )
        if origin_source.get("source_key") != execution_source.get("source_key"):
            raise PhotorealIdentityRepresentationDiagnosticError(
                "identity request transport changed source order/identity"
            )
        origin_source.pop("resolved_path", None)
        execution_source.pop("resolved_path", None)
        if origin_source != execution_source:
            raise PhotorealIdentityRepresentationDiagnosticError(
                "identity request transport changed source authority beyond resolved_path"
            )
    origin_copy["sources"] = origin_sources
    execution_copy["sources"] = execution_sources
    if origin_copy != execution_copy:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity request transport changed request authority beyond resolved_path"
        )


def _load_adapter(repo_root: Path):
    path = repo_root / "tools" / "photoreal_reference_vision_adapter_mesh.py"
    spec = importlib.util.spec_from_file_location(
        "bodyrig_identity_representation_diagnostic_adapter",
        path,
    )
    if spec is None or spec.loader is None:
        raise PhotorealIdentityRepresentationDiagnosticError(
            f"could not load reference adapter: {path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _normalize(vector: Any, *, dimension: int, label: str) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimension:
        raise PhotorealIdentityRepresentationDiagnosticError(
            f"{label} dimension mismatch"
        )
    values = [float(item) for item in vector]
    if any(not math.isfinite(item) for item in values):
        raise PhotorealIdentityRepresentationDiagnosticError(
            f"{label} contains non-finite value"
        )
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise PhotorealIdentityRepresentationDiagnosticError(
            f"{label} has invalid norm"
        )
    return [value / norm for value in values]


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "cannot build centroid from no vectors"
        )
    dimension = len(vectors[0])
    if any(len(vector) != dimension for vector in vectors):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "embedding dimensions are inconsistent"
        )
    mean = [
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(dimension)
    ]
    norm = math.sqrt(sum(value * value for value in mean))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "embedding centroid collapsed"
        )
    return [value / norm for value in mean]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "embedding dimensions are inconsistent"
        )
    return max(
        -1.0,
        min(1.0, sum(a * b for a, b in zip(left, right, strict=True))),
    )


def _summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min": round(min(values), 9),
        "median": round(statistics.median(values), 9),
        "max": round(max(values), 9),
    }


def _validate_attestation(
    *,
    review_root: Path,
    bank: Mapping[str, Any],
) -> dict[str, Any]:
    public_path = review_root / "identity-group-review-candidates.json"
    private_path = review_root / "private-review-index.json"
    attestation_path = review_root / "identity-group-attestation.json"
    public = _read_json(public_path, label="identity group review manifest")
    private = _read_json(private_path, label="private identity group review index")
    attestation = _read_json(attestation_path, label="identity group attestation")

    if (
        attestation.get("format") != ATTESTATION_FORMAT
        or attestation.get("version") != 1
    ):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity group attestation format/version mismatch"
        )
    if attestation.get("human_identity_attested") is not True:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity group attestation lacks human identity confirmation"
        )
    if attestation.get("identity_group_selection_authority") is not True:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity group attestation lacks group-selection authority"
        )
    for field in (
        "identity_matching_authorized",
        "teacher_training_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        if attestation.get(field) is not False:
            raise PhotorealIdentityRepresentationDiagnosticError(
                f"identity group attestation crossed downstream authority: {field}"
            )

    bank_sha = str(bank.get("identity_bank_sha256") or "").strip().lower()
    if str(attestation.get("identity_bank_sha256") or "").strip().lower() != bank_sha:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity group attestation targets a different identity bank"
        )
    if attestation.get("review_manifest_sha256") != _sha256_file(public_path):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity group attestation lost review-manifest binding"
        )
    if attestation.get("private_review_index_sha256") != _sha256_file(private_path):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity group attestation lost private-index binding"
        )

    public_groups = public.get("groups")
    private_groups = private.get("groups")
    references = bank.get("references")
    if (
        not isinstance(public_groups, list)
        or not isinstance(private_groups, list)
        or not isinstance(references, list)
    ):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity group evidence is incomplete"
        )
    bank_groups = {
        str(item.get("group_id") or "").strip()
        for item in references
        if isinstance(item, Mapping)
    }
    accepted = {
        str(value or "").strip()
        for value in attestation.get("accepted_group_ids") or []
    }
    rejected = {
        str(value or "").strip()
        for value in attestation.get("rejected_group_ids") or []
    }
    if not bank_groups or accepted != bank_groups or rejected:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "representation diagnostic requires every bank group to be human-attested as the target identity"
        )

    sheet_hashes = attestation.get("review_sheet_sha256_by_group")
    if not isinstance(sheet_hashes, Mapping) or set(sheet_hashes) != bank_groups:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity group attestation review-sheet hash set mismatch"
        )
    private_by_group = {
        str(item.get("group_id") or "").strip(): item
        for item in private_groups
        if isinstance(item, Mapping)
    }
    public_by_group = {
        str(item.get("group_id") or "").strip(): item
        for item in public_groups
        if isinstance(item, Mapping)
    }
    if set(private_by_group) != bank_groups or set(public_by_group) != bank_groups:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity group review group set mismatch"
        )
    sheet_root = (review_root / "private-review-sheets").resolve()
    for group_id in sorted(bank_groups):
        path = Path(
            str(private_by_group[group_id].get("review_sheet") or "")
        ).expanduser().resolve()
        try:
            path.relative_to(sheet_root)
        except ValueError as exc:
            raise PhotorealIdentityRepresentationDiagnosticError(
                f"review sheet path escapes review root for group {group_id}"
            ) from exc
        observed = _sha256_file(path)
        if observed != str(sheet_hashes[group_id]).strip().lower():
            raise PhotorealIdentityRepresentationDiagnosticError(
                f"review sheet bytes changed for group {group_id}"
            )
        if observed != str(
            public_by_group[group_id].get("review_sheet_sha256") or ""
        ).strip().lower():
            raise PhotorealIdentityRepresentationDiagnosticError(
                f"review sheet/public manifest mismatch for group {group_id}"
            )
    return attestation


def _profile_embedding(
    *,
    adapter: Any,
    runtime: Any,
    portrait_root: Path,
    performer_id: str,
    bank_sha: str,
) -> tuple[Path, str, list[float]]:
    profile_path, profile_sha, _ = review._portrait_reference(
        portrait_root,
        performer_id=performer_id,
        expected_bank_sha=bank_sha,
    )
    image = runtime.cv2.imread(str(profile_path), runtime.cv2.IMREAD_COLOR)
    if image is None or getattr(image, "size", 0) == 0:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "performer profile reference could not be decoded"
        )
    candidates = adapter._candidates(runtime, image)
    face_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("face") is not None
    ]
    if len(candidates) != 1 or len(face_candidates) != 1:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "performer profile reference no longer resolves to one unambiguous face"
        )
    vector = adapter._embedding(
        face_candidates[0]["face"],
        runtime.embedding_dimension,
    )
    if vector is None:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "performer profile reference has no identity embedding"
        )
    return profile_path, profile_sha, vector


def _pose_values(face: Any) -> dict[str, float] | None:
    raw = getattr(face, "pose", None)
    if raw is None:
        return None
    if hasattr(raw, "tolist"):
        raw = raw.tolist()
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        pitch, yaw, roll = (float(raw[index]) for index in range(3))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (pitch, yaw, roll)):
        return None
    return {
        "pitch_degrees": round(pitch, 6),
        "yaw_degrees": round(yaw, 6),
        "roll_degrees": round(roll, 6),
    }


def _face_quality(adapter: Any, runtime: Any, image: Any, face: Any) -> dict[str, Any]:
    box = adapter._face_bbox(face)
    if box is None:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "accepted identity face lost its bounding box"
        )
    height, width = image.shape[:2]
    face_width = max(0.0, box[2] - box[0])
    face_height = max(0.0, box[3] - box[1])
    center_x = (box[0] + box[2]) * 0.5
    center_y = (box[1] + box[3]) * 0.5
    diagonal = math.hypot(width * 0.5, height * 0.5)
    offset = (
        math.hypot(center_x - width * 0.5, center_y - height * 0.5) / diagonal
        if diagonal > 0
        else 0.0
    )
    crop = adapter._crop(image, box)
    return {
        "det_score": round(float(getattr(face, "det_score", 0.0) or 0.0), 9),
        "view_bin": adapter._view_bin(face),
        "pose": _pose_values(face),
        "bbox_width_pixels": round(face_width, 3),
        "bbox_height_pixels": round(face_height, 3),
        "bbox_min_dimension_pixels": round(min(face_width, face_height), 3),
        "bbox_area_fraction": round(
            0.0 if width * height <= 0 else (face_width * face_height) / (width * height),
            9,
        ),
        "face_center_offset_fraction": round(offset, 9),
        "frame_sharpness": adapter._sharpness(runtime, image),
        "face_crop_sharpness": adapter._sharpness(runtime, crop),
    }


def _match_exact_viewport(
    *,
    adapter: Any,
    runtime: Any,
    source: Mapping[str, Any],
    sample: Mapping[str, Any],
    expected_frame_sha: str,
) -> tuple[Any, str | None, Mapping[str, Any] | None, Any, bool]:
    eye_image, spatial = adapter._read_sample(runtime, source, sample)
    if not spatial:
        if adapter._frame_sha(eye_image) != expected_frame_sha:
            raise PhotorealIdentityRepresentationDiagnosticError(
                "rectilinear identity frame SHA no longer reproduces"
            )
        return eye_image, None, None, eye_image, False
    if source.get("projection") != "equi":
        raise PhotorealIdentityRepresentationDiagnosticError(
            "representation diagnostic currently requires equirectangular spatial identity sources"
        )
    authority = source.get("projection_authority")
    viewports = adapter.deproject_equirectangular_views(
        runtime,
        eye_image,
        authority,
    )
    viewport_meta = {
        str(item["viewport_id"]): item
        for item in build_equirectangular_viewports(authority)
    }
    matches = [
        (viewport_id, viewport_image)
        for viewport_id, viewport_image in viewports
        if adapter._frame_sha(viewport_image) == expected_frame_sha
    ]
    if len(matches) != 1:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "stored identity frame SHA did not resolve to exactly one equirectangular viewport"
        )
    viewport_id, viewport_image = matches[0]
    return viewport_image, viewport_id, viewport_meta[viewport_id], eye_image, True


def _face_center_world_angles(
    *,
    viewport: Mapping[str, Any],
    bbox: tuple[float, float, float, float],
    image_width: int,
    image_height: int,
) -> tuple[float, float]:
    center_x = (bbox[0] + bbox[2]) * 0.5
    center_y = (bbox[1] + bbox[3]) * 0.5
    normalized_x = (center_x / image_width) * 2.0 - 1.0
    normalized_y_down = (center_y / image_height) * 2.0 - 1.0

    yaw = math.radians(float(viewport["yaw_degrees"]))
    pitch = math.radians(float(viewport["pitch_degrees"]))
    hfov = math.radians(float(viewport["horizontal_fov_degrees"]))
    vfov = math.radians(float(viewport["vertical_fov_degrees"]))
    camera_x = normalized_x * math.tan(hfov * 0.5)
    camera_y = -normalized_y_down * math.tan(vfov * 0.5)

    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    forward = (cp * sy, sp, -cp * cy)
    right = (cy, 0.0, sy)
    up = (-sp * sy, cp, sp * cy)

    ray = [
        forward[index]
        + camera_x * right[index]
        + camera_y * up[index]
        for index in range(3)
    ]
    norm = math.sqrt(sum(value * value for value in ray))
    if norm <= 1e-12:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "face-centered projection ray collapsed"
        )
    ray = [value / norm for value in ray]
    face_yaw = math.degrees(math.atan2(ray[0], -ray[2]))
    face_pitch = math.degrees(math.asin(max(-1.0, min(1.0, ray[1]))))
    return round(face_yaw, 6), round(face_pitch, 6)


def _centered_view(
    *,
    adapter: Any,
    runtime: Any,
    eye_image: Any,
    authority: Mapping[str, Any],
    yaw: float,
    pitch: float,
    fov: float,
) -> Any:
    viewport = {
        "viewport_id": "face-centered",
        "yaw_degrees": yaw,
        "pitch_degrees": pitch,
        "horizontal_fov_degrees": fov,
        "vertical_fov_degrees": fov,
    }
    height, width = eye_image.shape[:2]
    map_x, map_y = build_equirectangular_remap(
        runtime.np,
        image_width=width,
        image_height=height,
        projection_authority=authority,
        viewport=viewport,
    )
    image = runtime.cv2.remap(
        eye_image,
        map_x,
        map_y,
        interpolation=runtime.cv2.INTER_LINEAR,
        borderMode=runtime.cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    if image is None or getattr(image, "size", 0) == 0:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "face-centered deprojection produced an empty viewport"
        )
    return runtime.np.ascontiguousarray(image)


def _single_face_measurement(
    *,
    adapter: Any,
    runtime: Any,
    image: Any,
) -> tuple[list[float] | None, dict[str, Any]]:
    candidates = adapter._candidates(runtime, image)
    face_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("face") is not None
    ]
    if len(candidates) == 0:
        return None, {
            "status": "no-person-candidates",
            "candidate_count": 0,
            "face_candidate_count": 0,
        }
    if len(candidates) != 1:
        return None, {
            "status": "multiple-person-candidates",
            "candidate_count": len(candidates),
            "face_candidate_count": len(face_candidates),
        }
    face = candidates[0].get("face")
    if face is None:
        return None, {
            "status": "single-person-without-face",
            "candidate_count": 1,
            "face_candidate_count": 0,
        }
    vector = adapter._embedding(face, runtime.embedding_dimension)
    if vector is None:
        return None, {
            "status": "face-without-embedding",
            "candidate_count": 1,
            "face_candidate_count": 1,
        }
    return vector, {
        "status": "available",
        "candidate_count": 1,
        "face_candidate_count": 1,
        **_face_quality(adapter, runtime, image, face),
    }


def _aggregate(
    measurements: list[dict[str, Any]],
    *,
    total_reference_count: int,
) -> dict[str, Any]:
    usable = [
        item
        for item in measurements
        if isinstance(item.get("_embedding"), list)
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in usable:
        grouped[str(item["group_id"])].append(item)

    leave_group_out: list[float] = []
    within_group: list[float] = []
    group_centroids: dict[str, list[float]] = {}
    for group_id, rows in grouped.items():
        vectors = [row["_embedding"] for row in rows]
        group_centroids[group_id] = _centroid(vectors)
        for left in range(len(vectors)):
            for right in range(left + 1, len(vectors)):
                within_group.append(_cosine(vectors[left], vectors[right]))

    for item in usable:
        others = [
            row["_embedding"]
            for row in usable
            if row["group_id"] != item["group_id"]
        ]
        if others:
            leave_group_out.append(
                _cosine(item["_embedding"], _centroid(others))
            )

    cross_group = []
    group_ids = sorted(group_centroids)
    for left in range(len(group_ids)):
        for right in range(left + 1, len(group_ids)):
            cross_group.append(
                _cosine(
                    group_centroids[group_ids[left]],
                    group_centroids[group_ids[right]],
                )
            )

    profile = [
        float(item["profile_cosine"])
        for item in usable
        if item.get("profile_cosine") is not None
    ]
    min_face = [
        float(item["quality"]["bbox_min_dimension_pixels"])
        for item in usable
        if isinstance(item.get("quality"), Mapping)
        and item["quality"].get("bbox_min_dimension_pixels") is not None
    ]
    det_scores = [
        float(item["quality"]["det_score"])
        for item in usable
        if isinstance(item.get("quality"), Mapping)
        and item["quality"].get("det_score") is not None
    ]
    return {
        "measurement_count": len(usable),
        "reference_coverage": round(
            0.0
            if total_reference_count <= 0
            else len(usable) / total_reference_count,
            9,
        ),
        "group_count": len(grouped),
        "leave_group_out_cosine": _summary(leave_group_out),
        "within_group_pairwise_cosine": _summary(within_group),
        "cross_group_centroid_cosine": _summary(cross_group),
        "profile_cosine": _summary(profile),
        "face_min_dimension_pixels": _summary(min_face),
        "face_detection_score": _summary(det_scores),
    }


def _public_measurement(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key != "_embedding"
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnostic-only replay and FOV sweep for a fully human-attested "
            "BodyRig Photoreal identity bank."
        )
    )
    parser.add_argument("--identity-bank", type=Path, required=True)
    parser.add_argument("--identity-request", type=Path, required=True)
    parser.add_argument("--identity-request-origin", type=Path, required=True)
    parser.add_argument("--portrait-root", type=Path, required=True)
    parser.add_argument("--review-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.out.expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityRepresentationDiagnosticError(
            f"diagnostic output already exists: {output}"
        )

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    adapter = _load_adapter(repo_root)
    adapter_revision = adapter._self_revision()

    bank_path = args.identity_bank.expanduser().resolve()
    request_path = args.identity_request.expanduser().resolve()
    request_origin_path = args.identity_request_origin.expanduser().resolve()
    portrait_root = args.portrait_root.expanduser().resolve()
    review_root = args.review_root.expanduser().resolve()
    model_root = args.model_root.expanduser().resolve()

    bank = _read_json(bank_path, label="identity bank")
    performer_id, bank_sha = review._validate_bank(
        bank,
        adapter_revision=adapter_revision,
    )
    request = _read_json(request_path, label="Stage-7 identity execution request")
    request_origin = _read_json(
        request_origin_path,
        label="Stage-7 identity original request",
    )
    _request_transport_equivalent(request_origin, request)
    sources = review._validate_request(
        request,
        performer_id=performer_id,
        bank=bank,
        adapter_revision=adapter_revision,
    )
    attestation = _validate_attestation(
        review_root=review_root,
        bank=bank,
    )

    model_set = adapter.build_model_set(model_root)
    if str(model_set.get("model_set_sha256") or "").strip().lower() != str(
        bank.get("model_set_sha256") or ""
    ).strip().lower():
        raise PhotorealIdentityRepresentationDiagnosticError(
            "model root does not match identity bank model set"
        )
    manifest = adapter._load_model_manifest(model_root)
    runtime = adapter._load_runtime(manifest, device=args.device)
    if runtime.embedding_dimension != bank.get("embedding_dimension"):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "runtime embedding dimension does not match identity bank"
        )

    profile_path, profile_sha, profile_vector = _profile_embedding(
        adapter=adapter,
        runtime=runtime,
        portrait_root=portrait_root,
        performer_id=performer_id,
        bank_sha=bank_sha,
    )

    references = bank.get("references")
    if not isinstance(references, list) or not references:
        raise PhotorealIdentityRepresentationDiagnosticError(
            "identity bank contains no references"
        )

    variants: dict[str, list[dict[str, Any]]] = defaultdict(list)
    per_reference: list[dict[str, Any]] = []
    by_source_sample_variant: dict[
        tuple[str, float | None, str],
        dict[str, list[float]],
    ] = defaultdict(dict)

    for index, raw in enumerate(references):
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityRepresentationDiagnosticError(
                "identity bank reference is invalid"
            )
        group_id = str(raw.get("group_id") or "").strip()
        source_key = str(raw.get("source_key") or "").strip()
        source = sources.get(source_key)
        if source is None:
            raise PhotorealIdentityRepresentationDiagnosticError(
                f"bank reference source not present in Stage-7 request: {source_key}"
            )
        samples = source.get("reference_samples")
        if not isinstance(samples, list):
            raise PhotorealIdentityRepresentationDiagnosticError(
                f"Stage-7 source lacks reference samples: {source_key}"
            )
        target_key = review._sample_key(
            raw.get("timestamp_seconds"),
            raw.get("eye"),
        )
        matching_samples = [
            sample
            for sample in samples
            if isinstance(sample, Mapping)
            and review._sample_key(
                sample.get("timestamp_seconds"),
                sample.get("eye"),
            )
            == target_key
        ]
        if len(matching_samples) != 1:
            raise PhotorealIdentityRepresentationDiagnosticError(
                f"bank reference did not resolve to one Stage-7 sample: {source_key}"
            )
        sample = matching_samples[0]
        expected_frame_sha = str(raw.get("frame_sha256") or "").strip().lower()
        matched_image, viewport_id, viewport, eye_image, spatial = _match_exact_viewport(
            adapter=adapter,
            runtime=runtime,
            source=source,
            sample=sample,
            expected_frame_sha=expected_frame_sha,
        )
        replay_vector, replay_quality = _single_face_measurement(
            adapter=adapter,
            runtime=runtime,
            image=matched_image,
        )
        if replay_vector is None:
            raise PhotorealIdentityRepresentationDiagnosticError(
                f"accepted bank reference no longer replays as one identity: {source_key}"
            )
        stored_vector = _normalize(
            raw.get("embedding"),
            dimension=runtime.embedding_dimension,
            label=f"bank reference[{index}] embedding",
        )
        replay_to_bank = _cosine(replay_vector, stored_vector)

        base_common = {
            "reference_index": index,
            "group_id": group_id,
            "source_key_sha256": hashlib.sha256(
                source_key.encode("utf-8")
            ).hexdigest(),
            "source_sha256": str(raw.get("source_sha256") or ""),
            "timestamp_seconds": raw.get("timestamp_seconds"),
            "eye": str(raw.get("eye") or ""),
            "projection": str(source.get("projection") or ""),
            "stereo_layout": str(source.get("stereo_layout") or ""),
            "decode_mode": str(source.get("decode_mode") or ""),
            "frame_sha256": expected_frame_sha,
            "matched_viewport_id": viewport_id,
        }

        bank_row = {
            **base_common,
            "variant": "bank-original",
            "profile_cosine": round(_cosine(stored_vector, profile_vector), 9),
            "quality": replay_quality,
            "_embedding": stored_vector,
        }
        variants["bank-original"].append(bank_row)
        replay_row = {
            **base_common,
            "variant": "replay-grid-110",
            "profile_cosine": round(_cosine(replay_vector, profile_vector), 9),
            "replay_to_bank_cosine": round(replay_to_bank, 9),
            "quality": replay_quality,
            "_embedding": replay_vector,
        }
        variants["replay-grid-110"].append(replay_row)

        row = {
            **base_common,
            "replay_to_bank_cosine": round(replay_to_bank, 9),
            "current_quality": replay_quality,
            "current_profile_cosine": replay_row["profile_cosine"],
            "centered_variants": {},
        }

        sample_key = (
            source_key,
            None
            if raw.get("timestamp_seconds") is None
            else round(float(raw.get("timestamp_seconds")), 6),
            str(raw.get("eye") or ""),
        )
        by_source_sample_variant[sample_key]["bank-original"] = stored_vector
        by_source_sample_variant[sample_key]["replay-grid-110"] = replay_vector

        if spatial:
            if viewport is None:
                raise PhotorealIdentityRepresentationDiagnosticError(
                    "spatial bank reference lacks matched viewport metadata"
                )
            face_candidates = adapter._candidates(runtime, matched_image)
            if (
                len(face_candidates) != 1
                or face_candidates[0].get("face") is None
            ):
                raise PhotorealIdentityRepresentationDiagnosticError(
                    "spatial bank replay lost its accepted face"
                )
            face_box = adapter._face_bbox(face_candidates[0]["face"])
            if face_box is None:
                raise PhotorealIdentityRepresentationDiagnosticError(
                    "spatial bank replay face lacks bounding box"
                )
            face_yaw, face_pitch = _face_center_world_angles(
                viewport=viewport,
                bbox=face_box,
                image_width=matched_image.shape[1],
                image_height=matched_image.shape[0],
            )
            row["grid_viewport"] = {
                key: viewport[key]
                for key in (
                    "viewport_id",
                    "yaw_degrees",
                    "pitch_degrees",
                    "horizontal_fov_degrees",
                    "vertical_fov_degrees",
                )
            }
            row["estimated_face_center_world"] = {
                "yaw_degrees": face_yaw,
                "pitch_degrees": face_pitch,
            }
            authority = source.get("projection_authority")
            if not isinstance(authority, Mapping):
                raise PhotorealIdentityRepresentationDiagnosticError(
                    "spatial source lost projection authority"
                )
            for fov in FOV_SWEEP:
                variant_name = f"face-centered-{int(fov)}"
                centered = _centered_view(
                    adapter=adapter,
                    runtime=runtime,
                    eye_image=eye_image,
                    authority=authority,
                    yaw=face_yaw,
                    pitch=face_pitch,
                    fov=fov,
                )
                vector, quality = _single_face_measurement(
                    adapter=adapter,
                    runtime=runtime,
                    image=centered,
                )
                variant_public: dict[str, Any] = {
                    "status": quality["status"],
                    "quality": quality,
                }
                if vector is not None:
                    profile_cosine = _cosine(vector, profile_vector)
                    bank_cosine = _cosine(vector, stored_vector)
                    variant_public.update(
                        {
                            "profile_cosine": round(profile_cosine, 9),
                            "to_bank_reference_cosine": round(bank_cosine, 9),
                        }
                    )
                    variant_row = {
                        **base_common,
                        "variant": variant_name,
                        "profile_cosine": round(profile_cosine, 9),
                        "quality": quality,
                        "_embedding": vector,
                    }
                    variants[variant_name].append(variant_row)
                    by_source_sample_variant[sample_key][variant_name] = vector
                row["centered_variants"][variant_name] = variant_public

        per_reference.append(row)

    total_reference_count = len(references)
    aggregates = {
        name: _aggregate(rows, total_reference_count=total_reference_count)
        for name, rows in sorted(variants.items())
    }

    stereo_pairs: list[dict[str, Any]] = []
    timestamps: dict[tuple[str, float | None], dict[str, dict[str, list[float]]]] = defaultdict(dict)
    for (source_key, timestamp, eye), variant_map in by_source_sample_variant.items():
        timestamps[(source_key, timestamp)][eye] = variant_map
    for (source_key, timestamp), eyes in timestamps.items():
        if "left" not in eyes or "right" not in eyes:
            continue
        common_variants = sorted(set(eyes["left"]) & set(eyes["right"]))
        stereo_pairs.append(
            {
                "source_key_sha256": hashlib.sha256(
                    source_key.encode("utf-8")
                ).hexdigest(),
                "timestamp_seconds": timestamp,
                "variant_cosines": {
                    variant: round(
                        _cosine(
                            eyes["left"][variant],
                            eyes["right"][variant],
                        ),
                        9,
                    )
                    for variant in common_variants
                },
            }
        )

    diagnostic_revision = str(
        os.environ.get("BODYRIG_REVISION") or ""
    ).strip().lower()
    if (
        len(diagnostic_revision) != 40
        or any(
            character not in "0123456789abcdef"
            for character in diagnostic_revision
        )
    ):
        raise PhotorealIdentityRepresentationDiagnosticError(
            "BODYRIG_REVISION must bind diagnostic execution to exact Git HEAD"
        )

    result = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "diagnostic_bodyrig_revision": diagnostic_revision,
        "adapter_revision": adapter_revision,
        "model_set_sha256": str(bank.get("model_set_sha256") or ""),
        "identity_bank_sha256": bank_sha,
        "identity_bank_file_sha256": _sha256_file(bank_path),
        "identity_request_sha256": _sha256_file(request_origin_path),
        "identity_request_transport_sha256": _sha256_file(request_path),
        "identity_group_attestation_sha256": _sha256_file(
            review_root / "identity-group-attestation.json"
        ),
        "review_bodyrig_revision": attestation.get("review_bodyrig_revision"),
        "attestation_bodyrig_revision": attestation.get(
            "attestation_bodyrig_revision"
        ),
        "portrait_profile_sha256": profile_sha,
        "portrait_profile_file": str(profile_path),
        "reference_count": total_reference_count,
        "human_attested_group_count": len(
            attestation.get("accepted_group_ids") or []
        ),
        "fov_sweep_degrees": list(FOV_SWEEP),
        "variant_aggregates": aggregates,
        "stereo_pairs": stereo_pairs,
        "references": per_reference,
        "diagnostic_only": True,
        "identity_group_selection_authority": False,
        "identity_matching_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "format": FORMAT,
                "performer_id": performer_id,
                "reference_count": total_reference_count,
                "variant_aggregates": aggregates,
                "stereo_pair_count": len(stereo_pairs),
                "diagnostic_only": True,
                "production_activation": False,
                "output": str(output),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
