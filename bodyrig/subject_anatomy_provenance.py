from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping


FORMAT = "bodyrig-subject-anatomy-refit"
VERSION = 1
METHOD_V1 = "explicit-family-smplx-betas-icp-to-retained-sith-source-v1"
METHOD_V2 = "explicit-family-smplx-betas-icp-normal-aware-to-retained-sith-source-v2"
METHOD_V3 = "explicit-family-smplx-betas-icp-bake-surface-normal-aware-to-retained-sith-source-v3"
METHODS = {METHOD_V1, METHOD_V2, METHOD_V3}
NORMAL_ALIGNMENT_AUTHORITY = "nearest-source-vertex-area-weighted-v1"
NORMAL_ALIGNMENT_AUTHORITY_V3 = "sith-closest-source-triangle-face-normal-v1"
NORMAL_SAMPLE_METHOD_V3 = "deterministic-smplx-face-centroids-v1"
NORMAL_NONREGRESSION_TOLERANCE = 1e-4
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MODEL_FAMILIES = {"female", "male", "neutral"}


class SubjectAnatomyProvenanceError(ValueError):
    pass


def sha256_path(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise SubjectAnatomyProvenanceError(f"subject anatomy evidence file is missing: {resolved}")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise SubjectAnatomyProvenanceError(f"{label} is invalid")
    digest = value.strip().lower()
    if not SHA_RE.fullmatch(digest):
        raise SubjectAnatomyProvenanceError(f"{label} is invalid")
    return digest


def _finite_nonnegative(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubjectAnatomyProvenanceError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise SubjectAnatomyProvenanceError(f"{label} is invalid")
    return result


def _finite_alignment(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SubjectAnatomyProvenanceError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or not -1.0 <= result <= 1.0:
        raise SubjectAnatomyProvenanceError(f"{label} is invalid")
    return result


def _finite_vector(value: Any, *, label: str, length: int) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise SubjectAnatomyProvenanceError(f"{label} is invalid")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise SubjectAnatomyProvenanceError(f"{label} is invalid")
        result.append(float(item))
    return result


def validate_subject_anatomy_refit(value: Mapping[str, Any], *, require_non_regression: bool = True) -> dict[str, Any]:
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise SubjectAnatomyProvenanceError("subject anatomy refit evidence format is invalid")
    family = value.get("targetModelFamily")
    if family not in MODEL_FAMILIES:
        raise SubjectAnatomyProvenanceError("subject anatomy refit model family is invalid")
    method = value.get("method")
    if method not in METHODS:
        raise SubjectAnatomyProvenanceError("subject anatomy refit method is invalid")

    initial_p95 = _finite_nonnegative(value.get("initialDonorToSourceP95"), label="initial anatomy p95")
    initial_rms = _finite_nonnegative(value.get("initialDonorToSourceRms"), label="initial anatomy RMS")
    final_p95 = _finite_nonnegative(value.get("finalDonorToSourceP95"), label="final anatomy p95")
    final_rms = _finite_nonnegative(value.get("finalDonorToSourceRms"), label="final anatomy RMS")
    iterations = value.get("iterations")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise SubjectAnatomyProvenanceError("subject anatomy refit iteration count is invalid")

    distance_non_regression = final_p95 <= initial_p95 + 1e-9 and final_rms <= initial_rms + 1e-9
    method_fields: dict[str, Any] = {}
    expected_non_regression = distance_non_regression
    if method in {METHOD_V2, METHOD_V3}:
        initial_normal_mean = _finite_alignment(
            value.get("initialNormalAlignmentMean"), label="initial anatomy normal mean"
        )
        initial_normal_p05 = _finite_alignment(
            value.get("initialNormalAlignmentP05"), label="initial anatomy normal p05"
        )
        final_normal_mean = _finite_alignment(
            value.get("finalNormalAlignmentMean"), label="final anatomy normal mean"
        )
        final_normal_p05 = _finite_alignment(
            value.get("finalNormalAlignmentP05"), label="final anatomy normal p05"
        )
        normal_non_regression = (
            final_normal_mean + NORMAL_NONREGRESSION_TOLERANCE >= initial_normal_mean
            and final_normal_p05 + NORMAL_NONREGRESSION_TOLERANCE >= initial_normal_p05
        )
        claim = value.get("normalAwareNonRegression")
        if type(claim) is not bool or claim is not normal_non_regression:
            raise SubjectAnatomyProvenanceError("subject anatomy normal non-regression claim is inconsistent")
        expected_authority = NORMAL_ALIGNMENT_AUTHORITY if method == METHOD_V2 else NORMAL_ALIGNMENT_AUTHORITY_V3
        if value.get("normalAlignmentAuthority") != expected_authority:
            raise SubjectAnatomyProvenanceError("subject anatomy normal alignment authority is invalid")
        normal_loss_weight = _finite_nonnegative(value.get("normalLossWeight"), label="subject anatomy normal loss weight")
        if normal_loss_weight <= 0.0:
            raise SubjectAnatomyProvenanceError("subject anatomy normal loss weight is invalid")
        expected_non_regression = distance_non_regression and normal_non_regression
        method_fields = {
            "initialNormalAlignmentMean": initial_normal_mean,
            "initialNormalAlignmentP05": initial_normal_p05,
            "finalNormalAlignmentMean": final_normal_mean,
            "finalNormalAlignmentP05": final_normal_p05,
            "normalAwareNonRegression": normal_non_regression,
            "normalAlignmentAuthority": expected_authority,
            "normalLossWeight": normal_loss_weight,
        }
        if method == METHOD_V3:
            if value.get("normalSampleMethod") != NORMAL_SAMPLE_METHOD_V3:
                raise SubjectAnatomyProvenanceError("subject anatomy v3 normal sample method is invalid")
            normal_sample_count = value.get("normalSampleCount")
            if isinstance(normal_sample_count, bool) or not isinstance(normal_sample_count, int) or normal_sample_count < 100:
                raise SubjectAnatomyProvenanceError("subject anatomy v3 normal sample count is invalid")
            method_fields.update(
                {
                    "normalSampleMethod": NORMAL_SAMPLE_METHOD_V3,
                    "normalSampleCount": normal_sample_count,
                }
            )

    non_regression = value.get("fitDidNotRegress")
    if type(non_regression) is not bool:
        raise SubjectAnatomyProvenanceError("subject anatomy non-regression claim is invalid")
    if non_regression is not expected_non_regression:
        raise SubjectAnatomyProvenanceError("subject anatomy non-regression claim is inconsistent")
    if require_non_regression and not non_regression:
        raise SubjectAnatomyProvenanceError("regressed subject anatomy candidate cannot enter package fitting")

    if value.get("poseAuthority") != "retained-sith-fit":
        raise SubjectAnatomyProvenanceError("subject anatomy pose authority is invalid")
    if value.get("shapeAuthority") != "derived-target-family-fit-to-retained-source":
        raise SubjectAnatomyProvenanceError("subject anatomy shape authority is invalid")
    required_boundary = {
        "retainedReconstructionModified": False,
        "reconstructionRerun": False,
        "generativeGeometry": False,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
    }
    for field, expected in required_boundary.items():
        if value.get(field) is not expected:
            raise SubjectAnatomyProvenanceError(f"subject anatomy authority boundary {field} is invalid")

    hashes = {
        field: _sha(value.get(field), label=field)
        for field in (
            "reconstructionSha256",
            "retainedSmplxObjSha256",
            "retainedFitParamsSha256",
            "retainedSourceMeshSha256",
            "derivedSmplxObjSha256",
            "derivedFitParamsSha256",
        )
    }
    derived_scale = _finite_nonnegative(value.get("derivedScale"), label="derived anatomy scale")
    if derived_scale <= 0.0:
        raise SubjectAnatomyProvenanceError("derived anatomy scale is invalid")
    derived_betas = _finite_vector(value.get("derivedBetas"), label="derived anatomy betas", length=10)
    derived_transl = _finite_vector(value.get("derivedTransl"), label="derived anatomy translation", length=3)

    return {
        "format": FORMAT,
        "version": VERSION,
        "targetModelFamily": family,
        "method": method,
        "initialDonorToSourceP95": initial_p95,
        "initialDonorToSourceRms": initial_rms,
        "finalDonorToSourceP95": final_p95,
        "finalDonorToSourceRms": final_rms,
        "iterations": iterations,
        "fitDidNotRegress": non_regression,
        "poseAuthority": "retained-sith-fit",
        "shapeAuthority": "derived-target-family-fit-to-retained-source",
        **method_fields,
        **required_boundary,
        **hashes,
        "derivedScale": derived_scale,
        "derivedBetas": derived_betas,
        "derivedTransl": derived_transl,
    }


def load_subject_anatomy_refit(path: str | Path, *, require_non_regression: bool = True) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise SubjectAnatomyProvenanceError(f"subject anatomy refit evidence is missing: {resolved}")
    try:
        value = json.loads(
            resolved.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SubjectAnatomyProvenanceError("subject anatomy refit evidence is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SubjectAnatomyProvenanceError("subject anatomy refit evidence must be an object")
    return validate_subject_anatomy_refit(value, require_non_regression=require_non_regression)


def provenance_stage(path: str | Path) -> dict[str, str]:
    evidence = load_subject_anatomy_refit(path, require_non_regression=True)
    return {
        "stage": "subject-anatomy-refit",
        "adapter": f"bodyrig.subject_anatomy_refit.{evidence['targetModelFamily']}",
        "revision": sha256_path(path),
    }
