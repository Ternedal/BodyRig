"""Read-only ExAvatar fit alignment diagnostic using existing 2D keypoints and 3D meshes.

It does not start preprocessing, modify the source dataset, or authorize teacher training.
The diagnostic compares bounding boxes only; it is NOT per-joint fit acceptance.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import struct
from typing import Any, Iterator

DEFAULT_FRAMES = (14, 19, 41, 43, 50, 58, 75, 76, 89, 93, 99, 105, 258, 345, 357, 427)
PLY_TYPES = {
    "char": "b", "uchar": "B", "short": "h", "ushort": "H",
    "int": "i", "uint": "I", "float": "f", "double": "d",
    "int8": "b", "uint8": "B", "int16": "h", "uint16": "H",
    "int32": "i", "uint32": "I", "float32": "f", "float64": "d",
}


class FitDiagnosticError(ValueError):
    """Invalid or missing diagnostic inputs."""


def _load_json(path: Path) -> Any:
    if not path.is_file() or path.is_symlink():
        raise FitDiagnosticError(f"Missing/unsafe input: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FitDiagnosticError(f"Unreadable JSON: {path}") from exc


def _png_size(path: Path) -> tuple[int, int]:
    if not path.is_file() or path.is_symlink():
        raise FitDiagnosticError(f"Missing frame: {path}")
    with path.open("rb") as stream:
        header = stream.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise FitDiagnosticError(f"Invalid PNG: {path}")
    width, height = struct.unpack(">II", header[16:24])
    if not 1 <= width <= 8192 or not 1 <= height <= 8192:
        raise FitDiagnosticError("Frame dimensions outside diagnostic limits")
    return width, height


def _vertices(path: Path) -> Iterator[tuple[float, float, float]]:
    if not path.is_file() or path.is_symlink():
        raise FitDiagnosticError(f"Missing mesh: {path}")
    with path.open("rb") as stream:
        if stream.readline().strip() != b"ply":
            raise FitDiagnosticError(f"Not a PLY mesh: {path}")
        fmt = None
        count = None
        in_vertex = False
        props: list[tuple[str, str]] = []
        while True:
            line = stream.readline()
            if not line:
                raise FitDiagnosticError(f"Unterminated PLY header: {path}")
            line = line.decode("ascii", errors="strict").strip()
            if line == "end_header":
                break
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "format":
                fmt = parts[1]
            elif len(parts) >= 3 and parts[0] == "element":
                in_vertex = parts[1] == "vertex"
                if in_vertex:
                    count = int(parts[2])
            elif in_vertex and len(parts) >= 3 and parts[0] == "property":
                if parts[1] == "list":
                    raise FitDiagnosticError("List-valued vertex properties are unsupported")
                if parts[1] not in PLY_TYPES:
                    raise FitDiagnosticError(f"Unknown PLY vertex property: {parts[1]}")
                props.append((parts[1], parts[2]))

        if count is None or not 1 <= count <= 250_000:
            raise FitDiagnosticError("PLY vertex count invalid/outside diagnostic limits")
        names = [name for _, name in props]
        if any(name not in names for name in ("x", "y", "z")):
            raise FitDiagnosticError("PLY mesh lacks x/y/z vertex properties")
        indices = [names.index(axis) for axis in ("x", "y", "z")]
        if fmt == "ascii":
            for _ in range(count):
                line = stream.readline()
                if not line:
                    raise FitDiagnosticError("Truncated ASCII PLY")
                values = line.split()
                if len(values) < len(props):
                    raise FitDiagnosticError("Incomplete ASCII PLY vertex")
                yield tuple(float(values[i]) for i in indices)
        elif fmt in {"binary_little_endian", "binary_big_endian"}:
            endian = "<" if fmt == "binary_little_endian" else ">"
            record = struct.Struct(endian + "".join(PLY_TYPES[t] for t, _ in props))
            for _ in range(count):
                raw = stream.read(record.size)
                if len(raw) != record.size:
                    raise FitDiagnosticError("Truncated binary PLY")
                values = record.unpack(raw)
                yield tuple(float(values[i]) for i in indices)
        else:
            raise FitDiagnosticError(f"Unsupported PLY format: {fmt}")


def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    if not points:
        raise FitDiagnosticError("No points for bounding box")
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def _robust_bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    # Suppress isolated projecting outliers, not whole clipped limbs.
    xs = sorted(p[0] for p in points)
    ys = sorted(p[1] for p in points)
    n = len(points)
    lo, hi = int(0.02 * (n - 1)), int(0.98 * (n - 1))
    return xs[lo], ys[lo], xs[hi], ys[hi]


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    intersection = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0.0 else 0.0


def _mesh_projection(
    path: Path, camera: dict[str, Any]
) -> tuple[tuple[float, float, float, float], int, int]:
    focal, center = camera["focal"], camera["princpt"]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (*focal, *center)):
        raise FitDiagnosticError("Camera has non-finite intrinsics")
    fx, fy = float(focal[0]), float(focal[1])
    cx, cy = float(center[0]), float(center[1])
    if fx <= 0 or fy <= 0:
        raise FitDiagnosticError("Invalid camera focal length")
    projected: list[tuple[float, float]] = []
    count = 0
    for x, y, z in _vertices(path):
        count += 1
        if math.isfinite(x) and math.isfinite(y) and math.isfinite(z) and z > 0.05:
            u, v = fx * x / z + cx, fy * y / z + cy
            if math.isfinite(u) and math.isfinite(v):
                projected.append((u, v))
    if len(projected) < 200:
        raise FitDiagnosticError(f"Too few forward-facing vertices: {path}")
    return _robust_bbox(projected), count, len(projected)


def diagnose_frame(dataset: Path, frame: int, *, include_smoothed: bool = True) -> dict[str, Any]:
    width, height = _png_size(dataset / "frames" / f"{frame}.png")
    camera = _load_json(dataset / "cam_params" / f"{frame}.json")
    keypoints = _load_json(dataset / "keypoints_whole_body" / f"{frame}.json")
    if not isinstance(camera, dict) or not isinstance(keypoints, list) or len(keypoints) < 17:
        raise FitDiagnosticError("Invalid camera/keypoint structure")

    # COCO-WholeBody indexes 0..16 are major body joints.
    valid: list[tuple[float, float]] = []
    for index in range(17):
        row = keypoints[index]
        if not isinstance(row, list) or len(row) < 3:
            continue
        x, y, confidence = row[:3]
        if all(isinstance(v, (float, int)) and math.isfinite(v) for v in (x, y, confidence)):
            if confidence >= 0.25 and 0 <= x <= width and 0 <= y <= height:
                valid.append((float(x), float(y)))
    record: dict[str, Any] = {
        "frame": frame, "width": width, "height": height,
        "valid_body_keypoints": len(valid), "body_keypoint_universe": 17,
        "metrics": {},
        "limitations": [
            "Body-keypoint bounding box is not the full human silhouette.",
            "Mesh is assumed to be saved in camera coordinates by pinned ExAvatar fitting.",
            "This is a diagnostic only: overlap is not 3D physical or identity acceptance.",
        ],
    }
    if len(valid) < 5:
        record["warning"] = "Too few visible body keypoints for robust bbox comparison"
        return record
    keybox = _bbox(valid)
    record["body_keypoint_bbox"] = [round(v, 2) for v in keybox]
    record["body_bbox_touches_frame"] = any((
        keybox[0] < width * 0.03, keybox[1] < height * 0.03,
        keybox[2] > width * 0.97, keybox[3] > height * 0.97,
    ))
    optimized = dataset / "smplx_optimized"
    variants = [
        ("optimized", optimized / "meshes" / f"{frame}_smplx.ply"),
    ]
    if include_smoothed:
        variants.append(("smoothed", optimized / "meshes_smoothed" / f"{frame}_smplx.ply"))
    for label, path in variants:
        meshbox, vertices, visible = _mesh_projection(path, camera)
        mesh_width = max(1e-6, meshbox[2] - meshbox[0])
        mesh_height = max(1e-6, meshbox[3] - meshbox[1])
        key_width = max(1e-6, keybox[2] - keybox[0])
        key_height = max(1e-6, keybox[3] - keybox[1])
        dx = ((meshbox[0] + meshbox[2]) - (keybox[0] + keybox[2])) * 0.5
        dy = ((meshbox[1] + meshbox[3]) - (keybox[1] + keybox[3])) * 0.5
        record["metrics"][label] = {
            "mesh_bbox": [round(v, 2) for v in meshbox],
            "mesh_vertex_count": vertices,
            "forward_mesh_vertices": visible,
            "mesh_keypoint_bbox_iou": round(_iou(meshbox, keybox), 4),
            "center_dx_normalized": round(dx / width, 4),
            "center_dy_normalized": round(dy / height, 4),
            "height_ratio_to_keypoint_bbox": round(mesh_height / key_height, 4),
            "width_ratio_to_keypoint_bbox": round(mesh_width / key_width, 4),
        }
    return record


def _indexed_frames(dataset: Path) -> tuple[int, ...]:
    """Use only the existing ExAvatar frame universe; never invent missing frames."""
    index_path = dataset / "frame_list_all.txt"
    if not index_path.is_file() or index_path.is_symlink():
        raise FitDiagnosticError(f"Missing or unsafe frame index: {index_path}")
    try:
        lines = index_path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise FitDiagnosticError(f"Unreadable frame index: {index_path}") from exc
    if not lines or len(lines) > 10_000:
        raise FitDiagnosticError("Frame index must contain 1..10000 frames")
    frames: list[int] = []
    for line in lines:
        value = line.strip()
        if not value.isdecimal():
            raise FitDiagnosticError("Frame index contains a non-decimal frame identifier")
        frame = int(value)
        if frame > 1_000_000 or frame in frames:
            raise FitDiagnosticError("Frame index contains an invalid or repeated frame")
        frames.append(frame)
    return tuple(frames)


def _triage_frame(record: dict[str, Any]) -> str:
    """Conservative review priority, never a quality or training approval."""
    if "error" in record:
        return "unreadable_evidence"
    if record.get("valid_body_keypoints", 0) < 12:
        return "low_body_keypoint_visibility"
    if record.get("body_bbox_touches_frame"):
        return "body_near_viewport_edge"
    metrics = record.get("metrics", {}).get("optimized")
    if not isinstance(metrics, dict):
        return "missing_alignment_metrics"
    if (
        metrics["mesh_keypoint_bbox_iou"] < 0.35
        or abs(metrics["center_dx_normalized"]) > 0.20
        or abs(metrics["center_dy_normalized"]) > 0.20
        or metrics["height_ratio_to_keypoint_bbox"] < 0.60
        or metrics["height_ratio_to_keypoint_bbox"] > 1.80
    ):
        return "suspect_optimized_geometry"
    return "geometry_proxy_promising_review_required"


def _review_priority(record: dict[str, Any]) -> tuple[int, float, int]:
    category = record["triage"]
    priority = {
        "unreadable_evidence": 0,
        "suspect_optimized_geometry": 1,
        "missing_alignment_metrics": 2,
        "low_body_keypoint_visibility": 3,
        "body_near_viewport_edge": 4,
        "geometry_proxy_promising_review_required": 5,
    }.get(category, 0)
    optimized = record.get("metrics", {}).get("optimized", {})
    return (priority, float(optimized.get("mesh_keypoint_bbox_iou", -1)), int(record["frame"]))


def analyze_dataset(
    dataset: Path,
    frames: tuple[int, ...],
    *,
    include_smoothed: bool = True,
) -> dict[str, Any]:
    if not dataset.is_dir() or dataset.is_symlink():
        raise FitDiagnosticError(f"Dataset is missing/unsafe: {dataset}")
    available = set(_indexed_frames(dataset))
    if not frames or len(frames) > 10_000 or len(set(frames)) != len(frames):
        raise FitDiagnosticError("Select 1..10000 unique frame indexes")
    report: dict[str, Any] = {
        "format": "bodyrig-exavatar-fit-projection-diagnostic",
        "version": 1,
        "dataset": str(dataset.resolve()),
        "training_authority": False,
        "human_fit_review_accepted": False,
        "metric_is_quality_acceptance": False,
        "camera_translation_authority": False,
        "include_smoothed": include_smoothed,
        "frames": [],
    }
    for frame in frames:
        if frame not in available:
            entry = {"frame": frame, "error": "Frame not in dataset index"}
        else:
            try:
                entry = diagnose_frame(dataset, frame, include_smoothed=include_smoothed)
            except (FitDiagnosticError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
                entry = {"frame": frame, "error": str(exc)}
        entry["triage"] = _triage_frame(entry)
        report["frames"].append(entry)
    report["analyzed_frame_count"] = sum(
        "optimized" in row.get("metrics", {}) for row in report["frames"]
    )
    report["diagnostic_error_count"] = sum("error" in row for row in report["frames"])
    report["review_category_counts"] = {
        category: sum(row["triage"] == category for row in report["frames"])
        for category in sorted({row["triage"] for row in report["frames"]})
    }
    # A finite number of prioritized manual-review candidates, NOT a training subset.
    prioritized = sorted(report["frames"], key=_review_priority)
    report["priority_review_frames"] = [
        {"frame": row["frame"], "reason": row["triage"]}
        for row in prioritized[:30]
    ]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all-frames", action="store_true",
                           help="Audit every frame from existing frame_list_all.txt")
    selection.add_argument("--frames",
                           help="Comma-separated numbered sample; default is representative 16 frames")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--optimized-only", action="store_true",
                        help="Skip already-known-bad temporal smoothing artifacts")
    parser.add_argument("--output", type=Path, help="Optional diagnostic JSON path; never source dataset")
    args = parser.parse_args()
    try:
        if args.all_frames:
            frames = _indexed_frames(args.dataset)
        elif args.frames is None:
            frames = DEFAULT_FRAMES
        else:
            frames = tuple(dict.fromkeys(int(v.strip()) for v in args.frames.split(",") if v.strip()))
            if not frames or len(frames) > 100 or any(v < 0 for v in frames):
                raise FitDiagnosticError("Select 1..100 unique nonnegative sample frame indexes")
        report = analyze_dataset(args.dataset, frames, include_smoothed=not args.optimized_only)
        print("frame  joints   fitted IoU   smooth IoU   smooth dx/w   smooth dy/h   height ratio  review flag")
        rows = report["frames"]
        if args.all_frames:
            selected = {item["frame"] for item in report["priority_review_frames"]}
            rows = [row for row in rows if row["frame"] in selected]
        for row in rows:
            if "error" in row:
                print(f"{row['frame']:>5}  ERROR: {row['error']}")
                continue
            m = row["metrics"]
            if "optimized" not in m:
                print(f"{row['frame']:>5}  insufficient body keypoints  {row['triage']}")
                continue
            o = m["optimized"]
            s = m.get("smoothed", o)
            print(
                f"{row['frame']:>5}  {row['valid_body_keypoints']:>2}/17"
                f"      {o['mesh_keypoint_bbox_iou']:>6.3f}"
                f"       {s['mesh_keypoint_bbox_iou']:>6.3f}"
                f"         {s['center_dx_normalized']:>7.3f}"
                f"       {s['center_dy_normalized']:>7.3f}"
                f"          {s['height_ratio_to_keypoint_bbox']:>6.2f}"
                f"   {row['triage']}"
            )
        print(f"Audited: {len(report['frames'])} frames; "
              f"measured: {report['analyzed_frame_count']}; "
              f"errors: {report['diagnostic_error_count']}")
        for category, count in report["review_category_counts"].items():
            print(f"  {category}: {count}")
        if args.output is not None:
            if args.output.resolve().is_relative_to(args.dataset.resolve()):
                raise FitDiagnosticError("Diagnostic output must not be written inside source dataset")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            print(f"Diagnostic JSON: {args.output}")
        print("Review flags are only heuristics; no frames are cleared for training.")
        return 1 if report["diagnostic_error_count"] else 0
    except (FitDiagnosticError, ValueError, OSError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
