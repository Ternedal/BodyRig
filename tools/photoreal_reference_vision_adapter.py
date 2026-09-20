from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bodyrig.photoreal_equirectangular_deprojection import (  # noqa: E402
    PhotorealEquirectangularDeprojectionError,
    deproject_equirectangular_views,
)
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


class ReferenceVisionDecodeError(ReferenceVisionError):
    """A source/sample could not be decoded, without weakening structural authority."""
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


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise ReferenceVisionError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ReferenceVisionError(f"{label} is invalid")
    return result


def _self_revision() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _listish(value: Any) -> list[Any] | None:
    if value is None or isinstance(value, (str, bytes)):
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        return list(value)
    return None


def _safe_model_path(root: Path, raw: Any, *, label: str, directory: bool = False) -> Path:
    relative = Path(_text(raw, label=label))
    if relative.is_absolute() or ".." in relative.parts:
        raise ReferenceVisionError(f"{label} must remain inside model root")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReferenceVisionError(f"{label} escapes model root") from exc
    valid = resolved.is_dir() if directory else resolved.is_file()
    if not valid:
        raise ReferenceVisionError(f"{label} not found: {resolved}")
    return resolved


def _load_model_manifest(root: Path) -> ModelManifest:
    value = _read_json(root / "bodyrig-reference-vision-v1.json", label="reference vision model manifest")
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
    if value.get("format") != MODEL_MANIFEST_FORMAT or isinstance(version, bool) or version != 1:
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
    version = request.get("version")
    if request_format not in SUPPORTED_REQUESTS or isinstance(version, bool) or version != 1:
        raise ReferenceVisionError("unsupported BodyRig request format/version")
    if args.bodyrig_adapter != ADAPTER_NAME:
        raise ReferenceVisionError("adapter identity mismatch")
    revision = _self_revision()
    if args.bodyrig_revision != revision or request.get("revision") != revision:
        raise ReferenceVisionError("adapter revision does not match exact adapter bytes")
    expected_sha = _sha(args.bodyrig_model_set_sha256, label="CLI model-set SHA-256")
    if _sha(request.get("model_set_sha256"), label="request model-set SHA-256") != expected_sha:
        raise ReferenceVisionError("request/CLI model-set provenance mismatch")
    try:
        observed = build_model_set(model_root)
    except PhotorealModelSetError as exc:
        raise ReferenceVisionError(str(exc)) from exc
    if observed["model_set_sha256"] != expected_sha:
        raise ReferenceVisionError("model root bytes do not match pinned model-set SHA-256")
    return _load_model_manifest(model_root)


def _load_runtime(manifest: ModelManifest, *, device: str) -> Runtime:
    try:
        import cv2
        import numpy as np
        from insightface.app import FaceAnalysis
        from mmpose.apis import MMPoseInferencer
    except Exception as exc:  # noqa: BLE001
        raise ReferenceVisionError(
            "reference vision dependencies are unavailable; require OpenCV, NumPy, InsightFace/ONNX Runtime and MMPose/MMDetection"
        ) from exc

    normalized = device.strip().lower()
    if normalized not in {"cpu", "cuda", "cuda:0"}:
        raise ReferenceVisionError("--device must be cpu, cuda or cuda:0")
    use_cuda = normalized != "cpu"
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if use_cuda else ["CPUExecutionProvider"]
    try:
        face_app = FaceAnalysis(name=manifest.insightface_name, root=str(manifest.insightface_root), providers=providers)
        face_app.prepare(ctx_id=0 if use_cuda else -1, det_size=(640, 640))
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
    return Runtime(cv2, np, face_app, pose_inferencer, manifest.identity_embedding_dimension)


def _frame_sha(image: Any) -> str:
    contiguous = image if getattr(image, "flags", None) is not None and image.flags.c_contiguous else image.copy(order="C")
    digest = hashlib.sha256()
    digest.update(("x".join(str(int(value)) for value in contiguous.shape) + "\n").encode("ascii"))
    digest.update(contiguous.tobytes(order="C"))
    return digest.hexdigest()


def _perceptual_hash(runtime: Runtime, image: Any) -> str:
    gray = runtime.cv2.cvtColor(image, runtime.cv2.COLOR_BGR2GRAY)
    resized = runtime.cv2.resize(gray, (32, 32), interpolation=runtime.cv2.INTER_AREA).astype(runtime.np.float32)
    low = runtime.cv2.dct(resized)[:8, :8].flatten()
    median = float(runtime.np.median(low[1:]))
    bits = 0
    for index, value in enumerate(low):
        if float(value) >= median:
            bits |= 1 << index
    return f"{bits:016x}"[-16:]


def _sharpness(runtime: Runtime, image: Any) -> float:
    gray = runtime.cv2.cvtColor(image, runtime.cv2.COLOR_BGR2GRAY)
    variance = float(runtime.cv2.Laplacian(gray, runtime.cv2.CV_64F).var())
    return round(max(0.0, min(1.0, 1.0 - math.exp(-variance / 400.0))), 6)


def _decode_video_frame_ffmpeg(runtime: Runtime, path: Path, timestamp: float) -> Any:
    """Decode one video sample through the system ffmpeg as an OpenCV fallback."""

    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{timestamp:.6f}",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReferenceVisionDecodeError(f"ffmpeg fallback could not run: {exc}") from exc
    if completed.returncode != 0 or not completed.stdout:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[-1000:]
        raise ReferenceVisionDecodeError(
            f"ffmpeg fallback failed with exit code {completed.returncode}: {detail or 'no diagnostic output'}"
        )
    encoded = runtime.np.frombuffer(completed.stdout, dtype=runtime.np.uint8)
    try:
        image = runtime.cv2.imdecode(encoded, runtime.cv2.IMREAD_COLOR)
    except Exception as exc:  # noqa: BLE001
        cv_error = getattr(runtime.cv2, "error", None)
        if cv_error is None or not isinstance(exc, cv_error):
            raise
        raise ReferenceVisionDecodeError(f"ffmpeg fallback image decode raised {type(exc).__name__}: {exc}") from exc
    if image is None:
        raise ReferenceVisionDecodeError("ffmpeg fallback returned an undecodable image")
    return image


def _read_sample(runtime: Runtime, source: Mapping[str, Any], sample: Mapping[str, Any]) -> tuple[Any, bool]:
    path = Path(_text(source.get("resolved_path"), label="resolved source path", maximum=32768))
    kind = _text(source.get("kind"), label="source kind", maximum=16)
    if kind == "image":
        image = runtime.cv2.imread(str(path), runtime.cv2.IMREAD_COLOR)
        if image is None:
            raise ReferenceVisionDecodeError(f"could not decode image: {path}")
    elif kind == "video":
        timestamp = sample.get("timestamp_seconds")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or float(timestamp) < 0:
            raise ReferenceVisionError("video sample timestamp is invalid")
        timestamp_value = float(timestamp)
        image = None
        opencv_failure = None
        capture = None
        try:
            capture = runtime.cv2.VideoCapture(str(path))
            if not capture.isOpened():
                opencv_failure = "VideoCapture could not open the source"
            else:
                capture.set(runtime.cv2.CAP_PROP_POS_MSEC, timestamp_value * 1000.0)
                try:
                    ok, image = capture.read()
                except Exception as exc:  # noqa: BLE001
                    cv_error = getattr(runtime.cv2, "error", None)
                    if cv_error is None or not isinstance(exc, cv_error):
                        raise
                    opencv_failure = f"VideoCapture.read raised {type(exc).__name__}: {exc}"
                else:
                    if not ok or image is None:
                        opencv_failure = "VideoCapture.read returned no frame"
        finally:
            if capture is not None:
                capture.release()

        if image is None:
            try:
                image = _decode_video_frame_ffmpeg(runtime, path, timestamp_value)
            except ReferenceVisionDecodeError as exc:
                source_key = str(source.get("source_key") or "").strip() or "<unknown>"
                detail = opencv_failure or "OpenCV decoder produced no frame"
                raise ReferenceVisionDecodeError(
                    f"could not decode video sample source={source_key} timestamp={timestamp_value:.6f}s; "
                    f"opencv={detail}; ffmpeg={exc}"
                ) from exc
    else:
        raise ReferenceVisionError(f"unsupported source kind: {kind}")

    eye = _text(sample.get("eye"), label="sample eye", maximum=16)
    layout = str(source.get("stereo_layout") or "mono")
    height, width = image.shape[:2]
    if layout == "side-by-side":
        midpoint = width // 2
        if midpoint < 1 or eye not in {"left", "right"}:
            raise ReferenceVisionError("invalid side-by-side sample")
        image = image[:, :midpoint] if eye == "left" else image[:, midpoint:]
    elif layout == "over-under":
        midpoint = height // 2
        if midpoint < 1 or eye not in {"left", "right"}:
            raise ReferenceVisionError("invalid over-under sample")
        image = image[:midpoint, :] if eye == "left" else image[midpoint:, :]
    elif layout == "mono":
        if eye != "mono":
            raise ReferenceVisionError("mono source requested non-mono eye")
    else:
        raise ReferenceVisionError(f"unsupported stereo layout: {layout}")
    if image.size == 0:
        raise ReferenceVisionDecodeError("decoded frame is empty")
    return runtime.np.ascontiguousarray(image), str(source.get("decode_mode") or "") == "spatial-deprojection-required"


def _faces(runtime: Runtime, image: Any) -> list[Any]:
    try:
        return list(runtime.face_app.get(image))
    except Exception as exc:  # noqa: BLE001
        raise ReferenceVisionError(f"InsightFace inference failed: {exc}") from exc


def _pose_predictions(runtime: Runtime, image: Any) -> list[Mapping[str, Any]]:
    try:
        result = next(runtime.pose_inferencer(image, return_vis=False, draw_bbox=False))
    except StopIteration:
        return []
    except Exception as exc:  # noqa: BLE001
        raise ReferenceVisionError(f"MMPose inference failed: {exc}") from exc
    if not isinstance(result, Mapping):
        return []
    predictions = result.get("predictions")
    if not isinstance(predictions, list):
        return []
    if len(predictions) == 1 and isinstance(predictions[0], list):
        predictions = predictions[0]
    return [item for item in predictions if isinstance(item, Mapping)]


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    raw = _listish(value)
    if raw is None:
        return None
    if len(raw) == 1:
        nested = _listish(raw[0])
        if nested is not None:
            raw = nested
    if len(raw) < 4:
        return None
    try:
        box = tuple(float(raw[index]) for index in range(4))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in box) or box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def _pose_bbox(prediction: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    return _bbox(prediction.get("bbox")) or _bbox(prediction.get("bboxes"))


def _face_bbox(face: Any) -> tuple[float, float, float, float] | None:
    return _bbox(getattr(face, "bbox", None))


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    intersection = max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0.0, min(left[3], right[3]) - max(left[1], right[1])
    )
    union = _area(left) + _area(right) - intersection
    return 0.0 if union <= 0 else intersection / union


def _face_center_inside(face_box: tuple[float, float, float, float], person_box: tuple[float, float, float, float]) -> bool:
    x = (face_box[0] + face_box[2]) * 0.5
    y = (face_box[1] + face_box[3]) * 0.5
    return person_box[0] <= x <= person_box[2] and person_box[1] <= y <= person_box[3]


def _embedding(face: Any, dimension: int) -> list[float] | None:
    raw = _listish(getattr(face, "embedding", None))
    if raw is None:
        return None
    values = [float(item) for item in raw]
    if len(values) != dimension or any(not math.isfinite(item) for item in values):
        raise ReferenceVisionError("InsightFace embedding dimension/provenance mismatch")
    norm = math.sqrt(sum(item * item for item in values))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise ReferenceVisionError("InsightFace embedding norm is invalid")
    return [item / norm for item in values]


def _view_bin(face: Any) -> str:
    pose = _listish(getattr(face, "pose", None))
    if pose is None or len(pose) < 2:
        return "unknown"
    try:
        yaw = float(pose[1])
    except (TypeError, ValueError):
        return "unknown"
    if not math.isfinite(yaw):
        return "unknown"
    magnitude = abs(yaw)
    if magnitude <= 20:
        return "front"
    if magnitude <= 55:
        return "three-quarter-right" if yaw > 0 else "three-quarter-left"
    if magnitude <= 110:
        return "profile-right" if yaw > 0 else "profile-left"
    return "unknown"


def _body_visibility(prediction: Mapping[str, Any], *, width: int, height: int) -> float:
    points = _listish(prediction.get("keypoints"))
    scores = _listish(prediction.get("keypoint_scores")) or []
    if points is None:
        return 0.0
    if len(points) == 1:
        nested = _listish(points[0])
        if nested is not None:
            points = nested
    if len(scores) == 1:
        nested_scores = _listish(scores[0])
        if nested_scores is not None:
            scores = nested_scores
    total = min(17, len(points))
    if total < 5:
        return 0.0
    visible = 0
    for index in range(total):
        point = _listish(points[index])
        if point is None or len(point) < 2:
            continue
        try:
            x, y = float(point[0]), float(point[1])
            score = float(scores[index]) if index < len(scores) else 1.0
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
    inside = max(0.0, min(box[2], width) - max(box[0], 0.0)) * max(0.0, min(box[3], height) - max(box[1], 0.0))
    containment = 0.0 if _area(box) <= 0 else inside / _area(box)
    return round(max(0.0, min(1.0, score * containment)), 6)


def _crop(image: Any, box: tuple[float, float, float, float]) -> Any:
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, int(math.floor(box[0]))))
    y1 = max(0, min(height - 1, int(math.floor(box[1]))))
    x2 = max(x1 + 1, min(width, int(math.ceil(box[2]))))
    y2 = max(y1 + 1, min(height, int(math.ceil(box[3]))))
    return image[y1:y2, x1:x2]


def _candidates(runtime: Runtime, image: Any) -> list[dict[str, Any]]:
    faces = _faces(runtime, image)
    height, width = image.shape[:2]
    result: list[dict[str, Any]] = []
    for prediction in _pose_predictions(runtime, image):
        box = _pose_bbox(prediction)
        if box is not None:
            result.append({"bbox": box, "pose": prediction, "face": None})
    unmatched = list(faces)
    for candidate in result:
        matches = [face for face in unmatched if _face_bbox(face) is not None and _face_center_inside(_face_bbox(face), candidate["bbox"])]
        if matches:
            matches.sort(key=lambda face: float(getattr(face, "det_score", 0.0) or 0.0), reverse=True)
            candidate["face"] = matches[0]
            unmatched.remove(matches[0])
    for face in unmatched:
        box = _face_bbox(face)
        if box is None:
            continue
        x1, y1, x2, y2 = box
        fw, fh = x2 - x1, y2 - y1
        result.append(
            {
                "bbox": (max(0.0, x1 - 1.2 * fw), max(0.0, y1 - 0.4 * fh), min(float(width), x2 + 1.2 * fw), min(float(height), y2 + 4.5 * fh)),
                "pose": None,
                "face": face,
            }
        )
    result.sort(key=lambda item: ((item["bbox"][0] + item["bbox"][2]) * 0.5, (item["bbox"][1] + item["bbox"][3]) * 0.5))
    return result


def _candidate_rows(
    runtime: Runtime,
    image: Any,
    *,
    base: Mapping[str, Any],
    candidate_prefix: str = "",
) -> list[dict[str, Any]]:
    if candidate_prefix and any(not (character.isalnum() or character in "._-") for character in candidate_prefix):
        raise ReferenceVisionError("candidate prefix is invalid")
    candidates = _candidates(runtime, image)
    height, width = image.shape[:2]
    frame_sha = _frame_sha(image)
    phash = _perceptual_hash(runtime, image)
    if not candidates:
        return [{**base, "frame_sha256": frame_sha, "perceptual_hash": phash, "candidate_id": f"{candidate_prefix}none-0", "person_detected": False, "width": width, "height": height, "view_bin": "unknown", "face_visibility": 0.0, "full_body_visibility": 0.0, "person_fraction": 0.0, "sharpness": _sharpness(runtime, image), "motion": 0.0, "occlusion": 0.0, "identity_measurement_status": "unavailable", "identity_embedding": None}]
    boxes = [candidate["bbox"] for candidate in candidates]
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        box = candidate["bbox"]
        face = candidate["face"]
        pose = candidate["pose"]
        vector = None if face is None else _embedding(face, runtime.embedding_dimension)
        overlaps = [_iou(box, other) for other_index, other in enumerate(boxes) if other_index != index]
        rows.append(
            {
                **base,
                "frame_sha256": frame_sha,
                "perceptual_hash": phash,
                "candidate_id": f"{candidate_prefix}person-{index:03d}",
                "person_detected": True,
                "width": width,
                "height": height,
                "view_bin": "unknown" if face is None else _view_bin(face),
                "face_visibility": 0.0 if face is None else _face_visibility(face, width=width, height=height),
                "full_body_visibility": 0.0 if pose is None else _body_visibility(pose, width=width, height=height),
                "person_fraction": round(max(0.0, min(1.0, _area(box) / max(1.0, width * height))), 6),
                "sharpness": _sharpness(runtime, _crop(image, box)),
                "motion": 0.0,
                "occlusion": round(max(overlaps, default=0.0), 6),
                "identity_measurement_status": "available" if vector is not None else "unavailable",
                "identity_embedding": vector,
            }
        )
    return rows


def _iter_samples(sources: Iterable[Mapping[str, Any]], field: str) -> Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    for source in sources:
        samples = source.get(field)
        if not isinstance(samples, list):
            raise ReferenceVisionError(f"source {source.get('source_key')} has no {field}")
        for sample in samples:
            if not isinstance(sample, Mapping):
                raise ReferenceVisionError("sample is not an object")
            yield source, sample


def _single_identity_from_image(runtime: Runtime, image: Any) -> tuple[str, list[float]] | None:
    candidates = _candidates(runtime, image)
    if len(candidates) != 1 or candidates[0]["face"] is None:
        return None
    vector = _embedding(candidates[0]["face"], runtime.embedding_dimension)
    return None if vector is None else (_frame_sha(image), vector)


def _single_identity(runtime: Runtime, source: Mapping[str, Any], sample: Mapping[str, Any]) -> tuple[str, list[float]] | None:
    image, spatial = _read_sample(runtime, source, sample)
    if not spatial:
        return _single_identity_from_image(runtime, image)

    if source.get("projection") != "equi":
        raise ReferenceVisionError(
            "spatial identity bootstrap requires exact equirectangular projection authority"
        )
    authority = source.get("projection_authority")
    if not isinstance(authority, Mapping):
        raise ReferenceVisionError(
            "spatial identity bootstrap requires exact equirectangular projection authority"
        )
    try:
        viewports = deproject_equirectangular_views(runtime, image, authority)
    except PhotorealEquirectangularDeprojectionError as exc:
        raise ReferenceVisionError(f"identity equirectangular deprojection failed: {exc}") from exc

    measurements: list[tuple[str, list[float]]] = []
    for _viewport_id, viewport_image in viewports:
        measured = _single_identity_from_image(runtime, viewport_image)
        if measured is not None:
            measurements.append(measured)
    if len(measurements) != 1:
        return None
    return measurements[0]


def _identity_result(runtime: Runtime, request: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for source, sample in _iter_samples(request["sources"], "reference_samples"):
        measured = _single_identity(runtime, source, sample)
        if measured is not None:
            frame_sha, vector = measured
            observations.append({"source_key": source["source_key"], "source_sha256": source["source_sha256"], "timestamp_seconds": sample.get("timestamp_seconds"), "eye": sample["eye"], "frame_sha256": frame_sha, "embedding": vector})
    if not observations:
        raise ReferenceVisionError("identity extractor found no unambiguous single-person reference observations")
    return {"format": "bodyrig-photoreal-identity-reference-observations", "version": 1, "performer_id": request["performer_id"], "extractor": args.bodyrig_adapter, "extractor_revision": args.bodyrig_revision, "model_set_sha256": args.bodyrig_model_set_sha256, "embedding_dimension": runtime.embedding_dimension, "observations": observations, "build_only": True, "production_activation": False}


def _calibration_result(runtime: Runtime, request: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for source, sample in _iter_samples(request["sources"], "samples"):
        try:
            image, spatial = _read_sample(runtime, source, sample)
        except ReferenceVisionDecodeError:
            # Negative calibration is deliberately evidence-thresholded downstream.
            # A corrupt/unseekable negative sample may be omitted, while structural
            # path/layout/provenance errors remain fatal. Stage 13 still requires
            # enough observations from enough distinct negative performers.
            continue
        if spatial:
            raise ReferenceVisionError(
                "spatial source cannot establish calibration identity before projection-specific deprojection"
            )
        base = {
            "source_key": source["source_key"],
            "source_sha256": source["source_sha256"],
            "timestamp_seconds": sample.get("timestamp_seconds"),
            "eye": sample["eye"],
        }
        rows = _candidate_rows(runtime, image, base=base)
        detected = [row for row in rows if row["person_detected"] is True]
        if len(detected) != 1:
            continue
        row = detected[0]
        if (
            row["identity_measurement_status"] != "available"
            or row["identity_embedding"] is None
        ):
            continue
        observations.append(
            {
                "source_key": row["source_key"],
                "source_sha256": row["source_sha256"],
                "subject_performer_id": source["subject_performer_id"],
                "timestamp_seconds": row.get("timestamp_seconds"),
                "eye": row["eye"],
                "frame_sha256": row["frame_sha256"],
                "candidate_id": row["candidate_id"],
                "candidate_count": len(detected),
                "person_detected": row["person_detected"],
                "width": row["width"],
                "height": row["height"],
                "view_bin": row["view_bin"],
                "face_visibility": row["face_visibility"],
                "full_body_visibility": row["full_body_visibility"],
                "person_fraction": row["person_fraction"],
                "sharpness": row["sharpness"],
                "motion": row["motion"],
                "occlusion": row["occlusion"],
                "identity_measurement_status": row["identity_measurement_status"],
                "identity_measurement_reason": "embedding-available",
                "embedding": row["identity_embedding"],
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
        "identity_matching_authority": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }


def _frame_result(runtime: Runtime, request: Mapping[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for source, sample in _iter_samples(request["sources"], "samples"):
        image, spatial = _read_sample(runtime, source, sample)
        base = {"source_key": source["source_key"], "source_sha256": source["source_sha256"], "kind": source["kind"], "timestamp_seconds": sample.get("timestamp_seconds"), "eye": sample["eye"], "projection": source["projection"]}
        if spatial and source.get("projection") == "equi":
            try:
                viewports = deproject_equirectangular_views(runtime, image, source.get("projection_authority"))
            except PhotorealEquirectangularDeprojectionError as exc:
                raise ReferenceVisionError(f"equirectangular deprojection failed: {exc}") from exc
            for viewport_id, viewport_image in viewports:
                observations.extend(
                    _candidate_rows(
                        runtime,
                        viewport_image,
                        base=base,
                        candidate_prefix=f"{viewport_id}-",
                    )
                )
        elif spatial:
            height, width = image.shape[:2]
            observations.append({**base, "frame_sha256": _frame_sha(image), "perceptual_hash": _perceptual_hash(runtime, image), "candidate_id": "none-0", "person_detected": False, "width": width, "height": height, "view_bin": "unknown", "face_visibility": 0.0, "full_body_visibility": 0.0, "person_fraction": 0.0, "sharpness": _sharpness(runtime, image), "motion": 0.0, "occlusion": 0.0, "identity_measurement_status": "unavailable", "identity_embedding": None})
        else:
            observations.extend(_candidate_rows(runtime, image, base=base))
    if not observations:
        raise ReferenceVisionError("frame analyzer produced no observations")
    return {"format": "bodyrig-photoreal-frame-observations", "version": 1, "performer_id": request["performer_id"], "analyzer": args.bodyrig_adapter, "analyzer_revision": args.bodyrig_revision, "analyzer_model_set_sha256": args.bodyrig_model_set_sha256, "identity_embedding_dimension": runtime.embedding_dimension, "observations": observations, "build_only": True, "production_activation": False}


def _write_result(request_format: str, result: Mapping[str, Any], output: Path) -> None:
    if not output.is_dir():
        raise ReferenceVisionError(f"BodyRig output directory does not exist: {output}")
    if any(output.iterdir()):
        raise ReferenceVisionError("BodyRig output directory must be empty")
    filename = {IDENTITY_REQUEST: "identity-observations.json", CALIBRATION_REQUEST: "negative-observations.json", FRAME_REQUEST: "observations.json"}[request_format]
    (output / filename).write_text(json.dumps(dict(result), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


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
        request = _read_json(args.bodyrig_request.expanduser().resolve(), label="BodyRig adapter request")
        model_root = args.model_root.expanduser().resolve()
        manifest = _verify_provenance(args, request, model_root)
        runtime = _load_runtime(manifest, device=args.device)
        if request["format"] == IDENTITY_REQUEST:
            result = _identity_result(runtime, request, args)
        elif request["format"] == CALIBRATION_REQUEST:
            if _sha(args.bodyrig_identity_bank_sha256, label="CLI identity bank SHA-256") != _sha(request.get("identity_bank_sha256"), label="request identity bank SHA-256"):
                raise ReferenceVisionError("request/CLI identity bank provenance mismatch")
            result = _calibration_result(runtime, request, args)
        else:
            result = _frame_result(runtime, request, args)
        _write_result(request["format"], result, args.bodyrig_output.expanduser().resolve())
    except ReferenceVisionError as exc:
        print(f"BodyRig reference vision adapter: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
