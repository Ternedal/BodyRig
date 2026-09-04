from __future__ import annotations

import math
from typing import Any, Sequence

ADJUSTMENT_FORMAT = "bodyrig-bodyprint-adjustment"
ADJUSTMENT_VERSION = 1

FIELD_LIMITS: dict[str, float] = {
    "shape.arm_to_height": 0.015,
    "shape.shoulder_to_height": 0.010,
    "shape.hip_to_height": 0.010,
    "shape.leg_to_height": 0.015,
    "shape.height_scale": 0.030,
    "motion.gesture_amplitude": 0.080,
    "motion.energy": 0.080,
}
GEOMETRY_FIELDS = frozenset(field for field in FIELD_LIMITS if field.startswith("shape."))


class BodyprintAdjustmentError(ValueError):
    pass


def validate_adjustment_payload(value: Any) -> dict[str, Any]:
    expected = {"format", "version", "feedback_sha256", "changes"}
    if not isinstance(value, dict) or set(value) != expected:
        raise BodyprintAdjustmentError("BodyPrint adjustment fields must match v1 exactly")
    if value.get("format") != ADJUSTMENT_FORMAT or value.get("version") != ADJUSTMENT_VERSION:
        raise BodyprintAdjustmentError("unsupported BodyPrint adjustment format/version")
    feedback_sha = value.get("feedback_sha256")
    if (
        not isinstance(feedback_sha, str)
        or len(feedback_sha) != 64
        or any(ch not in "0123456789abcdef" for ch in feedback_sha)
    ):
        raise BodyprintAdjustmentError("feedback_sha256 must be lowercase SHA-256")
    changes = value.get("changes")
    if not isinstance(changes, list) or not 1 <= len(changes) <= len(FIELD_LIMITS):
        raise BodyprintAdjustmentError("BodyPrint adjustment must contain 1..7 changes")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(changes):
        if not isinstance(item, dict) or set(item) != {"field", "delta", "reason"}:
            raise BodyprintAdjustmentError(f"changes[{index}] fields must match v1 exactly")
        field = item.get("field")
        if not isinstance(field, str) or field not in FIELD_LIMITS or field in seen:
            raise BodyprintAdjustmentError(f"changes[{index}].field is invalid or duplicated")
        seen.add(field)
        delta = item.get("delta")
        if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not math.isfinite(float(delta)):
            raise BodyprintAdjustmentError(f"changes[{index}].delta must be finite")
        delta = float(delta)
        if delta == 0.0 or abs(delta) > FIELD_LIMITS[field] + 1e-12:
            raise BodyprintAdjustmentError(f"changes[{index}].delta exceeds the bounded V1 limit")
        reason = item.get("reason")
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 240
            or any(ord(ch) < 32 and ch not in "\t" for ch in reason)
        ):
            raise BodyprintAdjustmentError(f"changes[{index}].reason is invalid")
        normalized.append({"field": field, "delta": delta, "reason": reason.strip()})
    return {
        "format": ADJUSTMENT_FORMAT,
        "version": ADJUSTMENT_VERSION,
        "feedback_sha256": feedback_sha,
        "changes": normalized,
    }


def _add(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [float(a[i]) + float(b[i]) for i in range(3)]


def _sub(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [float(a[i]) - float(b[i]) for i in range(3)]


def _mul(a: Sequence[float], factor: float) -> list[float]:
    return [float(a[i]) * float(factor) for i in range(3)]


def _norm(a: Sequence[float]) -> float:
    return math.sqrt(sum(float(a[i]) * float(a[i]) for i in range(3)))


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return _norm(_sub(a, b))


def _mid(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [(float(a[i]) + float(b[i])) / 2.0 for i in range(3)]


def _unit(vector: Sequence[float], *, label: str) -> list[float]:
    length = _norm(vector)
    if length <= 1e-8:
        raise BodyprintAdjustmentError(f"{label} has zero length")
    return _mul(vector, 1.0 / length)


def _index(names: Sequence[str], name: str) -> int:
    try:
        return list(names).index(name)
    except ValueError as exc:
        raise BodyprintAdjustmentError(f"SMPL-X joint {name} is required for BodyPrint shape adjustment") from exc


def _height(joints: Sequence[Sequence[float]], names: Sequence[str]) -> float:
    head = joints[_index(names, "head")]
    ankles = _mid(joints[_index(names, "left_ankle")], joints[_index(names, "right_ankle")])
    value = _distance(head, ankles)
    if value <= 1e-8:
        raise BodyprintAdjustmentError("SMPL-X rest-pose height is degenerate")
    return value


def _ratio(joints: Sequence[Sequence[float]], names: Sequence[str], field: str) -> float:
    height = _height(joints, names)
    if field == "shape.shoulder_to_height":
        return _distance(joints[_index(names, "left_shoulder")], joints[_index(names, "right_shoulder")]) / height
    if field == "shape.hip_to_height":
        return _distance(joints[_index(names, "left_hip")], joints[_index(names, "right_hip")]) / height
    if field == "shape.arm_to_height":
        left = _distance(joints[_index(names, "left_shoulder")], joints[_index(names, "left_wrist")])
        right = _distance(joints[_index(names, "right_shoulder")], joints[_index(names, "right_wrist")])
        return ((left + right) / 2.0) / height
    if field == "shape.leg_to_height":
        hip_mid = _mid(joints[_index(names, "left_hip")], joints[_index(names, "right_hip")])
        left = _distance(hip_mid, joints[_index(names, "left_ankle")])
        right = _distance(hip_mid, joints[_index(names, "right_ankle")])
        return ((left + right) / 2.0) / height
    raise BodyprintAdjustmentError(f"unsupported geometric ratio field: {field}")


def _arm_chain(names: Sequence[str], side: str, *, include_shoulder: bool) -> list[int]:
    prefix = f"{side}_"
    selected: list[int] = []
    for index, name in enumerate(names):
        if not name.startswith(prefix):
            continue
        suffix = name[len(prefix):]
        if suffix in {"shoulder", "elbow", "wrist"} or suffix.startswith(("index", "middle", "pinky", "ring", "thumb")):
            if include_shoulder or suffix != "shoulder":
                selected.append(index)
    return selected


def _leg_chain(names: Sequence[str], side: str, *, include_hip: bool) -> list[int]:
    wanted = {f"{side}_hip", f"{side}_knee", f"{side}_ankle", f"{side}_foot"}
    if not include_hip:
        wanted.remove(f"{side}_hip")
    return [index for index, name in enumerate(names) if name in wanted]


def _translate(joints: list[list[float]], indexes: Sequence[int], delta: Sequence[float]) -> None:
    for index in indexes:
        joints[index] = _add(joints[index], delta)


def _scale_from(joints: list[list[float]], anchor_index: int, indexes: Sequence[int], factor: float) -> None:
    anchor = list(joints[anchor_index])
    for index in indexes:
        joints[index] = _add(anchor, _mul(_sub(joints[index], anchor), factor))


def adjust_joint_positions(
    joints: Sequence[Sequence[float]],
    joint_names: Sequence[str],
    changes: Sequence[dict[str, Any]],
) -> tuple[list[list[float]], dict[str, float]]:
    """Return a bounded target rest skeleton for geometric BodyPrint deltas.

    The targets are defined as *deltas from the already source-derived SMPL-X
    rest skeleton*. That avoids double-fitting raw recovery ratios onto a mesh
    which SiTH already reconstructed from the source material.
    """

    if len(joints) != len(joint_names) or not joints:
        raise BodyprintAdjustmentError("joint topology is empty or inconsistent")
    result = [[float(value) for value in point] for point in joints]
    if any(len(point) != 3 or not all(math.isfinite(value) for value in point) for point in result):
        raise BodyprintAdjustmentError("joint positions must be finite xyz triples")

    by_field = {item["field"]: float(item["delta"]) for item in changes if item["field"] in GEOMETRY_FIELDS}
    height_delta = by_field.pop("shape.height_scale", 0.0)
    if height_delta:
        pelvis_index = _index(joint_names, "pelvis")
        pelvis = list(result[pelvis_index])
        factor = 1.0 + height_delta
        if factor <= 0.0:
            raise BodyprintAdjustmentError("height adjustment produced a non-positive scale")
        for index, point in enumerate(result):
            result[index] = _add(pelvis, _mul(_sub(point, pelvis), factor))

    targets: dict[str, float] = {}
    for field, delta in by_field.items():
        current = _ratio(result, joint_names, field)
        target = current + delta
        if not 0.01 <= target <= 0.99:
            raise BodyprintAdjustmentError(f"{field} target leaves the accepted ratio range")
        targets[field] = target

    # Ratio changes interact through the common body height. Iterate the small,
    # bounded edits until all requested ratios settle on their targets.
    for _ in range(6):
        height = _height(result, joint_names)

        target = targets.get("shape.shoulder_to_height")
        if target is not None:
            left = _index(joint_names, "left_shoulder")
            right = _index(joint_names, "right_shoulder")
            axis = _unit(_sub(result[right], result[left]), label="shoulder axis")
            current_width = _distance(result[left], result[right])
            shift = (target * height - current_width) / 2.0
            _translate(result, _arm_chain(joint_names, "left", include_shoulder=True), _mul(axis, -shift))
            _translate(result, _arm_chain(joint_names, "right", include_shoulder=True), _mul(axis, shift))
            left_collar = _index(joint_names, "left_collar")
            right_collar = _index(joint_names, "right_collar")
            result[left_collar] = _add(result[left_collar], _mul(axis, -shift * 0.5))
            result[right_collar] = _add(result[right_collar], _mul(axis, shift * 0.5))

        target = targets.get("shape.hip_to_height")
        if target is not None:
            left = _index(joint_names, "left_hip")
            right = _index(joint_names, "right_hip")
            axis = _unit(_sub(result[right], result[left]), label="hip axis")
            current_width = _distance(result[left], result[right])
            shift = (target * _height(result, joint_names) - current_width) / 2.0
            _translate(result, _leg_chain(joint_names, "left", include_hip=True), _mul(axis, -shift))
            _translate(result, _leg_chain(joint_names, "right", include_hip=True), _mul(axis, shift))

        target = targets.get("shape.arm_to_height")
        if target is not None:
            current = _ratio(result, joint_names, "shape.arm_to_height")
            factor = target / current
            for side in ("left", "right"):
                shoulder = _index(joint_names, f"{side}_shoulder")
                _scale_from(result, shoulder, _arm_chain(joint_names, side, include_shoulder=False), factor)

        target = targets.get("shape.leg_to_height")
        if target is not None:
            current = _ratio(result, joint_names, "shape.leg_to_height")
            factor = target / current
            for side in ("left", "right"):
                hip = _index(joint_names, f"{side}_hip")
                _scale_from(result, hip, _leg_chain(joint_names, side, include_hip=False), factor)

    final_ratios = {field: _ratio(result, joint_names, field) for field in targets}
    for field, target in targets.items():
        if abs(final_ratios[field] - target) > 5e-4:
            raise BodyprintAdjustmentError(
                f"{field} adjustment did not converge: target={target:.6f}, actual={final_ratios[field]:.6f}"
            )
    return result, final_ratios


def apply_shape_adjustment(
    *,
    np: Any,
    rest_positions: Any,
    rest_joints: Any,
    joints4: Any,
    weights4: Any,
    joint_names: Sequence[str],
    adjustment: Any,
) -> tuple[Any, Any, dict[str, float]]:
    """Apply bounded shape deltas to the source-derived rest pose and mesh.

    Global height is a direct uniform scale around the pelvis. Local proportion
    edits move the target skeleton, then each reconstructed vertex follows the
    joint displacement through its existing top-4 SMPL-X skin weights. This is
    deliberately a small correction layer, not a replacement identity fitter.
    """

    payload = validate_adjustment_payload(adjustment)
    geometric = [item for item in payload["changes"] if item["field"] in GEOMETRY_FIELDS]
    if not geometric:
        return rest_positions, rest_joints, {"max_joint_delta": 0.0}

    positions = rest_positions.tolist()
    base_joints = rest_joints.tolist()
    if len(base_joints) != len(joint_names):
        raise BodyprintAdjustmentError("rest joint topology does not match joint names")

    height_delta = next((float(item["delta"]) for item in geometric if item["field"] == "shape.height_scale"), 0.0)
    pelvis_index = _index(joint_names, "pelvis")
    if height_delta:
        pelvis = list(base_joints[pelvis_index])
        factor = 1.0 + height_delta
        positions = [_add(pelvis, _mul(_sub(point, pelvis), factor)) for point in positions]
        base_joints = [_add(pelvis, _mul(_sub(point, pelvis), factor)) for point in base_joints]

    local_changes = [item for item in geometric if item["field"] != "shape.height_scale"]
    target_joints, ratios = adjust_joint_positions(base_joints, joint_names, local_changes)
    joint_delta = [_sub(target_joints[index], base_joints[index]) for index in range(len(base_joints))]

    joint_rows = joints4.tolist()
    weight_rows = weights4.tolist()
    if len(joint_rows) != len(positions) or len(weight_rows) != len(positions):
        raise BodyprintAdjustmentError("vertex skin-weight arrays do not match reconstructed positions")
    adjusted_positions: list[list[float]] = []
    for vertex_index, point in enumerate(positions):
        displacement = [0.0, 0.0, 0.0]
        row_joints = joint_rows[vertex_index]
        row_weights = weight_rows[vertex_index]
        if len(row_joints) != 4 or len(row_weights) != 4:
            raise BodyprintAdjustmentError("BodyRig shape adjustment requires top-4 skin weights")
        for raw_joint, raw_weight in zip(row_joints, row_weights):
            joint = int(raw_joint)
            weight = float(raw_weight)
            if joint < 0 or joint >= len(joint_delta) or not math.isfinite(weight) or weight < 0.0:
                raise BodyprintAdjustmentError("invalid skin influence during BodyPrint adjustment")
            displacement = _add(displacement, _mul(joint_delta[joint], weight))
        adjusted_positions.append(_add(point, displacement))

    max_joint_delta = max((_norm(delta) for delta in joint_delta), default=0.0)
    metrics = {"max_joint_delta": float(max_joint_delta), **ratios}
    return (
        np.asarray(adjusted_positions, dtype=rest_positions.dtype),
        np.asarray(target_joints, dtype=rest_joints.dtype),
        metrics,
    )
