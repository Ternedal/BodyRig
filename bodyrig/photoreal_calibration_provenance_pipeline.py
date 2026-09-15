from __future__ import annotations

from typing import Any, Mapping

from .photoreal_calibration_provenance_authority import validate_calibration_provenance
from .photoreal_frame_identity_authority import authorize_frame_identities
from .photoreal_frame_index import build_frame_index
from .photoreal_teacher_input import build_teacher_input


class PhotorealCalibrationProvenancePipelineError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealCalibrationProvenancePipelineError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealCalibrationProvenancePipelineError(f"{label} is invalid")
    return result


def _provenance(calibration: Mapping[str, Any]) -> tuple[str, str]:
    validated = validate_calibration_provenance(calibration)
    return (
        _sha(validated["negative_inventory_sha256"], label="negative inventory SHA-256"),
        _sha(
            validated["identity_calibration_provenance_sha256"],
            label="identity calibration provenance SHA-256",
        ),
    )


def _require_provenance(
    artifact: Mapping[str, Any],
    *,
    negative_inventory_sha256: str,
    identity_calibration_provenance_sha256: str,
    label: str,
) -> None:
    if _sha(artifact.get("negative_inventory_sha256"), label=f"{label} negative inventory SHA-256") != negative_inventory_sha256:
        raise PhotorealCalibrationProvenancePipelineError(f"{label} targets different negative inventory")
    if _sha(
        artifact.get("identity_calibration_provenance_sha256"),
        label=f"{label} identity calibration provenance SHA-256",
    ) != identity_calibration_provenance_sha256:
        raise PhotorealCalibrationProvenancePipelineError(f"{label} targets different calibration provenance")


def authorize_frame_identities_sealed(
    plan: Mapping[str, Any],
    measurements: Mapping[str, Any],
    bank: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    negative_sha, provenance_sha = _provenance(calibration)
    result = authorize_frame_identities(plan, measurements, bank, calibration)
    result["negative_inventory_sha256"] = negative_sha
    result["identity_calibration_provenance_sha256"] = provenance_sha
    return result


def build_frame_index_sealed(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    authorized_observations: Mapping[str, Any],
) -> dict[str, Any]:
    negative_sha = _sha(
        authorized_observations.get("negative_inventory_sha256"),
        label="frame authority negative inventory SHA-256",
    )
    provenance_sha = _sha(
        authorized_observations.get("identity_calibration_provenance_sha256"),
        label="frame authority identity calibration provenance SHA-256",
    )
    result = build_frame_index(plan, receipt, authorized_observations)
    result["negative_inventory_sha256"] = negative_sha
    result["identity_calibration_provenance_sha256"] = provenance_sha
    return result


def build_teacher_input_sealed(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    frame_index: Mapping[str, Any],
    epoch_selection: Mapping[str, Any],
) -> dict[str, Any]:
    negative_sha = _sha(
        frame_index.get("negative_inventory_sha256"),
        label="frame index negative inventory SHA-256",
    )
    provenance_sha = _sha(
        frame_index.get("identity_calibration_provenance_sha256"),
        label="frame index identity calibration provenance SHA-256",
    )
    result = build_teacher_input(plan, receipt, frame_index, epoch_selection)
    result["negative_inventory_sha256"] = negative_sha
    result["identity_calibration_provenance_sha256"] = provenance_sha
    # The legacy builder sealed before provenance was attached. Re-seal the final
    # teacher manifest so provenance is cryptographically part of teacher authority.
    from .photoreal_teacher_input import _digest

    result.pop("teacher_input_sha256", None)
    result["teacher_input_sha256"] = _digest(result)
    return result
