from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any, Mapping

FORMAT = "bodyrig-visual-identity"
VERSION = 1
TRACK_RE = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


class VisualIdentityError(ValueError):
    pass


def _integer(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise VisualIdentityError(f"{field} must be an integer in {minimum}..{maximum}")
    return value


def _ratio(value: Any, *, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise VisualIdentityError(f"{field} must be a finite number in 0..1")
    return float(value)


def _nonempty(value: Any, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise VisualIdentityError(f"{field} must contain 1..{maximum} characters")
    return value.strip()


def validate_visual_identity(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Validate build-only visual identity observations.

    The profile is deliberately metadata-only. It may describe what a capture
    adapter observed, but it must never contain source paths, raw frames or a
    biometric/template vector. Those stay inside the private build workspace.
    """

    required = {
        "format",
        "version",
        "adapter",
        "revision",
        "source_count",
        "subject_track_id",
        "capture",
        "coverage",
        "quality",
        "privacy",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise VisualIdentityError("visual identity fields must match v1 exactly")
    if value["format"] != FORMAT or value["version"] != VERSION:
        raise VisualIdentityError("unsupported visual identity format/version")

    _nonempty(value["adapter"], field="adapter", maximum=80)
    _nonempty(value["revision"], field="revision", maximum=160)
    source_count = _integer(value["source_count"], field="source_count", minimum=1, maximum=10)

    track_id = value["subject_track_id"]
    if not isinstance(track_id, str) or not TRACK_RE.fullmatch(track_id):
        raise VisualIdentityError("subject_track_id is invalid")

    capture = value["capture"]
    capture_fields = {
        "observed_frames",
        "face_frames",
        "full_body_frames",
        "side_body_frames",
        "rear_body_frames",
    }
    if not isinstance(capture, Mapping) or set(capture) != capture_fields:
        raise VisualIdentityError("capture fields must match v1 exactly")
    observed = _integer(capture["observed_frames"], field="capture.observed_frames", minimum=1, maximum=10_000_000)
    counts: dict[str, int] = {}
    for key in capture_fields - {"observed_frames"}:
        counts[key] = _integer(capture[key], field=f"capture.{key}", minimum=0, maximum=observed)
    if counts["face_frames"] == 0 and counts["full_body_frames"] == 0:
        raise VisualIdentityError("capture must contain face or full-body observations")

    coverage = value["coverage"]
    coverage_fields = {"face", "hair_or_scalp", "skin", "clothing", "full_body", "back"}
    if not isinstance(coverage, Mapping) or set(coverage) != coverage_fields:
        raise VisualIdentityError("coverage fields must match v1 exactly")
    for key in coverage_fields:
        _ratio(coverage[key], field=f"coverage.{key}")

    quality = value["quality"]
    quality_fields = {"sharpness", "lighting", "visibility"}
    if not isinstance(quality, Mapping) or set(quality) != quality_fields:
        raise VisualIdentityError("quality fields must match v1 exactly")
    for key in quality_fields:
        _ratio(quality[key], field=f"quality.{key}")

    privacy = value["privacy"]
    privacy_fields = {"contains_source_media", "contains_biometric_template"}
    if not isinstance(privacy, Mapping) or set(privacy) != privacy_fields:
        raise VisualIdentityError("privacy fields must match v1 exactly")
    if privacy["contains_source_media"] is not False:
        raise VisualIdentityError("visual identity profile must not contain source media")
    if privacy["contains_biometric_template"] is not False:
        raise VisualIdentityError("visual identity profile must not contain biometric templates")

    # source_count is intentionally consumed above even though it does not
    # affect any heuristic. It is evidence and must never be silently inferred.
    assert source_count >= 1
    return deepcopy(dict(value))
