from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping


FORMAT = "bodyrig-subject-anatomy-refit"
VERSION = 1
METHOD = "explicit-family-smplx-betas-icp-to-retained-sith-source-v1"
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
    if value.get("method") != METHOD:
        raise SubjectAnatomyProvenanceError("subject anatomy refit method is invalid")

    initial_p95 = _finite_nonnegative(value.get("initialDonorToSourceP95"), label="initial anatomy p95")
    initial_rms = _finite_nonnegative(value.get("initialDonorToSourceRms"), label="initial anatomy RMS")
    final_p95 = _finite_nonnegative(value.get("finalDonorToSourceP95"), label="final anatomy p95")
    final_rms = _finite_nonnegative(value.get("finalDonorToSourceRms"), label="final anatomy RMS")
    iterations = value.get("iterations")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise SubjectAnatomyProvenanceError("subject anatomy refit iteration count is invalid")

    non_regression = value.get("fitDidNotRegress")
    if type(non_regression) is not bool:
        raise SubjectAnatomyProvenanceError("subject anatomy non-regression claim is invalid")
    expected_non_regression = final_p95 <= initial_p95 + 1e-9 and final_rms <= initial_rms + 1e-9
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
        "method": METHOD,
        "initialDonorToSourceP95": initial_p95,
        "initialDonorToSourceRms": initial_rms,
        "finalDonorToSourceP95": final_p95,
        "finalDonorToSourceRms": final_rms,
        "iterations": iterations,
        "fitDidNotRegress": non_regression,
        "poseAuthority": "retained-sith-fit",
        "shapeAuthority": "derived-target-family-fit-to-retained-source",
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
