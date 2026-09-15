from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Keep heavy vision dependencies out of BodyRig core. The adapter loads them
# lazily only after request/model provenance has been verified.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bodyrig.photoreal_model_set import PhotorealModelSetError, build_model_set  # noqa: E402

ADAPTER_NAME = "bodyrig-reference-vision-v1"
MODEL_MANIFEST_FORMAT = "bodyrig-photoreal-reference-vision-models"
MODEL_MANIFEST_VERSION = 1
IDENTITY_REQUEST = "bodyrig-photoreal-identity-extractor-request"
CALIBRATION_REQUEST = "bodyrig-photoreal-identity-calibration-extractor-request"
FRAME_REQUEST = "bodyrig-photoreal-frame-analyzer-request"
SUPPORTED_REQUESTS = {IDENTITY_REQUEST, CALIBRATION_REQUEST, FRAME_REQUEST}


class ReferenceVisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelManifest:
    insightface_root: Path
    insightface_name: str
    mmpose_pose_config: Path
    mmpose_pose_weights: Path
    mmdet_config: Path
    mmdet_weights: Path
    identity_embedding_dimension: int


@dataclass
class Runtime:
    cv2: Any
    np: Any
    face_app: Any
    pose_inferencer: Any
    embedding_dimension: int


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReferenceVisionError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ReferenceVisionError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise ReferenceVisionError(f"{label} is invalid")
    return result


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise ReferenceVisionError(f"{label} is invalid")
    return result


def _self_revision() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _safe_model_path(root: Path, raw: Any, *, label: str, directory: bool = False) -> Path:
    relative = Path(_text(raw, label=label))
    if relative.is_absolute() or ".." in relative.parts:
        raise ReferenceVisionError(f"{label} must be a relative path inside model root")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReferenceVisionError(f"{label} escapes model root") from exc
    exists = resolved.is_dir() if directory else resolved.is_file()
    if not exists:
        raise ReferenceVisionError(f"{label} not found: {resolved}")
    return resolved


def _load_model_manifest(root: Path) -> ModelManifest:
    path = root / "bodyrig-reference-vision-v1.json"
    value = _read_json(path, label="reference vision model manifest")
    required = {
        "format",
        "version",
        "insightface_root",
        "insightface_name",
        "mmpose_pose_config",
        "mmpose_pose_weights",
        "mmdet_config",
        "mmdet_weights",
        "identity_embedding_dimension",
    }
    if set(value) != required:
        raise ReferenceVisionError("reference vision model manifest fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != MODEL_MANIFEST_FORMAT or isinstance(version, bool) or version != MODEL_MANIFEST_VERSION:
        raise ReferenceVisionError("reference vision model manifest format/version mismatch")
    dimension = value.get("identity_embedding_dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or not 32 <= dimension <= 4096:
        raise ReferenceVisionError("identity_embedding_dimension is invalid")
    return ModelManifest(
        insightface_root=_safe_model_path(root, value["insightface_root"], label="insightface_root", directory=True),
        insightface_name=_text(value["insightface_name"], label="insightface_name", maximum=128),
        mmpose_pose_config=_safe_model_path(root, value["mmpose_pose_config"], label="mmpose_pose_config"),
        mmpose_pose_weights=_safe_model_path(root, value["mmpose_pose_weights"], label="mmpose_pose_weights"),
        mmdet_config=_safe_model_path(root, value["mmdet_config"], label="mmdet_config"),
        mmdet_weights=_safe_model_path(root, value["mmdet_weights"], label="mmdet_weights"),
        identity_embedding_dimension=dimension,
    )


def _verify_provenance(args: argparse.Namespace, request: Mapping[str, Any], model_root: Path) -> ModelManifest:
    request_format = request.get("format")
    if request_format not in SUPPORTED_REQUESTS or request.get("version") != 1:
        raise ReferenceVisionError(f"unsupported BodyRig request format/version: {request_format!r}")
    if args.bodyrig_adapter != ADAPTER_NAME:
        raise ReferenceVisionError("adapter identity mismatch")
    revision = _self_revision()
    if args.bodyrig_revision != revision:
        raise ReferenceVisionError("adapter revision does not match exact adapter bytes")
    request_revision = _text(request.get("revision"), label="request revision", maximum=160)
    if request_revision != revision:
        raise ReferenceVisionError("request targets different adapter revision")
    expected_model_sha = _sha(args.bodyrig_model_set_sha256, label="CLI model-set SHA-256")
    request_model_sha = _sha(request.get("model_set_sha256"), label="request model-set SHA-256")
    if expected_model_sha != request_model_sha:
        raise ReferenceVisionError("request/CLI model-set provenance mismatch")
    try:
        observed_model_set = build_model_set(model_root)
    except PhotorealModelSetError as exc:
        raise ReferenceVisionError(str(exc)) from exc
    if observed_model_set["model_set_sha256"] != expected_model_sha:
        raise ReferenceVisionError("model root bytes do not match pinned model-set SHA-256")
    return _load_model_manifest(model_root)


def _load_runtime(manifest: ModelManifest, *, device: str) -> Runtime:
    try:
        import cv2
        import numpy as np
        from insightface.app import FaceAnalysis
        from mmpose.apis import MMPoseInferencer
    except Exception as exc:  # noqa: BLE001 - dependency preflight must be explicit
        raise ReferenceVisionError(
            "reference vision dependencies are unavailable; require opencv-python, numpy, insightface, onnxruntime and mmpose/mmdet"
        ) from exc

    normalized_device = device.strip().lower()
    if normalized_device not in {"cpu", "cuda", "cuda:0"}:
        raise ReferenceVisionError("--device must be cpu, cuda or cuda:0")
    use_cuda = normalized_device != "cpu"
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if use_cuda else ["CPUExecutionProvider"]
    ctx_id = 0 if use_cuda else -1
    try:
        face_app = FaceAnalysis(
            name=manifest.insightface_name,
            root=str(manifest.insightface_root),
            providers=providers,
        )
        face_app.prepare(ctx_id=ctx_id, det_size=(640, 640))
        pose_inferencer = MMPoseInferencer(
            pose2d=str(manifest.mmpose_pose_config),
            pose2d_weights=str(manifest.mmpose_pose_weights),
            det_model=str(manifest.mmdet_config),
            det_weights=str(manifest.mmdet_weights),
            device="cuda:0" if use_cuda else "cpu",
            show_progress=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise ReferenceVisionError(f"reference vision model initialization failed: {exc}") from exc
    return Runtime(cv2=cv2, np=np, face_app=face_app, pose_inferencer=pose_inferencer, embedding_dimension=manifest.identity_embedding_dimension)


def _frame_sha(image: Any) -> str:
    shape = "x".join(str(int(value)) for value in image.shape)
    digest = hashlib.sha256()
    digest.update((shape + "\n").encode("ascii"))
    digest.update(memoryview(image).cast("B"))
    return digest.hexdigest()


def _perceptual_hash(runtime: Runtime, image: Any) -> str:
    gray = runtime.cv2.cvtColor(image, runtime.cv2.COLOR_BGR2GRAY)
    resized = runtime.cv2.resize(gray, (32, 32), interpolation=runtime.cv2.INTER_AREA).astype(runtime.np.float32)
    dct = runtime.cv2.dct(resized)
    low = dct[:8, :8].copy()
    values = low.flatten()
    median = float(runtime.np.median(values[1:]))
    bits = 0
    for index, value in enumerate(values):
        if float(value) >= median:
            bits |= 1 << index
    return f"{bits:016x}"[-16:]


def _sharpness(runtime: Runtime, image: Any) -> float:
    gray = runtime.cv2.cvtColor(image, runtime.cv2.COLOR_BGR2GRAY)
    variance = float(runtime.cv2.Laplacian(gray, runtime.cv2.CV_64F).var())
    return round(max(0.0, min(1.0, 1.0 - math.exp(-variance / 400.0))), 6)


def _read_sample(runtime: Runtime, source: Mapping[str, Any], sample: Mapping[str, Any]) -> tuple[Any, bool]:
    path = Path(_text(source.get("resolved_path"), label="resolved source path", maximum=32768))
    kind = _text(source.get("kind"), label="source kind", maximum=16)
    if kind == "image":
        image = runtime.cv2.imread(str(path), runtime.cv2.IMREAD_COLOR)
        if image is None:
            raise ReferenceVisionError(f"could not decode image: {path}")
    elif kind == "video":
        timestamp = sample.get("timestamp_seconds")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or float(timestamp) < 0:
            raise ReferenceVisionError("video sample timestamp is invalid")
        capture = runtime.cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise ReferenceVisionError(f"could not open video: {path}")
            capture.set(runtime.cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000.0)
            ok, image = capture.read()
            if not ok or image is None:
                raise ReferenceVisionError(f"could not decode video frame at {timestamp}s: {path}")
        finally:
            capture.release()
    else:
        raise ReferenceVisionError(f"unsupported source kind: {kind}")

    eye = _text(sample.get("eye"), label="sample eye", maximum=16)
    stereo_layout = str(source.get("stereo_layout") or "mono")
    height, width = image.shape[:2]
    if stereo_layout == "side-by-side":
        midpoint = width // 2
        if midpoint < 1:
            raise ReferenceVisionError("side-by-side frame is too narrow")
        image = image[:, :midpoint] if eye == "left" else image[:, midpoint:] if eye == "right" else None
    elif stereo_layout == "over-under":
        midpoint = height // 2
        if midpoint < 1:
            raise ReferenceVisionError("over-under frame is too short")
        image = image[:midpoint, :] if eye == "left" else image[midpoint:, :] if eye == "right" else None
    elif stereo_layout == "mono":
        if eye != "mono":
            raise ReferenceVisionError("mono source requested non-mono eye")
    else:
        raise ReferenceVisionError(f"unsupported stereo layout: {stereo_layout}")
    if image is None or image.size == 0:
        raise ReferenceVisionError("stereo eye split produced an empty frame")
    spatial = str(source.get("decode_mode") or "") == "spatial-deprojection-required"
    return runtime.np.ascontiguousarray(image), spatial


def _faces(runtime: Runtime, image: Any) -> list[Any]:
    try:
        return list(runtime.face_app.get(image))
    except Exception as exc:  # noqa: BLE001
        raise ReferenceVisionError(f"InsightFace inference failed: {exc}") from exc


def _flatten_pose_predictions(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return []
    predictions = value.get("predictions")
    if not isinstance(predictions, list):
        return []
    if len(predictions) == 1 and isinstance(predictions[0], list):
        predictions = predictions[0]
    return [item for item in predictions if isinstance(item, Mapping)]


def _pose_predictions(runtime: Runtime, image: Any) -> list[Mapping[str, Any]]:
    try:
        generator = runtime.pose_inferencer(image, return_vis=False, draw_bbox=False)
        result = next(generator)
    except StopIteration:
        return []
    except Exception as exc:  # noqa: BLE001
        raise ReferenceVisionError(f“MMPose inference failed: {exc}") from exc
    return _flatten_pose_predictions(result)


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        raw = list(value)
        if len(raw) == 1 and isinstance(raw[0], Sequence):
            raw = list(raw[0])
        if len(raw) >= 4:
            try:
                x1, y1, x2, y2 = (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
            except (TypeError, ValueError):
                return None
            if all(math.isfinite(item) for item in (x1, y1, x2, y2)) and x2 > x1 and y2 > y1:
                return x1, y1, x2, y2
    return None


def _pose_bbox(prediction: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    return _bbox(prediction.get("bbox")) or _bbox(prediction.get("bboxes"))


def _face_bbox(face: Any) -> tuple[float, float, float, float] | None:
    return _bbox(getattr(face, "bbox", None))


def _bbox_area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = _bbox_area(left) + _bbox_area(right) - intersection
    return 0.0 if union <= 0 else intersection / union


def _face_center_inside(face_box: tuple[float, float, float, float], person_box: tuple[float, float, float, float]) -> bool:
    x = (face_box[0] + face_box[2]) * 0.5
    y = (face_box[1] + face_box[3]) * 0.5
    return person_box[0] <= x <= person_box[2] and person_box[1] <= y <= person_box[3]


def _normalize_embedding(face: Any, dimension: int) -> list[float] | None:
    raw = getattr(face, "embedding", None)
    if raw is None:
        return None
    values = [float(item) for item in raw]
    if len(values) != dimension or any(not math.isfinite(item) for item in values):
        raise ReferenceVisionError("InsightFace embedding dimension/provenance mismatch")
    norm = math.sqrt(sum(item * item for item in values))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise ReferenceVisionError("InsightFace embedding norm is invalid")
    return [item / norm for item in values]


def _face_view_bin(face: Any) -> str:
    pose = getattr(face, "pose", None)
    if pose is None or len(pose) < 2:
        return "unknown"
    try:
        yaw = float(pose[1])
    except (TypeError, ValueError):
        return "unknown"
    if not math.isfinite(yaw):
        return "unknown"
    magnitude = abs(yaw)
    if magnitude <= 20.0:
        return "front"
    if magnitude <= 55.0:
        return "three-quarter-right" if yaw > 0 else "three-quarter-left"
    if magnitude <= 110.0:
        return "profile-right" if yaw > 0 else "profile-left"
    return "unknown"


def _body_visibility(prediction: Mapping[str, Any], *, width: int, height: int) -> float:
    keypoints = prediction.get("keypoints")
    scores = prediction.get("keypoint_scores")
    if not isinstance(keypoints, Sequence) or isinstance(keypoints, (str, bytes)):
        return 0.0
    points = list(keypoints)
    if len(points) == 1 and isinstance(points[0], Sequence) and len(points[0]) > 17:
        points = list(points[0])
    score_values: list[Any] = []
    if isinstance(scores, Sequence) and not isinstance(scores, (str, bytes)):
        score_values = list(scores)
        if len(score_values) == 1 and isinstance(score_values[0], Sequence):
            score_values = list(score_values[0])
    total = min(17, len(points))
    if total < 5:
        return 0.0
    visible = 0
    for index in range(total):
        point = points[index]
        if not isinstance(point, Sequence) or len(point) < 2:
            continue
        try:
            x, y = float(point[0]), float(point[1])
            score = float(score_values[index]) if index < len(score_values) else 1.0
        except (TypeError, ValueError):
            continue
        if score >= 0.30 and 0 <= x < width and 0 <= y < height:
            visible += 1
    return round(visible / total, 6)


def _face_visibility(face: Any, *, width: int, height: int) -> float:
    box = _face_bbox(face)
    if box is None:
        return 0.0
    score = float(getattr(face, "det_score", 1.0) or 0.0)
    x1, y1, x2, y2 = box
    inside = max(0.0, min(x2, width) - max(x1, 0.0)) * max(0.0, min(y2, height) - max(y1, 0.0))
    area = _bbox_area(box)
    containment = 0.0 if area <= 0 else inside / area
    return round(max(0.0, min(1.0, score * containment)), 6)


def _crop(image: Any, box: tuple[float, float, float, float]) -> Any:
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, int(math.floor(box[0]))))
    y1 = max(0, min(height - 1, int(math.floor(box[1]))))
    x2 = max(x1 + 1, min(width, int(math.ceil(box[2]))))
    y2 = max(y1 + 1, min(height, int(math.ceil(box[3]))))
    return image[y1:y2, x1:x2]


def _person_candidates(runtime: Runtime, image: Any, faces: list[Any]) -> list[dict[str, Any]]:
    height, width = image.shape[:2]
    predictions = _pose_predictions(runtime, image)
    candidates: list[dict[str, Any]] = []
    for prediction in predictions:
        box = _pose_bbox(prediction)
        if box is None:
            continue
        candidates.append({"bbox": box, "pose": prediction, "face": None})

    unmatched_faces = list(faces)
    for candidate in candidates:
        box = candidate["bbox"]
        matches = [face for face in unmatched_faces if (_face_bbox(face) is not None and _face_center_inside(_face_bbox(face), box))]
        if matches:
            matches.sort(key=lambda face: float(getattr(face, "det_score", 0.0) or 0.0), reverse=True)
            chosen = matches[0]
            candidate["face"] = chosen
            unmatched_faces.remove(chosen)

    for face in unmatched_faces:
        box = _face_bbox(face)
        if box is None:
            continue
        x1, y1, x2, y2 = box
        face_height = y2 - y1
        face_width = x2 - x1
        expanded = (
            max(0.0, x1 - 1.2 * face_width),
            max(0.0, y1 - 0.4 * face_height),
            min(float(width), x2 + 1.2 * face_width),
            min(float(height), y2 + 4.5 * face_height),
        )
        candidates.append({"bbox": expanded, "pose": None, "face": face})

    candidates.sort(key=lambda item: ((item["bbox"][0] + item["bbox"][2]) * 0.5, (item["bbox"][1] + item["bbox"][3]) * 0.5))
    return candidates


def _candidate_observations(runtime: Runtime, image: Any, *, base: Mapping[str, Any]) -> list[dict[str, Any]]:
    faces = _faces(runtime, image)
    candidates = _person_candidates(runtime, image, faces)
    height, width = image.shape[:2]
    frame_sha = _frame_sha(image)
    phash = _perceptual_hash(runtime, image)
    if not candidates:
        return [
            {
                **base,
                "frame_sha256": frame_sha,
                "perceptual_hash": phash,
                "candidate_id": "none-0",
                "person_detected": False,
                "width": width,
                "height": height,
                "view_bin": "unknown",
                "face_visibility": 0.0,
                "full_body_visibility": 0.0,
                "person_fraction": 0.0,
                "sharpness": _sharpness(runtime, image),
                "motion": 0.0,
                "occlusion": 0.0,
                "identity_measurement_status": "unavailable",
                "identity_embedding": None,
            }
        ]

    result: list[dict[str, Any]] = []
    boxes = [item["bbox"] for item in candidates]
    for index, candidate in enumerate(candidates):
        box = candidate["bbox"]
        face = candidate["face"]
        pose = candidate["pose"]
        embedding = None if face is None else _normalize_embedding(face, runtime.embedding_dimension)
        overlaps = [_iou(box, other) for other_index, other in enumerate(boxes) if other_index != index]
        crop = _crop(image, box)
        result.append(
            {
                **base,
                "frame_sha256": frame_sha,
                "perceptual_hash": phash,
                "candidate_id": f"person-{index:03d}",
                "person_detected": True,
                "width": width,
                "height": height,
                "view_bin": "unknown" if face is None else _face_view_bin(face),
                "face_visibility": 0.0 if face is None else _face_visibility(face, width=width, height=height),
                "full_body_visibility": 0.0 if pose is None else _body_visibility(pose, width=width, height=height),
                "person_fraction": round(max(0.0, min(1.0, _bbox_area(box) / max(1.0, width * height))), 6),
                "sharpness": _sharpness(runtime, crop),
                "motion": 0.0,
                "occlusion": round(max(overlaps, default=0.0), 6),
                "identity_measurement_status": "available" if embedding is not None else "unavailable",
                "identity_embedding": embedding,
            }
        )
    return result


def _iter_source_samples(sources: Iterable[Mapping[str, Any]], sample_field: str) -> Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    for source in sources:
        samples = source.get(sample_field)
        if not isinstance(samples, list):
            raise ReferenceVisionError(f"source {source.get('source_key')} has no {sample_field}")
        for sample in samples:
            if not isinstance(sample, Mapping):
                raise ReferenceVisionError("sample is not an object")
            yield source, sample


def _exactly_one_person_embedding(runtime: Runtime, source: Mapping[str, Any], sample: Mapping[str, Any]) -> tuple[str, list[float]] | None:
    image, spatial = _read_sample(runtime, source, sample)
    if spatial:
        raise ReferenceVisionError("spatial source cannot establish identity authority before projection-specific deprojection")
    candidates = _person_candidates(runtime, image, _faces(runtime, image))
    if len(candidates) != 1:
        return None
    face = candidates[0]["face"]
    if face is None:
        return None
    embedding = _normalize_embedding(face, runtime.embedding_dimension)
    if embedding is None:
        return None
    return _frame_sha(image), embedding


def _identity_result(runtime: Runtime, request: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for source, sample in _iter_source_samples(request["sources"], "reference_samples"):
        measured = _exactly_one_person_embedding(runtime, source, sample)
        if measured is None:
            continue
        frame_sha, embedding = measured
        observations.append(
            {
                "source_key": source["source_key"],
                "source_sha256": source["source_sha256"],
                "timestamp_seconds": sample.get("timestamp_seconds"),
                "eye": sample["eye"],
                "frame_sha256": frame_sha,
                "embedding": embedding,
            }
        )
    if not observations:
        raise ReferenceVisionError("identity extractor found no unambiguous single-person reference observations")
    return {
        "format": "bodyrig-photoreal-identity-reference-observations",
        "version": 1,
        "performer_id": request["performer_id"],
        "extractor": args.bodyrig_adapter,
        "extractor_revision": args.bodyrig_revision,
        "model_set_sha256": args.bodyrig_model_set_sha256,
        "embedding_dimension": runtime.embedding_dimension,
        "observations": observations,
        "build_only": True,
        "production_activation": False,
    }


def _calibration_result(runtime: Runtime, request: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for source, sample in _iter_source_samples(request["sources"], "samples"):
        measured = _exactly_one_person_embedding(runtime, source, sample)
        if measured is None:
            continue
        frame_sha, embedding = measured
        observations.append(
            {
                "source_key": source["source_key"],
                "source_sha256": source["source_sha256"],
                "subject_performer_id": source["subject_performer_id"],
                "timestamp_seconds": sample.get("timestamp_seconds"),
                "eye": sample["eye"],
                "frame_sha256": frame_sha,
                "embedding": embedding,
            }
        )
    if not observations:
        raise ReferenceVisionError("calibration extractor found no unambiguous non-target observations")
    return {
        "format": "bodyrig-photoreal-identity-negative-observations",
        "version": 1,
        "target_performer_id": request["target_performer_id"],
        "identity_bank_sha256": request["identity_bank_sha256"],
        "extractor": args.bodyrig_adapter,
        "extractor_revision": args.bodyrig_revision,
        "model_set_sha256": args.bodyrig_model_set_sha256,
        "embedding_dimension": runtime.embedding_dimension,
        "observations": observations,
        "calibration_only": True,
        "build_only": True,
        "production_activation": False,
    }


def _frame_result(runtime: Runtime, request: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for source, sample in _iter_source_samples(request["sources"], "samples"):
        image, spatial = _read_sample(runtime, source, sample)
        base = {
            "source_key": source["source_key"],
            "source_sha256": source["source_sha256"],
            "kind": source["kind"],
            "timestamp_seconds": sample.get("timestamp_seconds"),
            "eye": sample["eye"],
            "projection": source["projection"],
        }
        if spatial:
            height, width = image.shape[:2]
            observations.append(
                {
                    **base,
                    "frame_sha256": _frame_sha(image),
                    "perceptual_hash": _perceptual_hash(runtime, image),
                    "candidate_id": "none-0",
                    "person_detected": False,
                    "width": width,
                    "height": height,
                    "view_bin": "unknown",
                    "face_visibility": 0.0,
                    "full_body_visibility": 0.0,
                    "person_fraction": 0.0,
                    "sharpness": _sharpness(runtime, image),
                    "motion": 0.0,
                    "occlusion": 0.0,
                    "identity_measurement_status": "unavailable",
                    "identity_embedding": None,
                }
            )
            continue
        observations.extend(_candidate_observations(runtime, image, base=base))
    if not observations:
        raise ReferenceVisionError("frame analyzer produced no observations")
    return {
        "format": "bodyrig-photoreal-frame-observations",
        "version": 1,
        "performer_id": request["performer_id"],
        "analyzer": args.bodyrig_adapter,
        "analyzer_revision": args.bodyrig_revision,
        "analyzer_model_set_sha256": args.bodyrig_model_set_sha256,
        "identity_embedding_dimension": runtime.embedding_dimension,
        "observations": observations,
        "build_only": True,
        "production_activation": False,
    }


def _write_result(request_format: str, result: Mapping[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    name = {
        IDENTITY_REQUEST: "identity-observations.json",
        CALIBRATION_REQUEST: "negative-observations.json",
        FRAME_REQUEST: "observations.json",
    }[request_format]
    (output / name).write_text(
        json.dumps(dict(result), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BodyRig Photoreal V2 reference measurement adapter")
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--bodyrig-request", type=Path, required=True)
    parser.add_argument("--bodyrig-output", type=Path, required=True)
    parser.add_argument("--bodyrig-adapter", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--bodyrig-model-set-sha256", required=True)
    parser.add_argument("--bodyrig-identity-bank-sha256", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        model_root = args.model_root.expanduser().resolve()
        request = _read_json(args.bodyrig_request.expanduser().resolve(), label="BodyRig adapter request")
        manifest = _verify_provenance(args, request, model_root)
        runtime = _load_runtime(manifest, device=args.device)
        if request["format"] == IDENTITY_REQUEST:
            result = _identity_result(runtime, request, args)
        elif request["format"] == CALIBRATION_REQUEST:
            supplied_bank = _sha(args.bodyrig_identity_bank_sha256, label="CLI identity bank SHA-256")
            if supplied_bank != _sha(request.get("identity_bank_sha256"), label="request identity bank SHA-256"):
                raise ReferenceVisionError("request/CLI identity bank provenance mismatch")
            result = _calibration_result(runtime, request, args)
        elif request["format"] == FRAME_REQUEST:
            result = _frame_result(runtime, request, args)
        else:  # pragma: no cover - verified above
            raise ReferenceVisionError("unsupported request")
        _write_result(request["format"], result, args.bodyrig_output.expanduser().resolve())
    except ReferenceVisionError as exc:
        print(f"BodyRig reference vision adapter: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
