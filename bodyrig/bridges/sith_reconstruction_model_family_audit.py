from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from sith_smplx_vrm_fitter_gender import (
    FIT_MAX_THRESHOLD,
    FIT_RMS_THRESHOLD,
    GENDERS,
    _infer_reconstruction_gender,
    _select_reconstruction_gender,
)


FORMAT = "bodyrig-reconstruction-smplx-family-audit"
VERSION = 1


class ReconstructionModelFamilyAuditError(ValueError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise ReconstructionModelFamilyAuditError(f"retained reconstruction artifact is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_receipt(
    metrics: Mapping[str, tuple[float, float]],
    *,
    authority_gender: str | None = None,
) -> dict[str, Any]:
    authority = authority_gender or _select_reconstruction_gender(metrics)
    if authority not in GENDERS:
        raise ReconstructionModelFamilyAuditError("SMPL-X model-family authority is invalid")
    normalized: dict[str, dict[str, float | bool]] = {}
    for gender in GENDERS:
        if gender not in metrics:
            continue
        raw = metrics[gender]
        if not isinstance(raw, tuple) or len(raw) != 2:
            raise ReconstructionModelFamilyAuditError("SMPL-X fit metrics are invalid")
        fit_max, fit_rms = float(raw[0]), float(raw[1])
        if not math.isfinite(fit_max) or not math.isfinite(fit_rms) or fit_max < 0.0 or fit_rms < 0.0:
            raise ReconstructionModelFamilyAuditError("SMPL-X fit metrics are invalid")
        normalized[gender] = {
            "fitMax": round(fit_max, 9),
            "fitRms": round(fit_rms, 9),
            "withinStrictBounds": bool(fit_max <= FIT_MAX_THRESHOLD and fit_rms <= FIT_RMS_THRESHOLD),
        }
    if authority not in normalized or normalized[authority]["withinStrictBounds"] is not True:
        raise ReconstructionModelFamilyAuditError("SMPL-X authority does not satisfy strict reconstruction bounds")
    if sum(1 for item in normalized.values() if item["withinStrictBounds"] is True) != 1:
        raise ReconstructionModelFamilyAuditError("SMPL-X model-family authority is not unique")
    return {
        "format": FORMAT,
        "version": VERSION,
        "authorityModelFamily": authority,
        "strictFitMaxThreshold": FIT_MAX_THRESHOLD,
        "strictFitRmsThreshold": FIT_RMS_THRESHOLD,
        "fitMetrics": normalized,
        "retainedReconstructionIsAuthority": True,
        "operatorOverrideAllowed": False,
        "geometryModified": False,
        "reconstructionRerun": False,
        "humanReviewRequired": True,
        "productionReady": False,
    }


def audit(*, model_dir: Path, workspace: Path) -> dict[str, Any]:
    authority, metrics = _infer_reconstruction_gender(
        model_dir=str(model_dir),
        workspace=str(workspace),
        asserted_gender=None,
    )
    receipt = build_receipt(metrics, authority_gender=authority)
    stage = workspace / "sith-input-v1" / "smplx"
    receipt["retainedSmplxObjSha256"] = _sha256(stage / "000_smplx.obj")
    receipt["retainedFitParamsSha256"] = _sha256(stage / "000_fit.json")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--bodyrig-workspace", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        print(f"BodyRig reconstruction model-family audit: FAIL: output already exists: {output}")
        return 1
    try:
        receipt = audit(
            model_dir=Path(args.smplx_model_dir).expanduser().resolve(),
            workspace=Path(args.bodyrig_workspace).expanduser().resolve(),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(
            "BodyRig reconstruction model-family audit: PASS | "
            f"authority={receipt['authorityModelFamily']} | "
            f"output={output}"
        )
        return 0
    except Exception as exc:
        print(f"BodyRig reconstruction model-family audit: FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
