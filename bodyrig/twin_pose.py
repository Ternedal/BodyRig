"""POSE_READY: body motion from a staged ExAvatar workspace (#1398 slice 1a).

The ExAvatar preprocess already estimates SMPL-X parameters for every training frame. This
module turns the recorded outputs of one stage into a body motion, without a new model:

- ``init``: Hand4Whole's per-frame estimate (``hand4whole-smplx-init``). It has no root
  translation, so every sample stands at the origin. It is ready early in preprocessing.
- ``smoothed``: the fitted and smoothed parameters (``smplx-smooth``), with root translation.

Outputs, in a private directory, written atomically:

- ``motion.bvh``: the 22-joint SMPL-X body skeleton, one BVH frame per valid sample;
- ``motion.json``: the same motion with the real sample timestamps and per-sample validity;
- ``digital_twin_manifest.json``: provenance, the coordinate system and the artifacts.

What it refuses, rather than infers:

- a workspace whose receipt, preprocess state or any recorded output fails its integrity check;
- a workspace without an explicit subject-consent record bound to that exact workspace
  (``record_consent``). The record is the operator's own statement: the subject is the
  operator, or an adult who consented. The tool cannot verify consent itself; it verifies that
  it was recorded for this workspace and has not been altered since;
- a parameter file that is not byte-identical to the one the preprocess state recorded;
- a symlink anywhere on a path it reads or writes.

What it never writes: body shape, face or expression parameters, hand poses, source frames,
source names or keys, the performer or subject id. The skeleton's rest pose is the SMPL-X
neutral template with zero shape, so bone lengths carry nothing of the subject.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoreal_exavatar_preprocess import (
    STATE_FORMAT as PREPROCESS_STATE_FORMAT,
    PhotorealExAvatarPreprocessError,
    validate_recorded_stage_outputs,
    validate_workspace_receipt,
)

CONSENT_FORMAT = "bodyrig-twin-subject-consent"
MOTION_FORMAT = "bodyrig-twin-motion"
MANIFEST_FORMAT = "bodyrig-digital-twin-manifest"
MATERIALIZATION_FORMAT = "bodyrig-photoreal-exavatar-materialization-receipt"
VERSION = 1
CONSENT_SCOPE = "pose-motion-local"
RELATIONS = ("self", "consenting-adult")

# Which preprocess stage each motion source comes from, and where its per-frame files are.
SOURCES: dict[str, tuple[str, str]] = {
    "init": ("hand4whole-smplx-init", "smplx_init"),
    "smoothed": ("smplx-smooth", "smplx_optimized/smplx_params_smoothed"),
}

# The SMPL-X body joints 0..21 and their parents. Fixed: a model whose kinematic tree differs
# is refused, so the joint map of every motion.bvh is the same.
JOINTS = (
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee", "spine2",
    "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot", "neck", "left_collar",
    "right_collar", "head", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
)
PARENTS = (-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19)
SKELETON = "smplx-body-22"

# ExAvatar's camera and world frame is +X right, +Y down, +Z forward (BodyRig's tangent cameras
# are relative to the front viewport). The output frame is +X right, +Y up, -Z forward, which is
# BodyRig's own source frame: a rotation of 180 degrees about X.
TO_OUTPUT = ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))
COORDINATE_SYSTEM = {
    "handedness": "right",
    "up": "+Y",
    "forward": "-Z",
    "right": "+X",
    "units": "metres",
    "origin": "the front camera of the source (BodyRig tangent-camera world)",
    "from_exavatar": "rotate 180 degrees about X (x, y, z) -> (x, -y, -z)",
}
# The samples are training frames chosen across a clip, not consecutive video frames. BVH needs
# one fixed frame time, so it holds one frame per valid sample at this nominal rate; motion.json
# holds the real timestamps.
BVH_FRAME_TIME = 1.0 / 30.0
OUTPUT_NAMES = ("motion.bvh", "motion.json", "digital_twin_manifest.json")
MAX_PARAMETER_BYTES = 1 << 20
MAX_MODEL_BYTES = 2 << 30
_STAGE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class TwinPoseError(ValueError):
    pass


class TwinPoseNotReady(TwinPoseError):
    """The workspace is valid but the stage the motion needs has not completed yet."""


# --- small helpers -------------------------------------------------------------------------


def _canonical_digest(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sha_text(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower() if isinstance(value, str) else ""
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise TwinPoseError(f"{label} is not a SHA-256")
    return text


def _finite(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _vector(value: Any, length: int) -> list[float] | None:
    if not isinstance(value, list) or len(value) != length or not all(_finite(item) for item in value):
        return None
    return [float(item) for item in value]


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --- safe reads ----------------------------------------------------------------------------


def _real_directory(path: Path, *, label: str) -> Path:
    """An existing directory whose path has no symlinked component."""
    absolute = Path(os.path.abspath(path.expanduser()))
    if absolute.is_symlink() or not absolute.is_dir():
        raise TwinPoseError(f"{label} is not a real directory: {absolute}")
    if absolute.resolve() != absolute:
        raise TwinPoseError(f"{label} path goes through a symlink: {absolute}")
    return absolute


def _read_regular(path: Path, *, within: Path | None, label: str, limit: int = MAX_PARAMETER_BYTES) -> bytes:
    """The bytes of a regular file (inside ``within`` when given), refusing symlinks on the whole path.

    Every input is read through this one function, once: the receipt, the state, the consent
    record, the materialization receipt, every parameter and camera file and the model."""
    absolute = Path(os.path.abspath(path))
    if within is not None:
        try:
            absolute.relative_to(within)
        except ValueError:
            raise TwinPoseError(f"{label} is outside the workspace") from None
    if absolute.is_symlink() or absolute.resolve() != absolute:
        raise TwinPoseError(f"{label} path goes through a symlink")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(absolute, flags)
    except OSError as exc:
        raise TwinPoseError(f"{label} cannot be opened ({type(exc).__name__})") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise TwinPoseError(f"{label} is not a regular file")
        if info.st_size > limit:
            raise TwinPoseError(f"{label} is larger than {limit} bytes")
        # The file can still grow after fstat: count what is read and stop one byte past the cap
        # (ChatGPT #1408 6767309212), on the same descriptor.
        chunks, total = [], 0
        while total <= limit:
            chunk = os.read(fd, min(1 << 16, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > limit:
            raise TwinPoseError(f"{label} is larger than {limit} bytes")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _load_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TwinPoseError(f"{label} is not valid JSON") from None
    if not isinstance(value, dict):
        raise TwinPoseError(f"{label} must be a JSON object")
    return value


# --- consent -------------------------------------------------------------------------------


def build_consent(
    *,
    workspace_sha256: str,
    relation: str,
    subject_is_adult: bool,
    consent_evidence_sha256: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """A consent record for one workspace. The operator makes this statement; nothing infers it."""
    document: dict[str, Any] = {
        "format": CONSENT_FORMAT,
        "version": VERSION,
        "workspace_sha256": _sha_text(workspace_sha256, label="workspace SHA-256"),
        "subject_relation": relation,
        "subject_is_adult": subject_is_adult,
        "scopes": [CONSENT_SCOPE],
        "consent_evidence_sha256": consent_evidence_sha256,
        "recorded_at": recorded_at or _utc_now(),
        "recorded_by": "operator",
        "likeness_authority": False,
    }
    document["consent_sha256"] = _canonical_digest(document, omit="consent_sha256")
    validate_consent(document, workspace_sha256=document["workspace_sha256"])
    return document


def validate_consent(document: Any, *, workspace_sha256: str) -> str:
    """The record's digest, after every check; anything else is refused."""
    if not isinstance(document, Mapping):
        raise TwinPoseError("subject consent record must be a JSON object")
    expected_keys = {
        "format", "version", "workspace_sha256", "subject_relation", "subject_is_adult", "scopes",
        "consent_evidence_sha256", "recorded_at", "recorded_by", "likeness_authority", "consent_sha256",
    }
    if set(document) != expected_keys:
        raise TwinPoseError("subject consent record has missing or unknown fields")
    if document.get("format") != CONSENT_FORMAT or document.get("version") != VERSION:
        raise TwinPoseError("subject consent record format/version mismatch")
    if _sha_text(document.get("workspace_sha256"), label="consent workspace SHA-256") != workspace_sha256:
        raise TwinPoseError("subject consent record belongs to a different workspace")
    relation = document.get("subject_relation")
    if relation not in RELATIONS:
        raise TwinPoseError("subject consent record relation must be self or consenting-adult")
    if document.get("subject_is_adult") is not True:
        raise TwinPoseError("subject consent record does not state that the subject is an adult")
    scopes = document.get("scopes")
    if not isinstance(scopes, list) or CONSENT_SCOPE not in scopes or not all(isinstance(s, str) for s in scopes):
        raise TwinPoseError(f"subject consent record does not cover {CONSENT_SCOPE}")
    evidence = document.get("consent_evidence_sha256")
    if relation == "consenting-adult":
        _sha_text(evidence, label="consent evidence SHA-256 (required for a consenting adult)")
    elif evidence is not None:
        _sha_text(evidence, label="consent evidence SHA-256")
    recorded_at = document.get("recorded_at")
    if not isinstance(recorded_at, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", recorded_at):
        raise TwinPoseError("subject consent record time must be UTC like 2026-11-10T12:00:00Z")
    if document.get("recorded_by") != "operator" or document.get("likeness_authority") is not False:
        raise TwinPoseError("subject consent record authority fields are invalid")
    claimed = _sha_text(document.get("consent_sha256"), label="consent SHA-256")
    if _canonical_digest(document, omit="consent_sha256") != claimed:
        raise TwinPoseError("subject consent record was changed after it was recorded")
    return claimed


# --- the workspace -------------------------------------------------------------------------


def _workspace_receipt(workspace_root: str | Path) -> tuple[Path, dict[str, Any]]:
    root = _real_directory(Path(workspace_root), label="ExAvatar workspace")
    raw = _read_regular(root / "workspace-receipt.json", within=root, label="workspace receipt")
    try:
        receipt = validate_workspace_receipt(_load_object(raw, label="workspace receipt"))
    except PhotorealExAvatarPreprocessError as exc:
        raise TwinPoseError(f"workspace receipt is not valid: {exc}") from None
    return root, receipt


def load_verified_workspace(workspace_root: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """The workspace root, its receipt and its preprocess state, all integrity-checked."""
    root, receipt = _workspace_receipt(workspace_root)
    state = _load_object(_read_regular(root / "preprocess-state.json", within=root, label="preprocess state"),
                         label="preprocess state")
    if state.get("format") != PREPROCESS_STATE_FORMAT or state.get("version") != VERSION:
        raise TwinPoseError("preprocess state format/version mismatch")
    if state.get("workspace_sha256") != receipt["workspace_sha256"]:
        raise TwinPoseError("preprocess state belongs to a different workspace")
    if state.get("photoreal_acceptance_authority") is not False or state.get("production_activation") is not False:
        raise TwinPoseError("preprocess state crossed downstream authority")
    if "preprocess_state_sha256" in state:
        claimed = _sha_text(state.get("preprocess_state_sha256"), label="preprocess state SHA-256")
        if _canonical_digest(state, omit="preprocess_state_sha256") != claimed:
            raise TwinPoseError("preprocess state digest mismatch")
    if state.get("camera_mode") != "virtual":
        raise TwinPoseError("only the virtual camera mode is supported in slice 1a (COLMAP worlds have no fixed up axis)")
    try:
        validate_recorded_stage_outputs(root, state)
    except PhotorealExAvatarPreprocessError as exc:
        raise TwinPoseError(f"a recorded preprocess output has drifted: {exc}") from None
    return root, receipt, state


def _path_key(path: str | Path) -> str:
    """One spelling per path: the state records POSIX spellings, Windows reads use backslashes."""
    return os.path.normcase(os.path.abspath(str(path)))


def _completed(state: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Stage name -> {normalised absolute output path: sha256}, as the state recorded them."""
    result: dict[str, dict[str, str]] = {}
    for stage in state.get("completed_stages") or []:
        if isinstance(stage, Mapping):
            outputs = {_path_key(item["path"]): str(item["sha256"]) for item in stage.get("outputs") or []
                       if isinstance(item, Mapping) and isinstance(item.get("path"), str) and "sha256" in item}
            result[str(stage.get("name"))] = outputs
    return result


def available_source(state: Mapping[str, Any]) -> str | None:
    """The best motion source the state has completed: smoothed, else init, else None."""
    done = _completed(state)
    for source in ("smoothed", "init"):
        if SOURCES[source][0] in done:
            return source
    return None


def _read_recorded(path: Path, *, root: Path, recorded: Mapping[str, str], label: str) -> bytes:
    expected = recorded.get(_path_key(path))
    if expected is None:
        raise TwinPoseError(f"{label} is not an output the preprocess state recorded")
    raw = _read_regular(path, within=root, label=label)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise TwinPoseError(f"{label} changed after the preprocess state recorded it")
    return raw


def _sample_times(dataset: Path, *, root: Path, receipt: Mapping[str, Any]) -> tuple[dict[int, float], str]:
    """Timestamp per frame, and the eye, from the materialization receipt the workspace is bound to.

    The workspace build copied ``materialization-receipt.json`` into the dataset, and the
    digest-checked workspace receipt holds its SHA-256 (``materialization_receipt_sha256``), so
    these values are authenticated. ``bodyrig-source-map.json`` holds the same frames but is
    bound to nothing, so it is not read (Codex #1408 4524657349)."""
    raw = _read_regular(dataset / "materialization-receipt.json", within=root, label="materialization receipt",
                        limit=64 << 20)
    value = _load_object(raw, label="materialization receipt")
    bound = _sha_text(receipt.get("materialization_receipt_sha256"), label="bound materialization receipt SHA-256")
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != bound:
        raise TwinPoseError("materialization receipt is not the one this workspace was built from")
    if value.get("format") != MATERIALIZATION_FORMAT or value.get("version") != VERSION:
        raise TwinPoseError("materialization receipt format/version mismatch")
    frames = value.get("frames")
    count = int(receipt["frame_count"])
    if not isinstance(frames, list) or len(frames) != count:
        raise TwinPoseError("materialization receipt frame count differs from the workspace")
    timestamps: dict[int, float] = {}
    eyes: set[str] = set()
    for frame in frames:
        if not isinstance(frame, Mapping):
            raise TwinPoseError("materialization receipt frame entry is invalid")
        index, stamp, eye = frame.get("exavatar_frame_index"), frame.get("timestamp_seconds"), frame.get("eye")
        if isinstance(index, bool) or not isinstance(index, int) or index in timestamps:
            raise TwinPoseError("materialization receipt frame index is invalid")
        if not _finite(stamp) or float(stamp) < 0:
            raise TwinPoseError("materialization receipt timestamp is invalid")
        if eye not in ("mono", "left", "right"):
            raise TwinPoseError("materialization receipt eye is invalid")
        timestamps[index] = float(stamp)
        eyes.add(eye)
    if set(timestamps) != set(range(count)):
        raise TwinPoseError("materialization receipt frames are not the workspace's training frames")
    if len(eyes) != 1:
        raise TwinPoseError("materialization receipt mixes stereo eyes")
    return timestamps, eyes.pop()


# --- rotations -----------------------------------------------------------------------------


Matrix = list[list[float]]


def axis_angle_to_matrix(v: Sequence[float]) -> Matrix:
    x, y, z = (float(a) for a in v)
    angle = math.sqrt(x * x + y * y + z * z)
    if angle < 1e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    x, y, z = x / angle, y / angle, z / angle
    c, s, t = math.cos(angle), math.sin(angle), 1.0 - math.cos(angle)
    return [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]


def matrix_to_axis_angle(m: Matrix) -> list[float]:
    trace = m[0][0] + m[1][1] + m[2][2]
    cos = max(-1.0, min(1.0, (trace - 1.0) / 2.0))
    angle = math.acos(cos)
    if angle < 1e-9:
        return [0.0, 0.0, 0.0]
    if math.pi - angle < 1e-6:  # near 180 degrees: take the axis from the symmetric part
        diag = [max(0.0, (m[i][i] + 1.0) / 2.0) for i in range(3)]
        k = max(range(3), key=lambda i: diag[i])
        axis = [0.0, 0.0, 0.0]
        axis[k] = math.sqrt(diag[k])
        for j in range(3):
            if j != k:
                axis[j] = (m[k][j] + m[j][k]) / (4.0 * axis[k])
        norm = math.sqrt(sum(a * a for a in axis))
        return [a / norm * angle for a in axis]
    s = 2.0 * math.sin(angle)
    axis = [(m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s]
    return [a * angle for a in axis]


def matrix_to_zxy_degrees(m: Matrix) -> tuple[float, float, float]:
    """(z, x, y) with R = Rz(z) @ Rx(x) @ Ry(y): BVH's 'Zrotation Xrotation Yrotation' order."""
    x = math.asin(max(-1.0, min(1.0, m[2][1])))
    if abs(m[2][1]) < 1.0 - 1e-9:
        z = math.atan2(-m[0][1], m[1][1])
        y = math.atan2(-m[2][0], m[2][2])
    else:  # gimbal lock: fold the rotation into Z
        z = math.atan2(m[1][0], m[0][0])
        y = 0.0
    return math.degrees(z), math.degrees(x), math.degrees(y)


def _mul(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _transpose(a: Sequence[Sequence[float]]) -> Matrix:
    return [[a[j][i] for j in range(3)] for i in range(3)]


def _apply(a: Sequence[Sequence[float]], v: Sequence[float]) -> list[float]:
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def _rotation(value: Any) -> Matrix | None:
    if not isinstance(value, list) or len(value) != 3:
        return None
    rows = [_vector(row, 3) for row in value]
    if any(row is None for row in rows):
        return None
    m: Matrix = rows  # type: ignore[assignment]
    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    product = _mul(_transpose(m), m)
    if abs(det - 1.0) > 1e-3 or max(abs(product[i][j] - (1.0 if i == j else 0.0)) for i in range(3) for j in range(3)) > 1e-3:
        return None
    return m


# --- per-sample motion ---------------------------------------------------------------------


def parse_parameters(raw: bytes, *, source: str) -> tuple[dict[str, Any] | None, str | None]:
    """(root_pose, body_pose, trans) from one SMPL-X parameter file, or (None, reason).

    Only these are read. Shape, expression, jaw, eyes and hands are ignored and never copied."""
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "unreadable_parameters"
    if not isinstance(value, dict):
        return None, "unreadable_parameters"
    root = _vector(value.get("root_pose"), 3)
    body_raw = value.get("body_pose")
    body = [_vector(row, 3) for row in body_raw] if isinstance(body_raw, list) and len(body_raw) == 21 else None
    if root is None or body is None or any(row is None for row in body):
        return None, "malformed_pose"
    trans = None
    if source == "smoothed":
        trans = _vector(value.get("trans"), 3)
        if trans is None:
            return None, "malformed_translation"
    return {"root_pose": root, "body_pose": body, "trans": trans}, None


def sample_motion(params: Mapping[str, Any], camera: Mapping[str, Any], pelvis_rest: Sequence[float]) -> dict[str, Any]:
    """One sample in the output frame: root rotation and position, and the 21 local rotations.

    SMPL-X places the pelvis at ``pelvis_rest + trans`` in camera coordinates; ExAvatar's world
    is ``R^T (p - t)``; the output frame is that world turned 180 degrees about X. The local
    joint rotations are relative to the rest skeleton and need no conversion."""
    r_cam: Matrix = camera["R"]
    t_cam: list[float] = camera["t"]
    root_world = _mul(TO_OUTPUT, _mul(_transpose(r_cam), axis_angle_to_matrix(params["root_pose"])))
    if params["trans"] is None:
        position = None  # init: Hand4Whole estimates no translation
    else:
        pelvis_cam = [float(pelvis_rest[k]) + params["trans"][k] for k in range(3)]
        world = _apply(_transpose(r_cam), [pelvis_cam[k] - t_cam[k] for k in range(3)])
        position = _apply(TO_OUTPUT, world)
    return {"root_rotation": root_world, "root_position": position,
            "local_rotations": [list(row) for row in params["body_pose"]]}


# --- BVH -----------------------------------------------------------------------------------


def _fmt(value: float) -> str:
    text = f"{value:.6f}"
    return "0.000000" if text == "-0.000000" else text


def _children() -> dict[int, list[int]]:
    children: dict[int, list[int]] = {i: [] for i in range(len(JOINTS))}
    for joint, parent in enumerate(PARENTS):
        if parent >= 0:
            children[parent].append(joint)
    return children


def hierarchy_order() -> list[int]:
    """SMPL-X joint indices in the order motion.bvh declares them (depth first from the pelvis)."""
    children, order = _children(), []

    def walk(joint: int) -> None:
        order.append(joint)
        for child in children[joint]:
            walk(child)

    walk(0)
    return order


def write_bvh(rest_joints: Sequence[Sequence[float]], samples: Sequence[Mapping[str, Any]]) -> str:
    """The skeleton (offsets from the rest joints) and one frame per sample."""
    if len(rest_joints) != len(JOINTS) or not all(_vector([float(v) for v in j], 3) for j in rest_joints):
        raise TwinPoseError("the rest skeleton must have 22 finite joints")
    if not samples:
        raise TwinPoseError("there is no valid sample to write")
    children = _children()
    lines = ["HIERARCHY"]

    def emit(joint: int, depth: int) -> None:
        pad = "\t" * depth
        parent = PARENTS[joint]
        # The root's offset is zero: its position channels carry the absolute pelvis position.
        offset = [0.0, 0.0, 0.0] if parent < 0 else [float(rest_joints[joint][k]) - float(rest_joints[parent][k]) for k in range(3)]
        lines.append(f"{pad}{'ROOT' if parent < 0 else 'JOINT'} {JOINTS[joint]}")
        lines.append(pad + "{")
        lines.append(f"{pad}\tOFFSET {' '.join(_fmt(v) for v in offset)}")
        lines.append(f"{pad}\tCHANNELS {'6 Xposition Yposition Zposition' if parent < 0 else '3'} Zrotation Xrotation Yrotation")
        for child in children[joint]:
            emit(child, depth + 1)
        if not children[joint]:
            lines.extend([f"{pad}\tEnd Site", pad + "\t{", f"{pad}\t\tOFFSET 0.000000 0.000000 0.000000", pad + "\t}"])
        lines.append(pad + "}")

    emit(0, 0)
    lines.extend(["MOTION", f"Frames: {len(samples)}", f"Frame Time: {_fmt(BVH_FRAME_TIME)}"])
    order = hierarchy_order()
    for sample in samples:
        position = sample["root_position"] or [0.0, 0.0, 0.0]
        values = [float(v) for v in position]
        values.extend(matrix_to_zxy_degrees(sample["root_rotation"]))
        # BVH channels follow the order joints are declared in (depth first), not the SMPL-X index.
        for joint in order[1:]:
            values.extend(matrix_to_zxy_degrees(axis_angle_to_matrix(sample["local_rotations"][joint - 1])))
        if len(values) != 6 + 3 * (len(JOINTS) - 1) or not all(math.isfinite(v) for v in values):
            raise TwinPoseError("a motion value is not finite")
        lines.append(" ".join(_fmt(v) for v in values))
    return "\n".join(lines) + "\n"


# --- rest skeleton from the SMPL-X model ---------------------------------------------------


def load_template_rest_joints(model_path: str | Path) -> tuple[list[list[float]], str]:
    """The 22 body joints of the SMPL-X template at zero shape, and the model file's SHA-256.

    Needs numpy (present in the ExAvatar runtime, where this runs). The archive is opened with
    ``allow_pickle=False`` and only three numeric arrays are read."""
    import io

    import numpy as np  # deferred: BodyRig's core installs without numpy

    path = Path(os.path.abspath(Path(model_path).expanduser()))
    if path.suffix.lower() != ".npz":
        raise TwinPoseError("the SMPL-X model must be a .npz file (for example SMPLX_NEUTRAL.npz)")
    # Same whole-path symlink policy as every other input (Codex #1408 4524657359); the bytes are
    # read once, so the hash and the arrays come from the same file contents.
    raw = _read_regular(path, within=None, label="SMPL-X model", limit=MAX_MODEL_BYTES)
    model_sha = hashlib.sha256(raw).hexdigest()
    try:
        with np.load(io.BytesIO(raw), allow_pickle=False) as data:
            template = np.asarray(data["v_template"], dtype=np.float64)
            regressor = np.asarray(data["J_regressor"], dtype=np.float64)
            tree = np.asarray(data["kintree_table"])
    except (OSError, KeyError, ValueError) as exc:
        raise TwinPoseError(f"the SMPL-X model cannot be read ({type(exc).__name__})") from None
    if template.ndim != 2 or template.shape[1] != 3 or regressor.ndim != 2 or regressor.shape[0] < len(JOINTS) \
            or regressor.shape[1] != template.shape[0] or tree.ndim != 2 or tree.shape[1] < len(JOINTS):
        raise TwinPoseError("the SMPL-X model arrays have unexpected shapes")
    parents = [int(p) for p in tree[0][: len(JOINTS)]]
    parents[0] = -1
    if tuple(parents) != PARENTS:
        raise TwinPoseError("the SMPL-X model's body kinematic tree differs from the fixed joint map")
    joints = regressor[: len(JOINTS)] @ template
    if not np.all(np.isfinite(joints)):
        raise TwinPoseError("the SMPL-X template joints are not finite")
    return [[float(v) for v in row] for row in joints], model_sha


# --- private output ------------------------------------------------------------------------


def prepare_output_dir(out: str | Path) -> Path:
    """A private output directory with no symlinked component; created (0700) if missing."""
    path = Path(os.path.abspath(Path(out).expanduser()))
    if path.is_symlink():
        raise TwinPoseError("output directory is a symlink")
    if not path.exists():
        parent = _real_directory(path.parent, label="output parent")
        path = parent / path.name
        path.mkdir(mode=0o700)
    path = _real_directory(path, label="output directory")
    if os.name == "posix":
        os.chmod(path, 0o700)
    return path


def atomic_write(directory: Path, name: str, data: bytes) -> dict[str, Any]:
    """Write one output file through a private temporary file and an atomic rename."""
    if name not in OUTPUT_NAMES:
        raise TwinPoseError(f"not an output file name: {name}")
    final = directory / name
    if final.is_symlink() or (final.exists() and not final.is_file()):
        raise TwinPoseError(f"output {name} exists and is not a regular file")
    fd, temp = tempfile.mkstemp(dir=directory, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, final)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    if os.name == "posix":
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    return {"name": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


# --- stage timings -------------------------------------------------------------------------


def _stage_timings(root: Path) -> list[dict[str, Any]]:
    """Name, state and elapsed seconds of each preprocess stage the watcher recorded; nothing else."""
    path = root / "logs" / "preprocess" / "stage-timing.jsonl"
    if not path.exists():
        return []
    raw = _read_regular(path, within=root, label="stage timings", limit=4 << 20)
    result = []
    for line in raw.decode("utf-8", "replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("format") != "bodyrig-exavatar-stage-timing":
            continue
        stage, state, elapsed = record.get("stage"), record.get("state"), record.get("elapsed_seconds")
        if isinstance(stage, str) and _STAGE_NAME.fullmatch(stage) and isinstance(state, str) \
                and _STAGE_NAME.fullmatch(state) and _finite(elapsed):
            result.append({"stage": stage, "state": state, "elapsed_seconds": float(elapsed)})
    return result


# --- the whole export ----------------------------------------------------------------------


def export_pose(
    *,
    workspace_root: str | Path,
    consent_path: str | Path,
    out_dir: str | Path,
    rest_joints: Sequence[Sequence[float]],
    template_model_sha256: str,
    source: str = "auto",
) -> dict[str, Any]:
    """Verify, read, convert and write. Returns the manifest."""
    root, receipt, state = load_verified_workspace(workspace_root)
    consent_raw = _read_regular(Path(os.path.abspath(Path(consent_path).expanduser())),
                                within=Path(os.path.abspath(Path(consent_path).expanduser())).parent,
                                label="subject consent record")
    consent = _load_object(consent_raw, label="subject consent record")
    consent_sha = validate_consent(consent, workspace_sha256=receipt["workspace_sha256"])

    chosen = available_source(state) if source == "auto" else source
    if chosen not in SOURCES:
        if source == "auto":
            raise TwinPoseNotReady("no motion source yet: hand4whole-smplx-init has not completed")
        raise TwinPoseError("source must be auto, init or smoothed")
    stage_name, folder = SOURCES[chosen]
    done = _completed(state)
    if stage_name not in done:
        raise TwinPoseNotReady(f"{stage_name} has not completed")
    if "camera" not in done:
        raise TwinPoseError("the camera stage is not recorded")

    dataset = root / str(receipt["working_dataset_relative_path"])
    timestamps, eye = _sample_times(dataset, root=root, receipt=receipt)
    pelvis = [float(v) for v in rest_joints[0]]
    frames: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for index in sorted(timestamps, key=lambda i: (timestamps[i], i)):
        entry: dict[str, Any] = {"exavatar_frame_index": index, "timestamp_seconds": timestamps[index],
                                 "valid": False, "invalid_reason": None, "bvh_frame": None}
        camera_raw = _read_recorded(dataset / "cam_params" / f"{index}.json", root=root, recorded=done["camera"],
                                    label=f"camera of frame {index}")
        camera_value = _load_object(camera_raw, label=f"camera of frame {index}")
        r_cam, t_cam = _rotation(camera_value.get("R")), _vector(camera_value.get("t"), 3)
        params_raw = _read_recorded(dataset / folder / f"{index}.json", root=root, recorded=done[stage_name],
                                    label=f"{chosen} parameters of frame {index}")
        params, reason = parse_parameters(params_raw, source=chosen)
        if r_cam is None or t_cam is None:
            reason = "invalid_camera"
        if reason is None and params is not None:
            sample = sample_motion(params, {"R": r_cam, "t": t_cam}, pelvis)
            entry.update({
                "valid": True,
                "bvh_frame": len(samples),
                "root_rotation_axis_angle": matrix_to_axis_angle(sample["root_rotation"]),
                "root_position": sample["root_position"],
                "joint_rotations_axis_angle": sample["local_rotations"],
            })
            samples.append(sample)
        else:
            entry["invalid_reason"] = reason
        frames.append(entry)
    if not samples:
        raise TwinPoseError("no frame has a valid pose")

    out = prepare_output_dir(out_dir)
    skeleton = {"name": SKELETON, "joints": list(JOINTS), "parents": list(PARENTS),
                "bvh_joint_order": [JOINTS[i] for i in hierarchy_order()],
                "rest_pose": "SMPL-X neutral template, zero shape",
                "template_model_sha256": _sha_text(template_model_sha256, label="template model SHA-256")}
    motion = {
        "format": MOTION_FORMAT,
        "version": VERSION,
        "source": chosen,
        "skeleton": skeleton,
        "coordinate_system": COORDINATE_SYSTEM,
        "rotation_encoding": "axis-angle radians; root in the output frame, joints local to their parent",
        "root_translation": "estimated" if chosen == "smoothed" else "not estimated (null); BVH puts the root at the origin",
        "frames": frames,
    }
    bvh = write_bvh(rest_joints, samples).encode("utf-8")
    artifacts = [atomic_write(out, "motion.bvh", bvh), atomic_write(out, "motion.json", _json_bytes(motion))]
    manifest: dict[str, Any] = {
        "format": MANIFEST_FORMAT,
        "version": VERSION,
        "state": "POSE_READY",
        "mesh": "unavailable",
        "motion_source": {"source": chosen, "preprocess_stage": stage_name},
        "workspace_sha256": receipt["workspace_sha256"],
        "preprocess_state_sha256": _canonical_digest(state, omit="preprocess_state_sha256"),
        "consent": {"consent_sha256": consent_sha, "subject_relation": consent["subject_relation"]},
        "skeleton": {key: skeleton[key] for key in ("name", "rest_pose", "template_model_sha256")} | {"joint_count": len(JOINTS)},
        "coordinate_system": COORDINATE_SYSTEM,
        "timing": {
            "samples": len(frames),
            "valid_samples": len(samples),
            "first_timestamp_seconds": frames[0]["timestamp_seconds"],
            "last_timestamp_seconds": frames[-1]["timestamp_seconds"],
            "bvh_frame_time_seconds": round(BVH_FRAME_TIME, 6),
            "bvh_timing": "one BVH frame per valid sample, nominal rate; real times in motion.json",
        },
        "eye": eye,
        "invalid_samples": sorted({f["invalid_reason"] for f in frames if not f["valid"]}),
        "multi_person_detection": "not available: ExAvatar keeps one person per frame and records no others",
        "preprocess_stage_timings": _stage_timings(root),
        "artifacts": artifacts,
        "likeness_authority": False,
        "identity_claim": False,
        "cloud_transfer": False,
        "modelrig_transfer": False,
        "production_activation": False,
    }
    manifest["manifest_sha256"] = _canonical_digest(manifest, omit="manifest_sha256")
    atomic_write(out, "digital_twin_manifest.json", _json_bytes(manifest))
    return manifest


def record_consent(
    *,
    workspace_root: str | Path,
    out_path: str | Path,
    relation: str,
    subject_is_adult: bool,
    consent_evidence_sha256: str | None = None,
) -> dict[str, Any]:
    """Write a new consent record for this workspace. An existing file is never overwritten."""
    _root, receipt = _workspace_receipt(workspace_root)
    document = build_consent(workspace_sha256=receipt["workspace_sha256"], relation=relation,
                             subject_is_adult=subject_is_adult, consent_evidence_sha256=consent_evidence_sha256)
    target = Path(os.path.abspath(Path(out_path).expanduser()))
    parent = _real_directory(target.parent, label="consent record folder")
    target = parent / target.name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(target, flags, 0o600)
    except FileExistsError:
        raise TwinPoseError(f"a consent record already exists: {target}") from None
    with os.fdopen(fd, "wb") as handle:
        handle.write(_json_bytes(document))
        handle.flush()
        os.fsync(handle.fileno())
    return document
