from __future__ import annotations

import argparse
import json
import math
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .skin_qa import _parse_glb

FORMAT = "bodyrig-appearance-bake-diagnostics"
VERSION = 1
ANATOMY_METHOD = "canonical-smplx-anatomy-normal-bake-v2"

# Diagnostic only: these thresholds do not constitute human fidelity acceptance.
# Normal thresholds are tied to the bake's own NORMAL_RETRY_COSINE=0.50 contract;
# distance thresholds are normalized by the fitted body's diagonal scale.
REVIEW_SURFACE_P95_RATIO = 0.015
HIGH_SURFACE_P95_RATIO = 0.050
REVIEW_SURFACE_MAX_RATIO = 0.040
HIGH_SURFACE_MAX_RATIO = 0.120
REVIEW_NORMAL_P05 = 0.50
HIGH_NORMAL_P05 = 0.00
REVIEW_LOW_ALIGNMENT_RATIO = 0.05
HIGH_LOW_ALIGNMENT_RATIO = 0.20
REVIEW_RETRY_RATIO = 0.25
HIGH_RETRY_RATIO = 0.50


class AppearanceBakeDiagnosticsError(ValueError):
    pass


def _number(
    source: Mapping[str, Any],
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = source.get(name)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise AppearanceBakeDiagnosticsError(f"appearance metric {name} is missing or invalid")
    value = float(raw)
    if not math.isfinite(value):
        raise AppearanceBakeDiagnosticsError(f"appearance metric {name} is non-finite")
    if minimum is not None and value < minimum:
        raise AppearanceBakeDiagnosticsError(f"appearance metric {name} is outside range")
    if maximum is not None and value > maximum:
        raise AppearanceBakeDiagnosticsError(f"appearance metric {name} is outside range")
    return value


def classify_appearance_transfer(appearance: Mapping[str, Any]) -> dict[str, Any]:
    if appearance.get("method") != ANATOMY_METHOD:
        raise AppearanceBakeDiagnosticsError(
            "appearance diagnostics require canonical anatomy-aware SMPL-X bake metadata"
        )

    body_scale = _number(appearance, "bodyScale", minimum=1e-6)
    surface_p95 = _number(appearance, "nearestSourceSurfaceDistanceP95", minimum=0.0)
    surface_max = _number(appearance, "nearestSourceSurfaceDistanceMax", minimum=0.0)
    alignment_mean = _number(appearance, "normalAlignmentMean", minimum=-1.0, maximum=1.0)
    alignment_p05 = _number(appearance, "normalAlignmentP05", minimum=-1.0, maximum=1.0)
    low_alignment = _number(appearance, "normalLowAlignmentRatio", minimum=0.0, maximum=1.0)
    retry_ratio = _number(appearance, "normalRetryTexelRatio", minimum=0.0, maximum=1.0)
    occupied_ratio = _number(appearance, "occupiedTexelRatio", minimum=0.0, maximum=1.0)
    padded_ratio = _number(appearance, "paddedTexelRatio", minimum=0.0, maximum=1.0)

    surface_p95_ratio = surface_p95 / body_scale
    surface_max_ratio = surface_max / body_scale
    high: list[str] = []
    review: list[str] = []

    def flag(value: float, review_limit: float, high_limit: float, label: str) -> None:
        if value > high_limit:
            high.append(label)
        elif value > review_limit:
            review.append(label)

    flag(
        surface_p95_ratio,
        REVIEW_SURFACE_P95_RATIO,
        HIGH_SURFACE_P95_RATIO,
        "source-surface p95 distance is large relative to body scale",
    )
    flag(
        surface_max_ratio,
        REVIEW_SURFACE_MAX_RATIO,
        HIGH_SURFACE_MAX_RATIO,
        "source-surface maximum distance is large relative to body scale",
    )
    flag(
        low_alignment,
        REVIEW_LOW_ALIGNMENT_RATIO,
        HIGH_LOW_ALIGNMENT_RATIO,
        "too many baked texels remain below the normal-alignment retry cosine",
    )
    flag(
        retry_ratio,
        REVIEW_RETRY_RATIO,
        HIGH_RETRY_RATIO,
        "too many baked texels required normal-aware source retries",
    )
    if alignment_p05 < HIGH_NORMAL_P05:
        high.append("normal-alignment p05 is opposite-facing")
    elif alignment_p05 < REVIEW_NORMAL_P05:
        review.append("normal-alignment p05 remains below the bake retry cosine")

    if padded_ratio + 1e-9 < occupied_ratio:
        raise AppearanceBakeDiagnosticsError("appearance atlas padded coverage is below occupied coverage")

    risk = "high-risk" if high else "review" if review else "nominal"
    reasons = high + review
    return {
        "diagnostic_risk": risk,
        "reasons": reasons,
        "metrics": {
            "body_scale": round(body_scale, 6),
            "surface_distance_p95": round(surface_p95, 6),
            "surface_distance_max": round(surface_max, 6),
            "surface_distance_p95_body_ratio": round(surface_p95_ratio, 6),
            "surface_distance_max_body_ratio": round(surface_max_ratio, 6),
            "normal_alignment_mean": round(alignment_mean, 6),
            "normal_alignment_p05": round(alignment_p05, 6),
            "normal_low_alignment_ratio": round(low_alignment, 6),
            "normal_retry_texel_ratio": round(retry_ratio, 6),
            "occupied_texel_ratio": round(occupied_ratio, 6),
            "padded_texel_ratio": round(padded_ratio, 6),
        },
        "manual_review_required": True,
        "human_fidelity_pass": False,
    }


def inspect_package(path: str | Path) -> dict[str, Any]:
    package = Path(path).expanduser().resolve()
    if not package.is_file():
        raise AppearanceBakeDiagnosticsError(f"package not found: {package}")
    try:
        with zipfile.ZipFile(package, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise AppearanceBakeDiagnosticsError("package avatar.vrm is unavailable") from exc

    document, _binary = _parse_glb(avatar)
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    appearance = bodyrig.get("appearanceTransfer") if isinstance(bodyrig, dict) else None
    if not isinstance(appearance, dict):
        raise AppearanceBakeDiagnosticsError("avatar has no BodyRig appearanceTransfer metadata")

    result = classify_appearance_transfer(appearance)
    result.update(
        {
            "format": FORMAT,
            "version": VERSION,
            "package": str(package),
            "appearance_method": str(appearance.get("method") or ""),
            "source_derived": appearance.get("generativeAppearanceSynthesis") is False,
            "acceptance_semantics": "diagnostic-only-not-human-pass",
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only diagnostics for BodyRig source-derived anatomy texture bake quality."
    )
    parser.add_argument("package", help="BodyRig .mrbody package")
    args = parser.parse_args(argv)
    try:
        result = inspect_package(args.package)
    except (AppearanceBakeDiagnosticsError, OSError, ValueError) as exc:
        print(f"BodyRig appearance bake diagnostics: ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["diagnostic_risk"] == "nominal" else 3


if __name__ == "__main__":
    raise SystemExit(main())
