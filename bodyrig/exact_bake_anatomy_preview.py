from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any, Mapping

from .sith_reconstruction_authority import (
    AUTHORITY_FILENAME as RECONSTRUCTION_AUTHORITY_FILENAME,
    SithReconstructionAuthorityError,
    write_reconstruction_authority,
)


LINE_SEARCH_FORMAT = "bodyrig-subject-anatomy-exact-bake-line-search"
LINE_SEARCH_VERSION = 1
LINE_SEARCH_METHOD = "retained-to-v3-fit-parameter-line-search-exact-production-bake-v1"
SCORE_FORMAT = "bodyrig-exact-anatomy-bake-score"
SCORE_VERSION = 1
SCORE_METHOD = "production-anatomy-bake-exact-geometry-score-v1"
WORKSPACE_FORMAT = "bodyrig-exact-bake-anatomy-preview-workspace"
WORKSPACE_VERSION = 1
METRIC_KEYS = (
    "surface_distance_p95_body_ratio",
    "surface_distance_max_body_ratio",
    "normal_alignment_mean",
    "normal_alignment_p05",
    "normal_low_alignment_ratio",
    "normal_retry_texel_ratio",
)
FIXED_FIELDS = (
    "expression",
    "global_orient",
    "body_pose",
    "left_hand_pose",
    "right_hand_pose",
    "jaw_pose",
    "leye_pose",
    "reye_pose",
)


class ExactBakeAnatomyPreviewError(ValueError):
    pass


def sha256_path(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ExactBakeAnatomyPreviewError(f"required preview artifact is missing: {resolved}")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ExactBakeAnatomyPreviewError(f"{label} is missing: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExactBakeAnatomyPreviewError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ExactBakeAnatomyPreviewError(f"{label} must be an object")
    return value


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExactBakeAnatomyPreviewError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise ExactBakeAnatomyPreviewError(f"{label} is non-finite")
    return result


def _fit(path: Path, *, label: str) -> dict[str, list[float]]:
    raw = _read_json(path, label=label)
    result: dict[str, list[float]] = {}
    for field, values in raw.items():
        if not isinstance(field, str) or not isinstance(values, list) or not values:
            raise ExactBakeAnatomyPreviewError(f"{label} has invalid fit field {field!r}")
        converted: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ExactBakeAnatomyPreviewError(f"{label} has non-finite fit values")
            converted.append(float(value))
        result[field] = converted
    required = {"betas", "transl", "scale", *FIXED_FIELDS}
    if set(result) != required:
        raise ExactBakeAnatomyPreviewError(f"{label} fields do not match the retained SiTH fit contract")
    if len(result["betas"]) != 10 or len(result["transl"]) != 3 or len(result["scale"]) != 1:
        raise ExactBakeAnatomyPreviewError(f"{label} shape fields have invalid lengths")
    if result["scale"][0] <= 0.0:
        raise ExactBakeAnatomyPreviewError(f"{label} scale must be positive")
    return result


def _expected_interpolation(
    retained: Mapping[str, list[float]],
    endpoint: Mapping[str, list[float]],
    *,
    alpha: float,
) -> dict[str, list[float]]:
    if not 0.0 < alpha < 1.0:
        raise ExactBakeAnatomyPreviewError("preview alpha must be strictly between 0 and 1")
    if set(retained) != set(endpoint):
        raise ExactBakeAnatomyPreviewError("retained and endpoint fit fields differ")
    for field in FIXED_FIELDS:
        if retained[field] != endpoint[field]:
            raise ExactBakeAnatomyPreviewError(f"endpoint changed retained pose authority: {field}")
    result = {field: list(values) for field, values in retained.items()}
    result["betas"] = [
        (1.0 - alpha) * left + alpha * right
        for left, right in zip(retained["betas"], endpoint["betas"], strict=True)
    ]
    result["transl"] = [
        (1.0 - alpha) * left + alpha * right
        for left, right in zip(retained["transl"], endpoint["transl"], strict=True)
    ]
    result["scale"] = [
        math.exp((1.0 - alpha) * math.log(retained["scale"][0]) + alpha * math.log(endpoint["scale"][0]))
    ]
    return result


def _fit_matches(actual: Mapping[str, list[float]], expected: Mapping[str, list[float]]) -> bool:
    if set(actual) != set(expected):
        return False
    for field in actual:
        left = actual[field]
        right = expected[field]
        if len(left) != len(right):
            return False
        if any(not math.isclose(a, b, rel_tol=0.0, abs_tol=1e-8) for a, b in zip(left, right, strict=True)):
            return False
    return True


def _metric_row(line_search: Mapping[str, Any], *, alpha: float) -> dict[str, float]:
    rows = line_search.get("rows")
    if not isinstance(rows, list):
        raise ExactBakeAnatomyPreviewError("line-search receipt has no metric rows")
    matches: list[dict[str, float]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ExactBakeAnatomyPreviewError("line-search metric row is invalid")
        row_alpha = _finite(raw.get("alpha"), label="line-search alpha")
        if math.isclose(row_alpha, alpha, rel_tol=0.0, abs_tol=1e-12):
            row = {"alpha": row_alpha}
            for key in METRIC_KEYS:
                row[key] = _finite(raw.get(key), label=f"line-search {key}")
            matches.append(row)
    if len(matches) != 1:
        raise ExactBakeAnatomyPreviewError("selected alpha is not represented by exactly one line-search row")
    return matches[0]


def _validate_score(score: Mapping[str, Any], *, row: Mapping[str, float], alpha: float) -> None:
    if score.get("format") != SCORE_FORMAT or score.get("version") != SCORE_VERSION or score.get("method") != SCORE_METHOD:
        raise ExactBakeAnatomyPreviewError("selected point exact-bake score contract is invalid")
    if score.get("resolution") != 1024:
        raise ExactBakeAnatomyPreviewError("selected point was not scored on the exact 1024x1024 production bake")
    required_boundary = {
        "sourceDerived": True,
        "exactProductionBakePath": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "humanFidelityPass": False,
        "productionReady": False,
        "reconstructionRerun": False,
    }
    for field, expected in required_boundary.items():
        if score.get(field) is not expected:
            raise ExactBakeAnatomyPreviewError(f"selected point score authority boundary is invalid: {field}")
    metrics = score.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ExactBakeAnatomyPreviewError("selected point score has no metrics")
    for key in METRIC_KEYS:
        actual = _finite(metrics.get(key), label=f"selected point score {key}")
        if not math.isclose(actual, row[key], rel_tol=0.0, abs_tol=1e-12):
            raise ExactBakeAnatomyPreviewError(f"selected point score does not match line-search row at alpha={alpha:.4f}: {key}")


def stage_preview_workspace(
    *,
    identity_workspace: Path,
    endpoint_refit_dir: Path,
    line_search_dir: Path,
    alpha: float,
    output_workspace: Path,
) -> dict[str, Any]:
    identity_workspace = identity_workspace.expanduser().resolve()
    endpoint_refit_dir = endpoint_refit_dir.expanduser().resolve()
    line_search_dir = line_search_dir.expanduser().resolve()
    output_workspace = output_workspace.expanduser().resolve()
    if not identity_workspace.is_dir() or not endpoint_refit_dir.is_dir() or not line_search_dir.is_dir():
        raise ExactBakeAnatomyPreviewError("preview authority directory is missing")
    if output_workspace.exists():
        raise ExactBakeAnatomyPreviewError(f"preview workspace already exists: {output_workspace}")
    if not math.isfinite(alpha) or not 0.0 < alpha < 1.0:
        raise ExactBakeAnatomyPreviewError("preview alpha must be strictly between 0 and 1")

    line_path = line_search_dir / "line-search.json"
    line = _read_json(line_path, label="exact-bake line-search receipt")
    if line.get("format") != LINE_SEARCH_FORMAT or line.get("version") != LINE_SEARCH_VERSION or line.get("method") != LINE_SEARCH_METHOD:
        raise ExactBakeAnatomyPreviewError("exact-bake line-search receipt contract is invalid")
    for field, expected in {
        "exactProductionBakePath": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "humanFidelityPass": False,
        "productionReady": False,
        "reconstructionRerun": False,
    }.items():
        if line.get(field) is not expected:
            raise ExactBakeAnatomyPreviewError(f"line-search authority boundary is invalid: {field}")
    gender = line.get("gender")
    if gender not in {"female", "male", "neutral"}:
        raise ExactBakeAnatomyPreviewError("line-search gender is invalid")
    row = _metric_row(line, alpha=alpha)

    stage = identity_workspace / "sith-input-v1"
    reconstruction = stage / "reconstruction.json"
    retained_obj = stage / "smplx" / "000_smplx.obj"
    retained_fit_path = stage / "smplx" / "000_fit.json"
    source_obj = stage / "meshes" / "000_reco.obj"
    source_mtl = stage / "meshes" / "000.mtl"
    endpoint_obj = endpoint_refit_dir / "subject_smplx.obj"
    endpoint_fit_path = endpoint_refit_dir / "subject_fit.json"
    endpoint_evidence = endpoint_refit_dir / "subject-anatomy-refit.json"
    for claimed, path, label in (
        (line.get("retainedSmplxObjSha256"), retained_obj, "retained SMPL-X"),
        (line.get("retainedFitParamsSha256"), retained_fit_path, "retained fit"),
        (line.get("endpointSmplxObjSha256"), endpoint_obj, "endpoint SMPL-X"),
        (line.get("endpointFitParamsSha256"), endpoint_fit_path, "endpoint fit"),
        (line.get("endpointEvidenceSha256"), endpoint_evidence, "endpoint evidence"),
    ):
        if not isinstance(claimed, str) or claimed.lower() != sha256_path(path):
            raise ExactBakeAnatomyPreviewError(f"line-search receipt does not bind {label} bytes")

    point_dir = line_search_dir / f"alpha-{alpha:.4f}"
    selected_obj = point_dir / "subject_smplx.obj"
    selected_fit_path = point_dir / "subject_fit.json"
    selected_score_path = point_dir / "exact-bake-score.json"
    selected_score = _read_json(selected_score_path, label="selected exact-bake score")
    _validate_score(selected_score, row=row, alpha=alpha)
    if selected_score.get("gender") != gender:
        raise ExactBakeAnatomyPreviewError("selected point score gender differs from line search")
    if selected_score.get("donorSha256") != sha256_path(selected_obj):
        raise ExactBakeAnatomyPreviewError("selected exact-bake score does not bind selected donor OBJ")
    if selected_score.get("reconstructionSha256") != sha256_path(reconstruction):
        raise ExactBakeAnatomyPreviewError("selected exact-bake score does not bind retained reconstruction")
    if selected_score.get("sourceMeshSha256") != sha256_path(source_obj):
        raise ExactBakeAnatomyPreviewError("selected exact-bake score does not bind retained source mesh")

    retained_fit = _fit(retained_fit_path, label="retained fit")
    endpoint_fit = _fit(endpoint_fit_path, label="endpoint fit")
    selected_fit = _fit(selected_fit_path, label="selected fit")
    expected_fit = _expected_interpolation(retained_fit, endpoint_fit, alpha=alpha)
    if not _fit_matches(selected_fit, expected_fit):
        raise ExactBakeAnatomyPreviewError("selected fit is not the exact retained-to-v3 interpolation for the requested alpha")

    reconstruction_doc = _read_json(reconstruction, label="retained reconstruction")
    details = reconstruction_doc.get("reconstruction")
    if not isinstance(details, dict):
        raise ExactBakeAnatomyPreviewError("retained reconstruction detail block is missing")
    texture_name = details.get("mesh_texture_name")
    if not isinstance(texture_name, str) or not texture_name or Path(texture_name).name != texture_name:
        raise ExactBakeAnatomyPreviewError("retained source texture reference is invalid")
    source_texture = stage / "meshes" / texture_name

    authority_paths = (reconstruction, retained_obj, retained_fit_path, source_obj, source_mtl, source_texture)
    before = {str(path): sha256_path(path) for path in authority_paths}
    created = False
    try:
        shutil.copytree(identity_workspace, output_workspace)
        created = True
        candidate_stage = output_workspace / "sith-input-v1"
        candidate_obj = candidate_stage / "smplx" / "000_smplx.obj"
        candidate_fit = candidate_stage / "smplx" / "000_fit.json"
        shutil.copyfile(selected_obj, candidate_obj)
        shutil.copyfile(selected_fit_path, candidate_fit)
        if sha256_path(candidate_obj) != sha256_path(selected_obj) or sha256_path(candidate_fit) != sha256_path(selected_fit_path):
            raise ExactBakeAnatomyPreviewError("selected fit/OBJ copy hash mismatch")

        candidate_reconstruction_path = candidate_stage / "reconstruction.json"
        candidate_reconstruction = _read_json(candidate_reconstruction_path, label="candidate reconstruction")
        candidate_details = candidate_reconstruction.get("reconstruction")
        if not isinstance(candidate_details, dict):
            raise ExactBakeAnatomyPreviewError("candidate reconstruction detail block is missing")
        candidate_details["smplx_obj_sha256"] = sha256_path(candidate_obj)
        candidate_details["fit_params_sha256"] = sha256_path(candidate_fit)
        candidate_reconstruction_path.write_text(
            json.dumps(candidate_reconstruction, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        authority_path = candidate_stage / RECONSTRUCTION_AUTHORITY_FILENAME
        authority_path.unlink(missing_ok=True)
        try:
            authority = write_reconstruction_authority(output_workspace, body_model_gender=str(gender))
        except SithReconstructionAuthorityError as exc:
            raise ExactBakeAnatomyPreviewError(f"candidate reconstruction authority failed: {exc}") from exc
        candidate_reconstruction_sha = sha256_path(candidate_reconstruction_path)
        if authority.get("reconstruction_sha256") != candidate_reconstruction_sha:
            raise ExactBakeAnatomyPreviewError("candidate reconstruction authority does not bind candidate reconstruction bytes")

        copied_source = candidate_stage / "meshes" / "000_reco.obj"
        copied_mtl = candidate_stage / "meshes" / "000.mtl"
        copied_texture = candidate_stage / "meshes" / texture_name
        for source, copied in ((source_obj, copied_source), (source_mtl, copied_mtl), (source_texture, copied_texture)):
            if sha256_path(source) != sha256_path(copied):
                raise ExactBakeAnatomyPreviewError("preview workspace changed retained source appearance bytes")
        for path in authority_paths:
            if sha256_path(path) != before[str(path)]:
                raise ExactBakeAnatomyPreviewError("preview staging changed retained authority bytes")

        receipt = {
            "format": WORKSPACE_FORMAT,
            "version": WORKSPACE_VERSION,
            "selectedAlpha": alpha,
            "gender": gender,
            "lineSearchSha256": sha256_path(line_path),
            "selectedScoreSha256": sha256_path(selected_score_path),
            "selectedSmplxObjSha256": sha256_path(selected_obj),
            "selectedFitParamsSha256": sha256_path(selected_fit_path),
            "retainedReconstructionSha256": before[str(reconstruction)],
            "retainedSmplxObjSha256": before[str(retained_obj)],
            "retainedFitParamsSha256": before[str(retained_fit_path)],
            "retainedSourceMeshSha256": before[str(source_obj)],
            "candidateReconstructionSha256": candidate_reconstruction_sha,
            "candidateReconstructionAuthoritySha256": sha256_path(authority_path),
            "metrics": {key: row[key] for key in METRIC_KEYS},
            "exactProductionBakePath": True,
            "retainedSourceAppearanceBytesPreserved": True,
            "reconstructionRerun": False,
            "comparisonOnly": True,
            "humanReviewRequired": True,
            "promotionEligible": False,
            "productionReady": False,
        }
        receipt_path = output_workspace / "exact-bake-anatomy-preview-workspace.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return receipt
    except Exception:
        if created:
            shutil.rmtree(output_workspace, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage a non-promotable BodyRig anatomy preview from one exact-bake line-search alpha.")
    parser.add_argument("--identity-workspace", required=True)
    parser.add_argument("--endpoint-refit-dir", required=True)
    parser.add_argument("--line-search-dir", required=True)
    parser.add_argument("--alpha", required=True, type=float)
    parser.add_argument("--output-workspace", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = stage_preview_workspace(
            identity_workspace=Path(args.identity_workspace),
            endpoint_refit_dir=Path(args.endpoint_refit_dir),
            line_search_dir=Path(args.line_search_dir),
            alpha=float(args.alpha),
            output_workspace=Path(args.output_workspace),
        )
    except (OSError, ValueError, ExactBakeAnatomyPreviewError) as exc:
        print(f"BodyRig exact-bake anatomy preview workspace: FAIL: {exc}")
        return 1
    print(
        "BodyRig exact-bake anatomy preview workspace: PASS | "
        f"alpha={float(receipt['selectedAlpha']):.4f} | "
        f"candidate_reconstruction={receipt['candidateReconstructionSha256']} | "
        "comparison_only=true | promotion_eligible=false | production=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
