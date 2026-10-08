from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from bodyrig.photoreal_cubemap_deprojection import build_cubemap_viewports
from bodyrig.photoreal_equirectangular_deprojection import build_equirectangular_viewports
from bodyrig.photoreal_mesh_deprojection import (
    _selected_mesh,
    build_mesh_viewports,
    load_mesh_projection_geometry,
)

REQUEST_FORMAT = "bodyrig-photoreal-exavatar-materialization-request"
REQUEST_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-exavatar-materialization-receipt"
RECEIPT_VERSION = 1
UPSTREAM_COMMIT = "d45268730c779fae4118f1a361cf9ff639bc4d1e"
SUPPORTED_NORMALIZATION_ACTIONS = {"preserve-flat-mono-video", "exact-authorized-deprojection"}


class ExAvatarMaterializeError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExAvatarMaterializeError(f"materialization request is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ExAvatarMaterializeError("materialization request must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise ExAvatarMaterializeError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise ExAvatarMaterializeError(f"{label} is invalid")
    return result


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_sha(image: Any) -> str:
    shape = "x".join(str(int(value)) for value in image.shape)
    digest = hashlib.sha256()
    digest.update((shape + "\n").encode("ascii"))
    digest.update(memoryview(image).cast("B"))
    return digest.hexdigest()


def _validate_request(value: Mapping[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if value.get("format") != REQUEST_FORMAT or value.get("version") != REQUEST_VERSION:
        raise ExAvatarMaterializeError("materialization request format/version mismatch")
    if value.get("upstream_commit") != UPSTREAM_COMMIT:
        raise ExAvatarMaterializeError("materialization request targets wrong ExAvatar commit")
    if value.get("held_out_evaluation_disclosed") is not False:
        raise ExAvatarMaterializeError("materialization request disclosed held-out evaluation")
    if value.get("photoreal_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise ExAvatarMaterializeError("materialization request crossed downstream authority")
    if value.get("build_only") is not True:
        raise ExAvatarMaterializeError("materialization request must be build-only")
    _sha(value.get("benchmark_plan_sha256"), label="benchmark plan SHA-256")
    _sha(value.get("teacher_input_sha256"), label="teacher input SHA-256")
    _text(value.get("performer_id"), label="performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="selected epoch id", maximum=256)

    source_raw = value.get("source")
    if not isinstance(source_raw, Mapping):
        raise ExAvatarMaterializeError("materialization request source is invalid")
    if source_raw.get("kind") != "video":
        raise ExAvatarMaterializeError("ExAvatar materialization requires a video source")
    projection = _text(source_raw.get("projection"), label="source projection", maximum=128)
    stereo_layout = _text(source_raw.get("stereo_layout"), label="source stereo layout", maximum=128)
    decode_mode = _text(source_raw.get("decode_mode"), label="source decode mode", maximum=128)
    normalization_action = _text(
        source_raw.get("normalization_action"),
        label="source normalization action",
        maximum=128,
    )
    if normalization_action not in SUPPORTED_NORMALIZATION_ACTIONS:
        raise ExAvatarMaterializeError("source normalization action is unsupported")
    projection_authority = source_raw.get("projection_authority")
    if normalization_action == "preserve-flat-mono-video":
        if projection != "flat" or stereo_layout != "mono" or decode_mode != "rectilinear-mono":
            raise ExAvatarMaterializeError("direct ExAvatar source is not authoritative flat mono")
        if projection_authority is not None:
            raise ExAvatarMaterializeError("direct ExAvatar source unexpectedly carries projection authority")
        allowed_eyes = {"mono"}
    else:
        if decode_mode not in {"rectilinear-stereo-split", "spatial-deprojection-required"}:
            raise ExAvatarMaterializeError("deprojected ExAvatar source decode mode is unsupported")
        if stereo_layout == "mono":
            allowed_eyes = {"mono"}
        elif stereo_layout in {"side-by-side", "over-under", "mesh-custom"}:
            allowed_eyes = {"left", "right"}
        else:
            raise ExAvatarMaterializeError("deprojected ExAvatar source stereo layout is unsupported")
        if decode_mode == "spatial-deprojection-required" and not isinstance(projection_authority, Mapping):
            raise ExAvatarMaterializeError("spatial ExAvatar source lacks projection authority")

    source = {
        "source_key": _text(source_raw.get("source_key"), label="source key", maximum=4096),
        "source_sha256": _sha(source_raw.get("source_sha256"), label="source SHA-256"),
        "resolved_path": _text(source_raw.get("resolved_path"), label="resolved source path"),
        "kind": "video",
        "projection": projection,
        "stereo_layout": stereo_layout,
        "decode_mode": decode_mode,
        "normalization_action": normalization_action,
        "projection_authority": None if projection_authority is None else dict(projection_authority),
    }
    if not source["resolved_path"].startswith("/"):
        raise ExAvatarMaterializeError("resolved source path must be absolute Linux path")

    observations_raw = value.get("observations")
    if not isinstance(observations_raw, list) or not observations_raw:
        raise ExAvatarMaterializeError("materialization request contains no observations")
    observations: list[dict[str, Any]] = []
    seen: set[tuple[str, float, str]] = set()
    for raw in observations_raw:
        if not isinstance(raw, Mapping):
            raise ExAvatarMaterializeError("materialization observation is invalid")
        if raw.get("source_key") != source["source_key"]:
            raise ExAvatarMaterializeError("materialization observation references different source")
        eye = _text(raw.get("eye"), label="materialization observation eye", maximum=16)
        if eye not in allowed_eyes:
            raise ExAvatarMaterializeError("materialization observation eye is incompatible with source authority")
        timestamp_raw = raw.get("timestamp_seconds")
        if isinstance(timestamp_raw, bool):
            raise ExAvatarMaterializeError("materialization timestamp is invalid")
        try:
            timestamp = float(timestamp_raw)
        except (TypeError, ValueError) as exc:
            raise ExAvatarMaterializeError("materialization timestamp is invalid") from exc
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ExAvatarMaterializeError("materialization timestamp is invalid")
        timestamp = round(timestamp, 6)
        frame_sha = _sha(raw.get("frame_sha256"), label="source frame SHA-256")
        key = (frame_sha, timestamp, eye)
        if key in seen:
            raise ExAvatarMaterializeError("materialization request repeats observation")
        seen.add(key)
        observations.append(
            {
                "source_key": source["source_key"],
                "frame_sha256": frame_sha,
                "timestamp_seconds": timestamp,
                "eye": eye,
            }
        )
    observations.sort(key=lambda item: (item["timestamp_seconds"], item["eye"], item["frame_sha256"]))
    if normalization_action == "exact-authorized-deprojection" and stereo_layout != "mono":
        eyes = {item["eye"] for item in observations}
        if len(eyes) != 1:
            raise ExAvatarMaterializeError(
                "ExAvatar spatial materialization requires a single stereo eye; "
                "mixed left/right views have no authoritative shared camera center"
            )
    return source, observations


def _load_replay_runtime() -> tuple[Any, Any]:
    try:
        from bodyrig.photoreal_appearance_epoch_visual_review import (
            _load_adapter,
            _load_runtime,
            _reproduce_observation,
        )
    except Exception as exc:  # noqa: BLE001
        raise ExAvatarMaterializeError("BodyRig exact-frame replay support is unavailable") from exc
    try:
        repo_root = Path(__file__).resolve().parents[1]
        adapter = _load_adapter(repo_root)
        runtime = _load_runtime()
    except Exception as exc:  # noqa: BLE001
        raise ExAvatarMaterializeError("could not initialize BodyRig exact-frame replay runtime") from exc
    return SimpleNamespace(
        adapter=adapter,
        runtime=runtime,
        reproduce=_reproduce_observation,
    ), runtime.cv2


def _viewport_camera_record(
    viewport: Mapping[str, Any],
    *,
    width: int,
    height: int,
    projection: str,
    eye: str,
) -> dict[str, Any]:
    try:
        yaw = float(viewport["yaw_degrees"])
        pitch = float(viewport["pitch_degrees"])
        hfov = float(viewport["horizontal_fov_degrees"])
        vfov = float(viewport["vertical_fov_degrees"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ExAvatarMaterializeError("matched BodyRig viewport camera metadata is invalid") from exc
    if not all(math.isfinite(value) for value in (yaw, pitch, hfov, vfov)):
        raise ExAvatarMaterializeError("matched BodyRig viewport camera metadata is non-finite")
    if not 0.0 < hfov < 179.0 or not 0.0 < vfov < 179.0:
        raise ExAvatarMaterializeError("matched BodyRig viewport FOV is invalid")
    if width < 2 or height < 2:
        raise ExAvatarMaterializeError("matched BodyRig viewport dimensions are invalid")
    focal_x = width / (2.0 * math.tan(math.radians(hfov) * 0.5))
    focal_y = height / (2.0 * math.tan(math.radians(vfov) * 0.5))
    if not all(math.isfinite(value) and value > 0.0 for value in (focal_x, focal_y)):
        raise ExAvatarMaterializeError("derived BodyRig viewport focal length is invalid")
    return {
        "format": "bodyrig-exavatar-tangent-camera",
        "version": 1,
        "projection": projection,
        "eye": eye,
        "viewport_id": str(viewport["viewport_id"]),
        "yaw_degrees": round(yaw, 9),
        "pitch_degrees": round(pitch, 9),
        "horizontal_fov_degrees": round(hfov, 9),
        "vertical_fov_degrees": round(vfov, 9),
        "focal": [round(focal_x, 9), round(focal_y, 9)],
        "princpt": [width / 2.0, height / 2.0],
        "rotation_authority": True,
        "intrinsics_authority": True,
        "translation_authority": True,
    }


def _reproduce_exact_with_camera(
    replay: Any,
    source: Mapping[str, Any],
    observation: Mapping[str, Any],
    *,
    mesh_cache: dict[Any, Any],
    mesh_geometry_cache: dict[str, Any],
) -> tuple[Any, dict[str, Any] | None]:
    expected = _sha(observation.get("frame_sha256"), label="source frame SHA-256")
    sample = {
        "timestamp_seconds": observation.get("timestamp_seconds"),
        "eye": observation.get("eye"),
    }
    try:
        image, spatial = replay.adapter._read_frame_sample(replay.runtime, source, sample)
    except Exception as exc:  # noqa: BLE001
        raise ExAvatarMaterializeError(
            "authorized benchmark frame could not be decoded from P0 authority "
            f"(source={source['source_key']}, timestamp={observation['timestamp_seconds']}, eye={observation['eye']})"
        ) from exc

    if not spatial:
        if replay.adapter.base._frame_sha(image) != expected:
            raise ExAvatarMaterializeError(
                "authorized benchmark frame bytes do not reproduce P0 observation"
            )
        return replay.runtime.np.ascontiguousarray(image), None

    projection = str(source.get("projection") or "")
    authority = source.get("projection_authority")
    eye = str(observation.get("eye") or "")
    candidates: list[tuple[str, Any]]
    viewport_by_id: dict[str, Mapping[str, Any]]
    try:
        if projection == "equi":
            candidates = replay.adapter.base.deproject_equirectangular_views(
                replay.runtime,
                image,
                authority,
            )
            viewport_by_id = {
                str(item["viewport_id"]): item
                for item in build_equirectangular_viewports(authority)
            }
        elif projection == "cbmp":
            candidates = replay.adapter.deproject_cubemap_views(
                replay.runtime,
                image,
                authority,
            )
            viewport_by_id = {
                str(item["viewport_id"]): item
                for item in build_cubemap_viewports()
            }
        elif projection == "mshp":
            candidates = replay.adapter.deproject_mesh_views(
                replay.runtime,
                image,
                source.get("resolved_path"),
                authority,
                eye=eye,
                cache=mesh_cache,
            )
            source_path = str(source.get("resolved_path") or "")
            geometry = mesh_geometry_cache.get(source_path)
            if geometry is None:
                geometry = load_mesh_projection_geometry(source_path, authority)
                mesh_geometry_cache[source_path] = geometry
            mesh = _selected_mesh(geometry, eye)
            viewport_by_id = {
                str(item["viewport_id"]): item
                for item in build_mesh_viewports(mesh)
            }
        else:
            raise ExAvatarMaterializeError(
                f"spatial ExAvatar source projection is unsupported for camera provenance: {projection}"
            )
    except ExAvatarMaterializeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExAvatarMaterializeError(
            f"could not reproduce spatial BodyRig viewport camera for projection {projection}"
        ) from exc

    matches = [
        (viewport_id, candidate)
        for viewport_id, candidate in candidates
        if replay.adapter.base._frame_sha(candidate) == expected
    ]
    if len(matches) != 1:
        raise ExAvatarMaterializeError(
            "authorized spatial frame did not map to exactly one BodyRig viewport "
            f"(source={source['source_key']}, expected={expected}, matches={len(matches)})"
        )
    viewport_id, candidate = matches[0]
    viewport = viewport_by_id.get(str(viewport_id))
    if viewport is None:
        raise ExAvatarMaterializeError(
            f"matched BodyRig viewport lacks camera metadata: {viewport_id}"
        )
    height, width = candidate.shape[:2]
    camera = _viewport_camera_record(
        viewport,
        width=int(width),
        height=int(height),
        projection=projection,
        eye=eye,
    )
    return replay.runtime.np.ascontiguousarray(candidate), camera


def _decode_exact_frames(source: Mapping[str, Any], observations: list[dict[str, Any]], output: Path) -> list[dict[str, Any]]:
    replay, cv2 = _load_replay_runtime()
    frames_dir = output / "frames"
    frames_dir.mkdir()
    result: list[dict[str, Any]] = []
    mesh_cache: dict[Any, Any] = {}
    mesh_geometry_cache: dict[str, Any] = {}
    for index, observation in enumerate(observations):
        try:
            image, camera = _reproduce_exact_with_camera(
                replay,
                source,
                observation,
                mesh_cache=mesh_cache,
                mesh_geometry_cache=mesh_geometry_cache,
            )
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, ExAvatarMaterializeError):
                raise
            raise ExAvatarMaterializeError(
                "authorized benchmark frame could not be reproduced from P0 decode authority "
                f"(source={source['source_key']}, timestamp={observation['timestamp_seconds']}, eye={observation['eye']})"
            ) from exc

        observed_frame_sha = replay.adapter.base._frame_sha(image)
        expected_frame_sha = observation["frame_sha256"]
        if observed_frame_sha != expected_frame_sha:
            raise ExAvatarMaterializeError(
                "authorized benchmark frame bytes do not reproduce P0 observation "
                f"(expected={expected_frame_sha}, observed={observed_frame_sha})"
            )

        frame_path = frames_dir / f"{index}.png"
        if not cv2.imwrite(str(frame_path), image, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
            raise ExAvatarMaterializeError(f"could not write lossless staged PNG: {frame_path}")
        if not frame_path.is_file() or frame_path.stat().st_size < 1:
            raise ExAvatarMaterializeError(f"staged PNG is missing/empty: {frame_path}")
        record = {
            "exavatar_frame_index": index,
            "source_key": source["source_key"],
            "source_frame_sha256": expected_frame_sha,
            "timestamp_seconds": float(observation["timestamp_seconds"]),
            "eye": observation["eye"],
            "relative_path": f"frames/{index}.png",
            "staged_png_sha256": _file_sha(frame_path),
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
            "camera": camera,
        }
        if source.get("normalization_action") == "exact-authorized-deprojection" and camera is None:
            raise ExAvatarMaterializeError(
                "deprojected ExAvatar frame lacks authoritative BodyRig tangent-camera provenance"
            )
        result.append(record)
    return result

def materialize(request: Mapping[str, Any], output: Path) -> dict[str, Any]:
    source, observations = _validate_request(request)
    if not output.is_dir():
        raise ExAvatarMaterializeError(f"materialization output directory does not exist: {output}")
    if any(output.iterdir()):
        raise ExAvatarMaterializeError("materialization output directory must be empty")

    frames = _decode_exact_frames(source, observations, output)
    indices = "".join(f"{index}\n" for index in range(len(frames)))
    (output / "frame_list_all.txt").write_text(indices, encoding="utf-8")
    (output / "frame_list_train.txt").write_text(indices, encoding="utf-8")
    # BodyRig held-out evaluation is deliberately external to ExAvatar.
    (output / "frame_list_test.txt").write_text("", encoding="utf-8")

    source_map = {
        "format": "bodyrig-photoreal-exavatar-source-map",
        "version": 1,
        "benchmark_plan_sha256": request["benchmark_plan_sha256"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "source_key": source["source_key"],
        "source_sha256": source["source_sha256"],
        "projection": source["projection"],
        "stereo_layout": source["stereo_layout"],
        "decode_mode": source["decode_mode"],
        "normalization_action": source["normalization_action"],
        "frames": frames,
        "held_out_evaluation_disclosed": False,
        "build_only": True,
        "production_activation": False,
    }
    (output / "bodyrig-source-map.json").write_text(
        json.dumps(source_map, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    receipt = {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "benchmark_plan_sha256": request["benchmark_plan_sha256"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "upstream_commit": request["upstream_commit"],
        "source_key": source["source_key"],
        "source_sha256": source["source_sha256"],
        "frame_count": len(frames),
        "frames": frames,
        "frame_lists_are_training_only": True,
        "bodyrig_held_out_evaluation_is_external": True,
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "exact_p0_frame_hashes_reproduced": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }
    (output / "materialization-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize exact BodyRig-authorized frames for ExAvatar benchmark preprocessing.")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = _read_json(args.request.expanduser().resolve())
        receipt = materialize(request, args.output.expanduser().resolve())
    except ExAvatarMaterializeError as exc:
        print(f"BodyRig ExAvatar materializer: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "PASS",
                "source_key": receipt["source_key"],
                "frame_count": receipt["frame_count"],
                "exact_p0_frame_hashes_reproduced": receipt["exact_p0_frame_hashes_reproduced"],
                "held_out_evaluation_disclosed": receipt["held_out_evaluation_disclosed"],
                "production_activation": receipt["production_activation"],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
