from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


FORMAT = "bodyrig-anatomy-geometry-audit"
VERSION = 1
BANDS = (
    ("legs", 0.08, 0.42),
    ("hips_waist", 0.42, 0.60),
    ("torso_chest", 0.60, 0.80),
)
GLOBAL_SOURCE_P95_MAX = 0.08
GLOBAL_DONOR_P95_MAX = 0.06
BAND_DISTANCE_P95_MAX = 0.08
BAND_SPAN_RATIO_MIN = 0.60
BAND_SPAN_RATIO_MAX = 1.65


class AnatomyGeometryAuditError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_positions(path: Path) -> list[tuple[float, float, float]]:
    if not path.is_file():
        raise AnatomyGeometryAuditError(f"OBJ is missing: {path}")
    result: list[tuple[float, float, float]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise AnatomyGeometryAuditError(f"OBJ is unreadable: {path}") from exc
    for line in lines:
        if not line.startswith("v "):
            continue
        parts = line.split()
        if len(parts) < 4:
            raise AnatomyGeometryAuditError("OBJ vertex is malformed")
        try:
            xyz = tuple(float(parts[index]) for index in range(1, 4))
        except ValueError as exc:
            raise AnatomyGeometryAuditError("OBJ vertex is non-numeric") from exc
        if not all(math.isfinite(value) for value in xyz):
            raise AnatomyGeometryAuditError("OBJ vertex is non-finite")
        result.append(xyz)  # type: ignore[arg-type]
    if len(result) < 3:
        raise AnatomyGeometryAuditError("OBJ contains too few vertices")
    return result


def _quantile(np: Any, values: Any, q: float) -> float:
    if values.size == 0:
        raise AnatomyGeometryAuditError("anatomy audit region has no vertices")
    result = float(np.quantile(values, q))
    if not math.isfinite(result):
        raise AnatomyGeometryAuditError("anatomy audit metric is non-finite")
    return result


def _robust_span(np: Any, positions: Any, axis: int) -> float:
    values = positions[:, axis]
    span = _quantile(np, values, 0.95) - _quantile(np, values, 0.05)
    if not math.isfinite(span) or span <= 1e-8:
        raise AnatomyGeometryAuditError("anatomy audit span is invalid")
    return span


def summarize_geometry(
    np: Any,
    *,
    donor_positions: Any,
    source_positions: Any,
    source_to_donor: Any,
    donor_to_source: Any,
) -> dict[str, Any]:
    donor = np.asarray(donor_positions, dtype=np.float64)
    source = np.asarray(source_positions, dtype=np.float64)
    s2d = np.asarray(source_to_donor, dtype=np.float64)
    d2s = np.asarray(donor_to_source, dtype=np.float64)
    if donor.ndim != 2 or donor.shape[1] != 3 or source.ndim != 2 or source.shape[1] != 3:
        raise AnatomyGeometryAuditError("anatomy audit positions must be Nx3")
    if s2d.shape != (len(source),) or d2s.shape != (len(donor),):
        raise AnatomyGeometryAuditError("anatomy audit distance arrays do not match geometry")
    if not bool(np.all(np.isfinite(donor))) or not bool(np.all(np.isfinite(source))):
        raise AnatomyGeometryAuditError("anatomy audit positions are non-finite")
    if not bool(np.all(np.isfinite(s2d))) or not bool(np.all(np.isfinite(d2s))) or bool(np.any(s2d < 0.0)) or bool(np.any(d2s < 0.0)):
        raise AnatomyGeometryAuditError("anatomy audit distances are invalid")

    y_min = float(np.min(donor[:, 1]))
    y_max = float(np.max(donor[:, 1]))
    body_height = y_max - y_min
    if not math.isfinite(body_height) or body_height <= 1e-6:
        raise AnatomyGeometryAuditError("donor body height is invalid")

    global_source_p95 = _quantile(np, s2d, 0.95) / body_height
    global_donor_p95 = _quantile(np, d2s, 0.95) / body_height
    bands: dict[str, Any] = {}
    gross_pass = global_source_p95 <= GLOBAL_SOURCE_P95_MAX and global_donor_p95 <= GLOBAL_DONOR_P95_MAX

    donor_y = (donor[:, 1] - y_min) / body_height
    source_y = (source[:, 1] - y_min) / body_height
    for name, low, high in BANDS:
        donor_mask = (donor_y >= low) & (donor_y < high)
        source_mask = (source_y >= low) & (source_y < high)
        donor_region = donor[donor_mask]
        source_region = source[source_mask]
        if len(donor_region) < 16 or len(source_region) < 16:
            raise AnatomyGeometryAuditError(f"anatomy audit band {name} exposes too few vertices")

        source_p95 = _quantile(np, s2d[source_mask], 0.95) / body_height
        donor_p95 = _quantile(np, d2s[donor_mask], 0.95) / body_height
        donor_width = _robust_span(np, donor_region, 0)
        source_width = _robust_span(np, source_region, 0)
        donor_depth = _robust_span(np, donor_region, 2)
        source_depth = _robust_span(np, source_region, 2)
        width_ratio = source_width / donor_width
        depth_ratio = source_depth / donor_depth
        band_pass = (
            source_p95 <= BAND_DISTANCE_P95_MAX
            and donor_p95 <= BAND_DISTANCE_P95_MAX
            and BAND_SPAN_RATIO_MIN <= width_ratio <= BAND_SPAN_RATIO_MAX
            and BAND_SPAN_RATIO_MIN <= depth_ratio <= BAND_SPAN_RATIO_MAX
        )
        gross_pass = gross_pass and band_pass
        bands[name] = {
            "sourceToDonorP95BodyHeightRatio": round(source_p95, 6),
            "donorToSourceP95BodyHeightRatio": round(donor_p95, 6),
            "sourceToDonorWidthRatio": round(width_ratio, 6),
            "sourceToDonorDepthRatio": round(depth_ratio, 6),
            "grossBandPass": bool(band_pass),
        }

    return {
        "bodyHeight": round(body_height, 6),
        "sourceToDonorP95BodyHeightRatio": round(global_source_p95, 6),
        "donorToSourceP95BodyHeightRatio": round(global_donor_p95, 6),
        "bands": bands,
        "grossAnatomyPass": bool(gross_pass),
        "humanReviewRequired": True,
    }


def _nearest_distances(torch: Any, *, query: Any, reference: Any, query_chunk: int = 1024, reference_tile: int = 8192) -> Any:
    count = int(query.shape[0])
    result = torch.empty((count,), dtype=torch.float32, device=query.device)
    with torch.no_grad():
        for start in range(0, count, query_chunk):
            chunk = query[start:start + query_chunk]
            local = torch.full((int(chunk.shape[0]),), float("inf"), dtype=torch.float32, device=query.device)
            for ref_start in range(0, int(reference.shape[0]), reference_tile):
                ref = reference[ref_start:ref_start + reference_tile]
                distances = torch.cdist(chunk.unsqueeze(0), ref.unsqueeze(0)).squeeze(0)
                tile_min = torch.min(distances, dim=1).values
                local = torch.minimum(local, tile_min)
            result[start:start + int(chunk.shape[0])] = local
    return result


def audit_files(*, donor_obj: Path, source_obj: Path) -> dict[str, Any]:
    try:
        import numpy as np
        import torch
    except ImportError as exc:
        raise AnatomyGeometryAuditError(f"numpy and torch are required for anatomy audit: {exc}") from exc
    if not torch.cuda.is_available():
        raise AnatomyGeometryAuditError("anatomy geometry audit requires CUDA")

    donor_values = _parse_positions(donor_obj)
    source_values = _parse_positions(source_obj)
    device = torch.device("cuda")
    donor = torch.tensor(donor_values, dtype=torch.float32, device=device)
    source = torch.tensor(source_values, dtype=torch.float32, device=device)
    source_to_donor = _nearest_distances(torch, query=source, reference=donor)
    donor_to_source = _nearest_distances(torch, query=donor, reference=source)
    metrics = summarize_geometry(
        np,
        donor_positions=donor.detach().cpu().numpy(),
        source_positions=source.detach().cpu().numpy(),
        source_to_donor=source_to_donor.detach().cpu().numpy(),
        donor_to_source=donor_to_source.detach().cpu().numpy(),
    )
    return {
        "format": FORMAT,
        "version": VERSION,
        "donorObjSha256": _sha256(donor_obj),
        "sourceObjSha256": _sha256(source_obj),
        **metrics,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--donor-obj", required=True)
    parser.add_argument("--source-obj", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    try:
        result = audit_files(
            donor_obj=Path(args.donor_obj).expanduser().resolve(),
            source_obj=Path(args.source_obj).expanduser().resolve(),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(
            "BodyRig anatomy geometry audit: "
            f"gross_pass={result['grossAnatomyPass']} "
            f"source_p95={result['sourceToDonorP95BodyHeightRatio']:.6f} "
            f"donor_p95={result['donorToSourceP95BodyHeightRatio']:.6f}"
        )
        return 0 if result["grossAnatomyPass"] else 2
    except Exception as exc:
        print(f"BodyRig anatomy geometry audit: FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
