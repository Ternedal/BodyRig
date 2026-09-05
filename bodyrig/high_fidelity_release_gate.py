from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .avatar import AvatarError, VRM_SPEC_VERSION, validate_vrm1
from .package import MRBodyError, ValidatedBody, validate_package


CANONICAL_RELEASE_CHECKS = (
    "bodyrig_checkout_clean",
    "preflight_ok",
    "recovery_adapter_pinned",
    "observed_frames_ge_2",
    "source_derived_shape_present",
    "source_derived_motion_present",
    "bodyprint_matches_package",
    "source_count_matches_package",
    "recovery_provenance_matches",
    "avatar_fitting_provenance_present",
    "avatar_is_vrm_1_0",
    "runtime_materialized_from_package",
)


class HighFidelityReleaseGateError(RuntimeError):
    pass


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _exact_stage(provenance: Mapping[str, Any], stage: str) -> dict[str, Any]:
    pipeline = provenance.get("pipeline")
    if not isinstance(pipeline, list):
        raise HighFidelityReleaseGateError("package provenance pipeline is missing")
    matches = [item for item in pipeline if isinstance(item, dict) and item.get("stage") == stage]
    if len(matches) != 1:
        raise HighFidelityReleaseGateError(f"promoted package must contain exactly one {stage} provenance stage")
    return dict(matches[0])


def _source_count(validated: ValidatedBody) -> int:
    source = validated.provenance.get("source")
    if not isinstance(source, dict):
        raise HighFidelityReleaseGateError("package provenance source authority is missing")
    value = source.get("count")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HighFidelityReleaseGateError("package provenance source count is invalid")
    return value


def _source_fact(source_report: Mapping[str, Any], name: str) -> None:
    checks = source_report.get("checks")
    if not isinstance(checks, dict) or checks.get(name) is not True:
        raise HighFidelityReleaseGateError(f"source Gate A did not prove required release invariant: {name}")


def _recovery(source_report: Mapping[str, Any]) -> dict[str, Any]:
    value = source_report.get("recovery")
    if not isinstance(value, dict):
        raise HighFidelityReleaseGateError("source Gate A lacks canonical recovery authority")
    adapter = str(value.get("adapter") or "").strip()
    revision = str(value.get("revision") or "").strip()
    track_id = str(value.get("track_id") or "").strip()
    observed = value.get("observed_frames")
    if not adapter or not revision or not track_id:
        raise HighFidelityReleaseGateError("source Gate A recovery authority is incomplete")
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < 2:
        raise HighFidelityReleaseGateError("source Gate A recovery observed fewer than two frames")
    return {
        "adapter": adapter,
        "revision": revision,
        "track_id": track_id,
        "observed_frames": observed,
    }


def _validate_vrm(package: Path) -> str:
    try:
        with zipfile.ZipFile(package, "r") as archive:
            document = validate_vrm1(archive.read("avatar.vrm"))
    except (OSError, zipfile.BadZipFile, KeyError, AvatarError) as exc:
        raise HighFidelityReleaseGateError(f"promoted package avatar is not canonical VRM 1.0: {exc}") from exc
    try:
        version = str(document["extensions"]["VRMC_vrm"]["specVersion"])
    except (KeyError, TypeError) as exc:
        raise HighFidelityReleaseGateError("promoted package avatar lacks VRM spec authority") from exc
    if version != VRM_SPEC_VERSION:
        raise HighFidelityReleaseGateError(f"promoted package VRM version is {version!r}, expected {VRM_SPEC_VERSION!r}")
    return version


def validate_promoted_release_lineage(
    promoted_package: str | Path,
    *,
    source_dir: str | Path,
    source_gate: Any,
    source_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-prove release invariants on final promoted bytes.

    Recovery/preflight observations are inherited only from an already-valid source Gate A.
    Package-derived facts are recomputed against the final promoted package so final release
    never relies on copied booleans for bodyprint, provenance, source count, fitting or VRM.
    """

    promoted_path = Path(promoted_package).expanduser().resolve()
    source_root = Path(source_dir).expanduser().resolve()
    body_id = str(getattr(source_gate, "body_id", "") or "")
    source_hash = str(getattr(source_gate, "package_hash", "") or "").lower()
    if not body_id or len(source_hash) != 64:
        raise HighFidelityReleaseGateError("source Gate A package authority is incomplete")

    source_package = source_root / f"{body_id}.mrbody"
    if not source_package.is_file() or _hash(source_package) != source_hash:
        raise HighFidelityReleaseGateError("source Gate A package bytes no longer match source authority")

    try:
        source = validate_package(source_package)
        promoted = validate_package(promoted_path)
    except MRBodyError as exc:
        raise HighFidelityReleaseGateError(f"release-lineage package validation failed: {exc}") from exc

    if str(source.manifest.get("id") or "") != body_id or str(promoted.manifest.get("id") or "") != body_id:
        raise HighFidelityReleaseGateError("promoted package body identity differs from source Gate A")

    # These source-only facts came from the recovery proof / rig preflight and are valid to
    # carry forward only because the source Gate A itself has already been revalidated.
    for name in (
        "preflight_ok",
        "recovery_adapter_pinned",
        "observed_frames_ge_2",
        "source_derived_shape_present",
        "source_derived_motion_present",
        "bodyprint_matches_package",
        "source_count_matches_package",
        "recovery_provenance_matches",
        "avatar_fitting_provenance_present",
        "avatar_is_vrm_1_0",
        "runtime_materialized_from_package",
    ):
        _source_fact(source_report, name)
    if source_report.get("bodyrig_checkout_clean") is not True:
        raise HighFidelityReleaseGateError("source Gate A was not produced from a clean checkout")

    recovery = _recovery(source_report)
    source_count = source_report.get("source_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count < 1:
        raise HighFidelityReleaseGateError("source Gate A source_count is invalid")

    # Anatomy continuation explicitly preserves BodyPrint; all subsequent component
    # promotions rewrite avatar.vrm only. Requiring byte-semantic BodyPrint equality here
    # turns that design promise into final-release authority.
    if promoted.bodyprint != source.bodyprint:
        raise HighFidelityReleaseGateError("promoted package BodyPrint differs from physical source Gate A")
    if _source_count(promoted) != source_count or _source_count(source) != source_count:
        raise HighFidelityReleaseGateError("promoted package source count differs from physical source Gate A")

    shape = promoted.bodyprint.get("shape")
    motion = promoted.bodyprint.get("motion")
    if not isinstance(shape, dict) or not all(
        key in shape for key in ("shoulder_to_height", "hip_to_height", "arm_to_height", "leg_to_height")
    ):
        raise HighFidelityReleaseGateError("promoted package lacks source-derived BodyPrint shape authority")
    if not isinstance(motion, dict) or "energy" not in motion or not any(
        key in motion for key in ("gesture_amplitude", "head_motion")
    ):
        raise HighFidelityReleaseGateError("promoted package lacks source-derived BodyPrint motion authority")

    source_recovery = _exact_stage(source.provenance, "body-recovery")
    promoted_recovery = _exact_stage(promoted.provenance, "body-recovery")
    expected_recovery = {"adapter": recovery["adapter"], "revision": recovery["revision"]}
    for value, label in ((source_recovery, "source"), (promoted_recovery, "promoted")):
        if value.get("adapter") != expected_recovery["adapter"] or value.get("revision") != expected_recovery["revision"]:
            raise HighFidelityReleaseGateError(f"{label} package recovery provenance differs from source Gate A")

    source_visual = _exact_stage(source.provenance, "visual-identity-capture")
    promoted_visual = _exact_stage(promoted.provenance, "visual-identity-capture")
    if promoted_visual != source_visual:
        raise HighFidelityReleaseGateError("promoted package visual-identity provenance differs from physical source package")

    source_fitting = _exact_stage(source.provenance, "avatar-fitting")
    promoted_fitting = _exact_stage(promoted.provenance, "avatar-fitting")
    if source_fitting.get("adapter") != "sith-smplx-vrm" or source_fitting.get("revision") != "1":
        raise HighFidelityReleaseGateError("source package lacks canonical sith-smplx-vrm v1 fitting provenance")
    if promoted_fitting.get("adapter") != "sith-smplx-vrm" or promoted_fitting.get("revision") != "1":
        raise HighFidelityReleaseGateError("promoted package lacks canonical sith-smplx-vrm v1 fitting provenance")

    vrm_spec = _validate_vrm(promoted_path)
    return {
        "source_count": source_count,
        "recovery": recovery,
        "vrm_spec_version": vrm_spec,
        "bodyprint_sha256": _canonical_json_sha256(promoted.bodyprint),
        "source_package_sha256": source_hash,
        "source_bodyprint_sha256": _canonical_json_sha256(source.bodyprint),
        "recovery_provenance": promoted_recovery,
        "visual_identity_provenance": promoted_visual,
        "avatar_fitting_provenance": promoted_fitting,
        "checks": {name: True for name in CANONICAL_RELEASE_CHECKS},
    }
