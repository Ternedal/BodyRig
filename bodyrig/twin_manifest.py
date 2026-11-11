"""Read and verify a POSE_READY twin output (#1397 interop, #1398 slice 1a).

``bodyrig.twin_pose.export_pose`` writes three files into a private directory:
``motion.bvh``, ``motion.json`` and ``digital_twin_manifest.json``
(``bodyrig-digital-twin-manifest`` v1). This module is the one place that reads them back
for a consumer: the scene inspector, a later ModelRig hand-off or Kaliv. It fails closed
and returns a typed :class:`TwinManifest` only when every check passes:

1. the directory and each file are real (no symlink anywhere on the path) and bounded;
2. the manifest is strict JSON: no ``NaN``/``Infinity`` and no duplicate key;
3. format and version, and exactly the v1 top-level keys (a v2 bumps the version);
4. ``manifest_sha256`` equals the canonical digest of the rest of the manifest;
5. the fixed parts: state ``POSE_READY``, mesh ``unavailable``, the SMPL-X 22-joint
   skeleton, the documented coordinate system, the motion source and its stage;
6. every safety flag is exactly ``false``: likeness authority, identity claim, cloud
   transfer, ModelRig transfer, production activation;
7. each artifact's size and SHA-256 match the bytes on disk, and there is exactly one
   ``motion.bvh`` and one ``motion.json``;
8. ``motion.json`` and ``motion.bvh`` agree with the manifest: the same source, skeleton
   and coordinate system, the sample counts, the BVH joint order and frame count.

The digest detects accidental change, not tampering: it is not keyed, so anyone who can
write the directory can recompute it. Authenticity comes from the directory being private
(``export_pose`` makes it 0700). Standard library only.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .twin_pose import (
    BVH_FRAME_TIME,
    COORDINATE_SYSTEM,
    JOINTS,
    MANIFEST_FORMAT,
    MOTION_FORMAT,
    PARENTS,
    RELATIONS,
    SKELETON,
    SOURCES,
    VERSION,
    TwinPoseError,
    _canonical_digest,
    _real_directory,
    _read_regular,
    hierarchy_order,
)

MANIFEST_NAME = "digital_twin_manifest.json"
ARTIFACT_NAMES = ("motion.bvh", "motion.json")
MAX_MANIFEST_BYTES = 1 << 20
# motion.json is about 2-3 KB per sample and motion.bvh under 1 KB; 128 MiB is far above a
# 20,000-sample clip.
MAX_ARTIFACT_BYTES = 128 << 20

SAFETY_FLAGS = ("likeness_authority", "identity_claim", "cloud_transfer", "modelrig_transfer",
                "production_activation")
TOP_LEVEL_KEYS = frozenset({
    "format", "version", "state", "mesh", "motion_source", "workspace_sha256", "preprocess_state_sha256",
    "consent", "skeleton", "coordinate_system", "timing", "eye", "invalid_samples", "multi_person_detection",
    "keypoint_gate", "preprocess_stage_timings", "artifacts", "manifest_sha256", *SAFETY_FLAGS,
})
SKELETON_KEYS = frozenset({"name", "rest_pose", "template_model_sha256", "joint_count"})
REST_POSE = "SMPL-X neutral template, zero shape"
TIMING_KEYS = frozenset({"samples", "valid_samples", "first_timestamp_seconds", "last_timestamp_seconds",
                         "bvh_frame_time_seconds", "bvh_timing"})
GATE_KEYS = frozenset({"applied", "reason_not_applied", "metric", "max_error", "min_score", "min_pairs",
                       "skeleton", "checked", "unchecked", "rejected"})
EYES = ("mono", "left", "right")
_SHA = re.compile(r"[0-9a-f]{64}")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}")
_STAGE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
# The BVH root has 6 channels and every other joint 3 (twin_pose.write_bvh).
BVH_VALUES_PER_FRAME = 6 + 3 * (len(JOINTS) - 1)


class TwinManifestError(TwinPoseError):
    """The twin output is not a verified POSE_READY output; the message names the first failing check."""


@dataclass(frozen=True)
class TwinManifest:
    """A verified POSE_READY output. Paths are the verified files; ``raw`` is the whole manifest, read-only."""

    directory: Path
    manifest_sha256: str
    source: str
    preprocess_stage: str
    workspace_sha256: str
    consent_sha256: str
    subject_relation: str
    template_model_sha256: str
    samples: int
    valid_samples: int
    eye: str
    keypoint_gate_applied: bool
    motion_bvh: Path
    motion_json: Path
    artifacts: Mapping[str, Mapping[str, Any]] = field(repr=False)
    raw: Mapping[str, Any] = field(repr=False)


# --- strict parsing ------------------------------------------------------------------------


def _reject_constant(token: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {token}")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant, object_pairs_hook=_no_duplicates)
    except (UnicodeDecodeError, ValueError):
        raise TwinManifestError(f"{label} is not strict JSON") from None
    if not isinstance(value, dict):
        raise TwinManifestError(f"{label} must be a JSON object")
    return value


def _int(value: Any, *, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise TwinManifestError(f"{label} is not a lowercase SHA-256")
    return value


def _exact_keys(value: Any, keys: frozenset[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TwinManifestError(f"{label} must be an object")
    if set(value) != keys:
        missing, extra = sorted(keys - set(value)), sorted(set(value) - keys)
        raise TwinManifestError(f"{label} keys differ from v1 (missing {missing}, unexpected {extra})")
    return value


# --- the manifest --------------------------------------------------------------------------


def _check_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("format") != MANIFEST_FORMAT:
        raise TwinManifestError("manifest format is not bodyrig-digital-twin-manifest")
    version = manifest.get("version")
    if isinstance(version, bool) or version != VERSION:
        raise TwinManifestError(f"manifest version is not {VERSION}")
    _exact_keys(manifest, TOP_LEVEL_KEYS, label="manifest")
    digest = _sha(manifest["manifest_sha256"], label="manifest_sha256")
    if _canonical_digest(manifest, omit="manifest_sha256") != digest:
        raise TwinManifestError("manifest_sha256 does not match the manifest")

    if manifest["state"] != "POSE_READY":
        raise TwinManifestError("manifest state is not POSE_READY")
    if manifest["mesh"] != "unavailable":
        raise TwinManifestError("manifest mesh is not 'unavailable'")
    for flag in SAFETY_FLAGS:
        if manifest[flag] is not False:
            raise TwinManifestError(f"safety flag {flag} is not false")
    if manifest["coordinate_system"] != COORDINATE_SYSTEM:
        raise TwinManifestError("coordinate system differs from the documented output frame")

    motion_source = _exact_keys(manifest["motion_source"], frozenset({"source", "preprocess_stage"}),
                                label="motion_source")
    if motion_source["source"] not in SOURCES:
        raise TwinManifestError("motion source is not init or smoothed")
    if motion_source["preprocess_stage"] != SOURCES[motion_source["source"]][0]:
        raise TwinManifestError("motion source and preprocess stage do not belong together")

    skeleton = _exact_keys(manifest["skeleton"], SKELETON_KEYS, label="skeleton")
    if skeleton["name"] != SKELETON or skeleton["joint_count"] != len(JOINTS) \
            or isinstance(skeleton["joint_count"], bool) or skeleton["rest_pose"] != REST_POSE:
        raise TwinManifestError("skeleton is not the SMPL-X 22-joint body template")
    _sha(skeleton["template_model_sha256"], label="template_model_sha256")

    consent = _exact_keys(manifest["consent"], frozenset({"consent_sha256", "subject_relation"}), label="consent")
    _sha(consent["consent_sha256"], label="consent_sha256")
    if consent["subject_relation"] not in RELATIONS:
        raise TwinManifestError("consent subject relation is not self or consenting-adult")
    _sha(manifest["workspace_sha256"], label="workspace_sha256")
    _sha(manifest["preprocess_state_sha256"], label="preprocess_state_sha256")

    timing = _exact_keys(manifest["timing"], TIMING_KEYS, label="timing")
    samples, valid = timing["samples"], timing["valid_samples"]
    if not _int(samples, minimum=1) or not _int(valid, minimum=1) or valid > samples:
        raise TwinManifestError("timing sample counts are invalid")
    first, last = timing["first_timestamp_seconds"], timing["last_timestamp_seconds"]
    if not _number(first) or not _number(last) or float(first) < 0 or float(first) > float(last):
        raise TwinManifestError("timing timestamps are invalid")
    if timing["bvh_frame_time_seconds"] != round(BVH_FRAME_TIME, 6) or not isinstance(timing["bvh_timing"], str):
        raise TwinManifestError("timing BVH frame time differs from the nominal rate")

    if manifest["eye"] not in EYES:
        raise TwinManifestError("eye is not mono, left or right")
    invalid = manifest["invalid_samples"]
    if not isinstance(invalid, list) or invalid != sorted(set(invalid)) \
            or not all(isinstance(r, str) and _REASON.fullmatch(r) for r in invalid):
        raise TwinManifestError("invalid_samples is not a sorted list of reason codes")
    if (valid < samples) != bool(invalid):
        raise TwinManifestError("invalid_samples does not agree with the sample counts")
    if not isinstance(manifest["multi_person_detection"], str):
        raise TwinManifestError("multi_person_detection is not a statement")

    gate = _exact_keys(manifest["keypoint_gate"], GATE_KEYS, label="keypoint_gate")
    if not isinstance(gate["applied"], bool):
        raise TwinManifestError("keypoint_gate.applied is not a boolean")
    if not all(_int(gate[k], minimum=0) for k in ("checked", "unchecked", "rejected")) \
            or gate["rejected"] > gate["checked"] or gate["checked"] + gate["unchecked"] > samples:
        raise TwinManifestError("keypoint_gate counts are invalid")
    if gate["applied"]:
        if motion_source["source"] != "smoothed" or gate["reason_not_applied"] is not None:
            raise TwinManifestError("keypoint_gate is applied to a source it cannot check")
    elif gate["reason_not_applied"] is None or not isinstance(gate["reason_not_applied"], str) \
            or gate["checked"] or gate["unchecked"] or gate["rejected"]:
        raise TwinManifestError("keypoint_gate not applied but has counts or no reason")
    if not (_number(gate["max_error"]) and 0 < float(gate["max_error"]) <= 1
            and _number(gate["min_score"]) and 0 <= float(gate["min_score"]) <= 1
            and _int(gate["min_pairs"], minimum=1)
            and isinstance(gate["metric"], str) and isinstance(gate["skeleton"], str)):
        raise TwinManifestError("keypoint_gate thresholds are invalid")

    timings = manifest["preprocess_stage_timings"]
    if not isinstance(timings, list) or not all(
            isinstance(t, dict) and set(t) == {"stage", "state", "elapsed_seconds"}
            and isinstance(t["stage"], str) and _STAGE.fullmatch(t["stage"])
            and isinstance(t["state"], str) and _STAGE.fullmatch(t["state"])
            and _number(t["elapsed_seconds"]) for t in timings):
        raise TwinManifestError("preprocess_stage_timings carry more than stage, state and elapsed seconds")


def _check_artifacts(directory: Path, artifacts: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(artifacts, list) or len(artifacts) != len(ARTIFACT_NAMES):
        raise TwinManifestError("artifacts must list exactly motion.bvh and motion.json")
    by_name: dict[str, dict[str, Any]] = {}
    for entry in artifacts:
        record = _exact_keys(entry, frozenset({"name", "size_bytes", "sha256"}), label="artifact")
        name = record["name"]
        if name not in ARTIFACT_NAMES or name in by_name:
            raise TwinManifestError("artifacts must list exactly motion.bvh and motion.json")
        if not _int(record["size_bytes"], minimum=1):
            raise TwinManifestError(f"artifact {name} size is invalid")
        by_name[name] = {"size_bytes": record["size_bytes"], "sha256": _sha(record["sha256"], label=f"{name} sha256")}
    return by_name


def _read_artifact(directory: Path, name: str, record: Mapping[str, Any]) -> bytes:
    import hashlib

    try:
        data = _read_regular(directory / name, within=directory, label=name, limit=MAX_ARTIFACT_BYTES)
    except TwinManifestError:
        raise
    except TwinPoseError as exc:
        raise TwinManifestError(str(exc)) from None
    if len(data) != record["size_bytes"]:
        raise TwinManifestError(f"{name} size differs from the manifest")
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise TwinManifestError(f"{name} SHA-256 differs from the manifest")
    return data


def _check_motion_json(data: bytes, manifest: Mapping[str, Any]) -> None:
    motion = _strict_object(data, label="motion.json")
    version = motion.get("version")
    if motion.get("format") != MOTION_FORMAT or isinstance(version, bool) or version != VERSION:
        raise TwinManifestError("motion.json format/version mismatch")
    if motion.get("source") != manifest["motion_source"]["source"]:
        raise TwinManifestError("motion.json source differs from the manifest")
    skeleton = motion.get("skeleton")
    if not isinstance(skeleton, dict) or skeleton.get("name") != SKELETON \
            or skeleton.get("joints") != list(JOINTS) or skeleton.get("parents") != list(PARENTS) \
            or skeleton.get("bvh_joint_order") != [JOINTS[i] for i in hierarchy_order()] \
            or skeleton.get("template_model_sha256") != manifest["skeleton"]["template_model_sha256"]:
        raise TwinManifestError("motion.json skeleton differs from the manifest")
    if motion.get("coordinate_system") != COORDINATE_SYSTEM:
        raise TwinManifestError("motion.json coordinate system differs from the manifest")
    frames = motion.get("frames")
    if not isinstance(frames, list) or len(frames) != manifest["timing"]["samples"]:
        raise TwinManifestError("motion.json frame count differs from the manifest")
    valid = [f for f in frames if isinstance(f, dict) and f.get("valid") is True]
    if len(valid) != manifest["timing"]["valid_samples"] \
            or [f.get("bvh_frame") for f in valid] != list(range(len(valid))):
        raise TwinManifestError("motion.json valid samples differ from the manifest")


def _check_bvh(data: bytes, manifest: Mapping[str, Any]) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise TwinManifestError("motion.bvh is not UTF-8") from None
    head, separator, motion = text.partition("MOTION\n")
    if not separator or not head.startswith("HIERARCHY\n"):
        raise TwinManifestError("motion.bvh has no HIERARCHY/MOTION sections")
    declared = [line.split()[1] for line in head.splitlines()
                if line.strip().startswith(("ROOT ", "JOINT ")) and len(line.split()) == 2]
    if declared != [JOINTS[i] for i in hierarchy_order()]:
        raise TwinManifestError("motion.bvh joint order differs from the SMPL-X body skeleton")
    lines = motion.splitlines()
    if len(lines) < 2 or not lines[0].startswith("Frames: ") or not lines[1].startswith("Frame Time: "):
        raise TwinManifestError("motion.bvh MOTION header is malformed")
    try:
        frames = int(lines[0].split()[1])
    except (IndexError, ValueError):
        raise TwinManifestError("motion.bvh frame count is malformed") from None
    rows = lines[2:]
    if frames != manifest["timing"]["valid_samples"] or len(rows) != frames:
        raise TwinManifestError("motion.bvh frame count differs from the manifest")
    for row in rows:
        values = row.split()
        if len(values) != BVH_VALUES_PER_FRAME:
            raise TwinManifestError("motion.bvh has a frame with the wrong number of channels")
        try:
            if not all(math.isfinite(float(v)) for v in values):
                raise ValueError
        except ValueError:
            raise TwinManifestError("motion.bvh has a non-finite value") from None


# --- the whole check -----------------------------------------------------------------------


def verify_twin_output(directory: str | Path) -> TwinManifest:
    """Verify a POSE_READY output directory and return its typed manifest; fail closed otherwise."""
    try:
        root = _real_directory(Path(directory), label="twin output directory")
        raw = _read_regular(root / MANIFEST_NAME, within=root, label=MANIFEST_NAME, limit=MAX_MANIFEST_BYTES)
    except TwinManifestError:
        raise
    except TwinPoseError as exc:
        raise TwinManifestError(str(exc)) from None
    manifest = _strict_object(raw, label=MANIFEST_NAME)
    _check_manifest(manifest)
    artifacts = _check_artifacts(root, manifest["artifacts"])
    motion_json = _read_artifact(root, "motion.json", artifacts["motion.json"])
    motion_bvh = _read_artifact(root, "motion.bvh", artifacts["motion.bvh"])
    _check_motion_json(motion_json, manifest)
    _check_bvh(motion_bvh, manifest)
    frozen = json.loads(json.dumps(manifest))
    return TwinManifest(
        directory=root,
        manifest_sha256=manifest["manifest_sha256"],
        source=manifest["motion_source"]["source"],
        preprocess_stage=manifest["motion_source"]["preprocess_stage"],
        workspace_sha256=manifest["workspace_sha256"],
        consent_sha256=manifest["consent"]["consent_sha256"],
        subject_relation=manifest["consent"]["subject_relation"],
        template_model_sha256=manifest["skeleton"]["template_model_sha256"],
        samples=manifest["timing"]["samples"],
        valid_samples=manifest["timing"]["valid_samples"],
        eye=manifest["eye"],
        keypoint_gate_applied=manifest["keypoint_gate"]["applied"],
        motion_bvh=root / "motion.bvh",
        motion_json=root / "motion.json",
        artifacts=MappingProxyType({k: MappingProxyType(v) for k, v in artifacts.items()}),
        raw=MappingProxyType(frozen),
    )
