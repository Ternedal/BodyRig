from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import sith_exact_anatomy_bake_score as exact_score
import sith_smplx_vrm_fitter as base


FORMAT = "bodyrig-subject-anatomy-exact-bake-line-search"
VERSION = 1
METHOD = "retained-to-v3-fit-parameter-line-search-exact-production-bake-v1"
ENDPOINT_METHOD = "explicit-family-smplx-betas-icp-bake-surface-normal-aware-to-retained-sith-source-v3"
DEFAULT_ALPHAS = (0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875)
MAX_INTERMEDIATE_POINTS = 15
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


class SubjectAnatomyLineSearchError(ValueError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise SubjectAnatomyLineSearchError(f"required line-search artifact is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise SubjectAnatomyLineSearchError(f"{label} is missing")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SubjectAnatomyLineSearchError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SubjectAnatomyLineSearchError(f"{label} must be an object")
    return value


def parse_alphas(raw: str | None) -> tuple[float, ...]:
    if raw is None or not raw.strip():
        return DEFAULT_ALPHAS
    values: list[float] = []
    for token in raw.split(","):
        text = token.strip()
        if not text:
            raise SubjectAnatomyLineSearchError("line-search alpha list contains an empty value")
        try:
            value = float(text)
        except ValueError as exc:
            raise SubjectAnatomyLineSearchError("line-search alpha is not numeric") from exc
        if not math.isfinite(value) or not 0.0 < value < 1.0:
            raise SubjectAnatomyLineSearchError("line-search intermediate alpha must be strictly between 0 and 1")
        values.append(value)
    unique = tuple(sorted(set(values)))
    if not unique or len(unique) > MAX_INTERMEDIATE_POINTS:
        raise SubjectAnatomyLineSearchError("line-search alpha count is outside the supported range")
    return unique


def interpolate_fit(
    retained: Mapping[str, list[float]],
    endpoint: Mapping[str, list[float]],
    *,
    alpha: float,
) -> dict[str, list[float]]:
    if not math.isfinite(float(alpha)) or not 0.0 <= float(alpha) <= 1.0:
        raise SubjectAnatomyLineSearchError("line-search alpha is outside range")
    if set(retained) != set(base.FIT_PARAM_LENGTHS) or set(endpoint) != set(base.FIT_PARAM_LENGTHS):
        raise SubjectAnatomyLineSearchError("line-search fit fields do not match BodyRig SiTH v1")
    for field in FIXED_FIELDS:
        left = [float(item) for item in retained[field]]
        right = [float(item) for item in endpoint[field]]
        if left != right:
            raise SubjectAnatomyLineSearchError(f"line-search endpoint changed retained pose authority: {field}")

    a = float(alpha)
    result = {field: [float(item) for item in retained[field]] for field in base.FIT_PARAM_LENGTHS}
    result["betas"] = [
        (1.0 - a) * float(left) + a * float(right)
        for left, right in zip(retained["betas"], endpoint["betas"], strict=True)
    ]
    result["transl"] = [
        (1.0 - a) * float(left) + a * float(right)
        for left, right in zip(retained["transl"], endpoint["transl"], strict=True)
    ]
    retained_scale = float(retained["scale"][0])
    endpoint_scale = float(endpoint["scale"][0])
    if retained_scale <= 0.0 or endpoint_scale <= 0.0:
        raise SubjectAnatomyLineSearchError("line-search scale endpoint is invalid")
    scale = math.exp((1.0 - a) * math.log(retained_scale) + a * math.log(endpoint_scale))
    if not math.isfinite(scale) or scale <= 0.0:
        raise SubjectAnatomyLineSearchError("line-search interpolated scale is invalid")
    result["scale"] = [scale]
    if not all(math.isfinite(float(item)) for values in result.values() for item in values):
        raise SubjectAnatomyLineSearchError("line-search interpolated fit is non-finite")
    return result


def _write_obj(path: Path, *, vertices: Any, faces: list[list[int]]) -> None:
    lines: list[str] = []
    for vertex in vertices:
        lines.append(f"v {float(vertex[0]):.9f} {float(vertex[1]):.9f} {float(vertex[2]):.9f}")
    for face in faces:
        if len(face) != 3:
            raise SubjectAnatomyLineSearchError("line-search SMPL-X topology is not triangular")
        lines.append(f"f {int(face[0]) + 1} {int(face[1]) + 1} {int(face[2]) + 1}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _metric_row(alpha: float, score: Mapping[str, Any]) -> dict[str, float]:
    metrics = score.get("metrics")
    if not isinstance(metrics, Mapping):
        raise SubjectAnatomyLineSearchError("exact bake score exposes no metrics")
    keys = (
        "surface_distance_p95_body_ratio",
        "surface_distance_max_body_ratio",
        "normal_alignment_mean",
        "normal_alignment_p05",
        "normal_low_alignment_ratio",
        "normal_retry_texel_ratio",
    )
    row: dict[str, float] = {"alpha": float(alpha)}
    for key in keys:
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise SubjectAnatomyLineSearchError(f"exact bake score metric is invalid: {key}")
        row[key] = float(value)
    return row


def _endpoint_authority(
    *,
    workspace: Path,
    endpoint_dir: Path,
    gender: str,
) -> tuple[dict[str, list[float]], dict[str, list[float]], Path, Path, dict[str, Any]]:
    stage = workspace / "sith-input-v1"
    reconstruction = stage / "reconstruction.json"
    retained_obj = stage / "smplx" / "000_smplx.obj"
    retained_fit_path = stage / "smplx" / "000_fit.json"
    source_obj = stage / "meshes" / "000_reco.obj"
    endpoint_fit_path = endpoint_dir / "subject_fit.json"
    endpoint_obj = endpoint_dir / "subject_smplx.obj"
    evidence_path = endpoint_dir / "subject-anatomy-refit.json"
    evidence = _read_json(evidence_path, label="v3 subject anatomy endpoint evidence")
    if evidence.get("format") != "bodyrig-subject-anatomy-refit" or evidence.get("version") != 1:
        raise SubjectAnatomyLineSearchError("v3 endpoint evidence format is invalid")
    if evidence.get("method") != ENDPOINT_METHOD or evidence.get("targetModelFamily") != gender:
        raise SubjectAnatomyLineSearchError("line-search endpoint is not the requested v3 model-family candidate")
    expected = {
        "reconstructionSha256": reconstruction,
        "retainedSmplxObjSha256": retained_obj,
        "retainedFitParamsSha256": retained_fit_path,
        "retainedSourceMeshSha256": source_obj,
        "derivedSmplxObjSha256": endpoint_obj,
        "derivedFitParamsSha256": endpoint_fit_path,
    }
    for field, path in expected.items():
        claimed = evidence.get(field)
        if not isinstance(claimed, str) or claimed.lower() != _sha256(path):
            raise SubjectAnatomyLineSearchError(f"line-search endpoint evidence does not bind {field}")
    if evidence.get("comparisonOnly") is not True or evidence.get("productionReady") is not False:
        raise SubjectAnatomyLineSearchError("line-search endpoint authority boundary is invalid")
    retained_fit = base._fit_params(retained_fit_path)
    endpoint_fit = base._fit_params(endpoint_fit_path)
    return retained_fit, endpoint_fit, retained_obj, endpoint_obj, evidence


def run_line_search(
    *,
    sith_repo: Path,
    model_dir: Path,
    workspace: Path,
    endpoint_dir: Path,
    output_dir: Path,
    gender: str,
    alphas: tuple[float, ...],
) -> dict[str, Any]:
    if gender not in exact_score.GENDERS:
        raise SubjectAnatomyLineSearchError("line-search SMPL-X gender is invalid")
    repo = sith_repo.expanduser().resolve()
    models = model_dir.expanduser().resolve()
    retained_workspace = workspace.expanduser().resolve()
    endpoint = endpoint_dir.expanduser().resolve()
    output = output_dir.expanduser().resolve()
    if output.exists():
        raise SubjectAnatomyLineSearchError(f"line-search output already exists: {output}")
    if not repo.is_dir() or not models.is_dir() or not retained_workspace.is_dir() or not endpoint.is_dir():
        raise SubjectAnatomyLineSearchError("line-search authority path is missing")

    try:
        import torch
        from smplx import SMPLX
    except ImportError as exc:
        raise SubjectAnatomyLineSearchError(f"line-search dependencies are unavailable: {exc}") from exc
    if not torch.cuda.is_available():
        raise SubjectAnatomyLineSearchError("exact-bake anatomy line search requires CUDA")

    retained_fit, endpoint_fit, retained_obj, endpoint_obj, endpoint_evidence = _endpoint_authority(
        workspace=retained_workspace,
        endpoint_dir=endpoint,
        gender=gender,
    )
    # This also proves the v3 endpoint did not silently change pose/expression authority.
    interpolate_fit(retained_fit, endpoint_fit, alpha=0.5)

    output.mkdir(parents=True, exist_ok=False)
    device = torch.device("cuda")
    model = None
    try:
        model = SMPLX(
            model_path=str(models),
            gender=gender,
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        ).to(device)
        model.eval()
        raw_faces = getattr(model, "faces_tensor", None)
        if raw_faces is not None:
            faces = [[int(item) for item in row] for row in raw_faces.detach().cpu().tolist()]
        else:
            raw = getattr(model, "faces", None)
            if raw is None:
                raise SubjectAnatomyLineSearchError("licensed SMPL-X model exposes no face topology")
            faces = [[int(item) for item in row] for row in raw.tolist()]
        if not faces or any(len(face) != 3 for face in faces):
            raise SubjectAnatomyLineSearchError("licensed SMPL-X topology is invalid")

        def tensor(values: list[float], width: int) -> Any:
            return torch.tensor(values, dtype=torch.float32, device=device).view(1, width)

        def vertices_for(fit: Mapping[str, list[float]]) -> Any:
            kwargs = {
                "betas": tensor(fit["betas"], 10),
                "expression": tensor(fit["expression"], 10),
                "global_orient": tensor(fit["global_orient"], 3),
                "body_pose": tensor(fit["body_pose"], 63),
                "left_hand_pose": tensor(fit["left_hand_pose"], 45),
                "right_hand_pose": tensor(fit["right_hand_pose"], 45),
                "jaw_pose": tensor(fit["jaw_pose"], 3),
                "leye_pose": tensor(fit["leye_pose"], 3),
                "reye_pose": tensor(fit["reye_pose"], 3),
                "transl": tensor(fit["transl"], 3),
                "return_verts": True,
            }
            with torch.no_grad():
                result = model(**kwargs).vertices[0] * float(fit["scale"][0])
            return result.detach().cpu().numpy()

        rows: list[dict[str, float]] = []
        points = (0.0, *alphas, 1.0)
        for index, alpha in enumerate(points):
            point_dir = output / f"alpha-{alpha:.4f}"
            point_dir.mkdir(parents=True, exist_ok=False)
            if alpha == 0.0:
                donor_obj = retained_obj
                fit = retained_fit
            elif alpha == 1.0:
                donor_obj = endpoint_obj
                fit = endpoint_fit
            else:
                fit = interpolate_fit(retained_fit, endpoint_fit, alpha=alpha)
                donor_obj = point_dir / "subject_smplx.obj"
                _write_obj(donor_obj, vertices=vertices_for(fit), faces=faces)
                (point_dir / "subject_fit.json").write_text(
                    json.dumps(fit, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8",
                )
            score_path = point_dir / "exact-bake-score.json"
            score = exact_score.score(
                sith_repo=repo,
                model_dir=models,
                workspace=retained_workspace,
                donor_obj=donor_obj,
                gender=gender,
                output_file=score_path,
            )
            rows.append(_metric_row(alpha, score))
            metrics = rows[-1]
            print(
                "BodyRig exact-bake line-search point: PASS | "
                f"alpha={alpha:.4f} | "
                f"p95_ratio={metrics['surface_distance_p95_body_ratio']:.6f} | "
                f"max_ratio={metrics['surface_distance_max_body_ratio']:.6f} | "
                f"normal_mean={metrics['normal_alignment_mean']:.6f} | "
                f"normal_p05={metrics['normal_alignment_p05']:.6f} | "
                f"low={metrics['normal_low_alignment_ratio']:.6f} | "
                f"retry={metrics['normal_retry_texel_ratio']:.6f}"
            )
    finally:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "method": METHOD,
        "gender": gender,
        "alphas": [float(value) for value in (0.0, *alphas, 1.0)],
        "retainedSmplxObjSha256": _sha256(retained_obj),
        "retainedFitParamsSha256": _sha256(retained_workspace / "sith-input-v1" / "smplx" / "000_fit.json"),
        "endpointSmplxObjSha256": _sha256(endpoint_obj),
        "endpointFitParamsSha256": _sha256(endpoint / "subject_fit.json"),
        "endpointEvidenceSha256": _sha256(endpoint / "subject-anatomy-refit.json"),
        "endpointMethod": endpoint_evidence["method"],
        "interpolation": {
            "betas": "linear",
            "translation": "linear",
            "scale": "log-linear-positive",
            "poseExpressionAuthority": "retained-unchanged",
        },
        "rows": rows,
        "exactProductionBakePath": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "humanFidelityPass": False,
        "productionReady": False,
        "reconstructionRerun": False,
    }
    summary = output / "line-search.json"
    summary.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sith-repo", required=True)
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--bodyrig-workspace", required=True)
    parser.add_argument("--endpoint-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--gender", required=True, choices=exact_score.GENDERS)
    parser.add_argument("--alphas", required=False, default=None)
    args = parser.parse_args(argv)
    try:
        receipt = run_line_search(
            sith_repo=Path(args.sith_repo),
            model_dir=Path(args.smplx_model_dir),
            workspace=Path(args.bodyrig_workspace),
            endpoint_dir=Path(args.endpoint_dir),
            output_dir=Path(args.output_dir),
            gender=args.gender,
            alphas=parse_alphas(args.alphas),
        )
        print(
            "BodyRig exact-bake anatomy line search: PASS | "
            f"points={len(receipt['rows'])} | comparison_only=true | production=false"
        )
        return 0
    except Exception as exc:
        print(f"BodyRig exact-bake anatomy line search: FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
