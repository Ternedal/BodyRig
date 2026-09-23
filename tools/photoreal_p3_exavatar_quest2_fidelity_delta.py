from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bodyrig.bridges.sith_pbr_material import PbrMaterialError, _read_glb
from bodyrig.hands_feet_nails_fingernail_geometry_candidate import (
    HandsFeetNailsFingernailGeometryError,
    _accessor_values,
    _body_geometry_inputs,
)
from bodyrig.photoreal_p3_quest2_eye_component import NODE_NAME as EYE_NODE_NAME
from bodyrig.photoreal_p3_quest2_eye_student_runner import validate_candidate_receipt
from bodyrig.photoreal_p3_quest2_fidelity_delta import (
    EXPECTED_COMPONENT_METRICS,
    FORMAT,
    POLICY_REVISION,
    REMAINING_BLOCKERS,
    VERSION,
    validate_fidelity_delta_evidence_structure,
)
from bodyrig.photoreal_p3_quest2_hair_component import NODE_NAME as HAIR_NODE_NAME
from bodyrig.photoreal_p3_quest2_hair_student_runner import (
    _read_json as _read_hair_json,
    validate_hair_student_receipt,
)
from bodyrig.photoreal_p3_device_distillation_runner import _digest, _file_sha
from tools.photoreal_p3_exavatar_quest2_student_candidate import (
    PINNED_TEST_EPOCH,
    Quest2StudentCandidateError,
    _prepare_exavatar_stage,
    _read_json,
    _validate_request,
    _verify_staged_teacher,
    _verify_workspace,
)


class ExAvatarQuest2FidelityDeltaError(ValueError):
    pass


def _finite_array(np: Any, value: Any, *, label: str, width: int = 3) -> Any:
    array = np.asarray(value, dtype=np.float32)
    if (
        array.ndim != 2
        or array.shape[1] != width
        or array.shape[0] < 1
        or not bool(np.all(np.isfinite(array)))
    ):
        raise ExAvatarQuest2FidelityDeltaError(f"{label} array is invalid")
    return array


def _pose_params(torch: Any, smpl_x: Any, pose_index: int) -> dict[str, Any]:
    if pose_index not in range(5):
        raise ExAvatarQuest2FidelityDeltaError("canonical fidelity pose index is invalid")
    body = torch.zeros(
        ((len(smpl_x.joint_part["body"]) - 1) * 3,),
        dtype=torch.float32,
        device="cuda",
    )
    jaw = torch.zeros((3,), dtype=torch.float32, device="cuda")
    leye = torch.zeros((3,), dtype=torch.float32, device="cuda")
    reye = torch.zeros((3,), dtype=torch.float32, device="cuda")
    lhand = torch.zeros(
        (len(smpl_x.joint_part["lhand"]) * 3,),
        dtype=torch.float32,
        device="cuda",
    )
    rhand = torch.zeros(
        (len(smpl_x.joint_part["rhand"]) * 3,),
        dtype=torch.float32,
        device="cuda",
    )
    if pose_index == 1:
        body[15 * 3 + 2] = -0.55
        body[17 * 3 + 1] = -0.45
    elif pose_index == 2:
        body[16 * 3 + 2] = 0.55
        body[18 * 3 + 1] = 0.45
    elif pose_index == 3:
        body[2 * 3 + 1] = 0.25
        body[14 * 3 + 1] = 0.35
        jaw[0] = 0.18
    elif pose_index == 4:
        body[2 * 3 + 1] = -0.25
        body[14 * 3 + 1] = -0.35
        leye[1] = 0.12
        reye[1] = -0.12
        lhand[0] = 0.25
        rhand[0] = -0.25
    return {
        "root_pose": torch.zeros((3,), dtype=torch.float32, device="cuda"),
        "body_pose": body,
        "jaw_pose": jaw,
        "leye_pose": leye,
        "reye_pose": reye,
        "lhand_pose": lhand,
        "rhand_pose": rhand,
        "expr": torch.zeros(
            (smpl_x.expr_param_dim,),
            dtype=torch.float32,
            device="cuda",
        ),
        "trans": torch.zeros((3,), dtype=torch.float32, device="cuda"),
    }


def _load_teacher_state(
    *,
    main_dir: Path,
    subject: str,
) -> dict[str, Any]:
    try:
        import numpy as np
        import torch
    except ImportError as exc:
        raise ExAvatarQuest2FidelityDeltaError(
            f"numpy/torch are required for Quest2 fidelity measurement: {exc}"
        ) from exc
    if not torch.cuda.is_available():
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 fidelity measurement requires CUDA"
        )

    common_dir = main_dir.parent / "common"
    inserted = [str(main_dir), str(common_dir)]
    old_cwd = Path.cwd()
    for value in reversed(inserted):
        if value not in sys.path:
            sys.path.insert(0, value)
    os.chdir(main_dir)
    try:
        from base import Tester
        from config import cfg
        from utils.smpl_x import smpl_x

        cfg.set_args(subject)
        identity_root = (
            main_dir.parent
            / "data"
            / "Custom"
            / "data"
            / subject
            / "smplx_optimized"
        )
        with (identity_root / "shape_param.json").open("r", encoding="utf-8") as stream:
            shape_param = torch.tensor(json.load(stream), dtype=torch.float32)
        with (identity_root / "face_offset.json").open("r", encoding="utf-8") as stream:
            face_offset = torch.tensor(json.load(stream), dtype=torch.float32)
        with (identity_root / "joint_offset.json").open("r", encoding="utf-8") as stream:
            joint_offset = torch.tensor(json.load(stream), dtype=torch.float32)
        with (identity_root / "locator_offset.json").open("r", encoding="utf-8") as stream:
            locator_offset = torch.tensor(json.load(stream), dtype=torch.float32)
        smpl_x.set_id_info(shape_param, face_offset, joint_offset, locator_offset)

        tester = Tester(str(PINNED_TEST_EPOCH))
        tester.smplx_params = None
        tester._make_model()
        human = tester.model.module.human_gaussian

        zero3 = torch.zeros((3,), dtype=torch.float32, device="cuda")
        cam = {
            "R": torch.eye(3, dtype=torch.float32, device="cuda"),
            "t": zero3.clone(),
            "focal": torch.tensor((1500.0, 1500.0), dtype=torch.float32, device="cuda"),
            "princpt": torch.tensor((512.0, 512.0), dtype=torch.float32, device="cuda"),
        }

        residuals: list[Any] = []
        refined_zero = None
        with torch.no_grad():
            for pose_index in range(5):
                params = _pose_params(torch, smpl_x, pose_index)
                base_asset, refined_asset, _offsets, _neutral = human(
                    params,
                    cam,
                    is_world_coord=True,
                )
                base_np = base_asset["mean_3d"].detach().cpu().numpy().astype(np.float32)
                refined_np = refined_asset["mean_3d"].detach().cpu().numpy().astype(np.float32)
                residuals.append(refined_np - base_np)
                if pose_index == 0:
                    refined_zero = {
                        "xyz": refined_np,
                        "rgb": refined_asset["rgb"].detach().cpu().numpy().astype(np.float32),
                    }
            _upsampled, zero_mesh, _zero_joints = human.get_zero_pose_human(
                return_mesh=True
            )

        if refined_zero is None:
            raise ExAvatarQuest2FidelityDeltaError("accepted ExAvatar teacher produced no zero pose")
        zero_mesh_np = zero_mesh.detach().cpu().numpy().astype(np.float32)
        if zero_mesh_np.shape != (smpl_x.vertex_num, 3):
            raise ExAvatarQuest2FidelityDeltaError(
                "accepted ExAvatar zero-pose donor topology is unexpected"
            )
        body_height = float(np.max(zero_mesh_np[:, 1]) - np.min(zero_mesh_np[:, 1]))
        if not math.isfinite(body_height) or body_height <= 1e-6:
            raise ExAvatarQuest2FidelityDeltaError(
                "accepted ExAvatar donor height is invalid"
            )

        zero_residual = residuals[0]
        motion_residual = np.stack(
            [item - zero_residual for item in residuals[1:]],
            axis=0,
        ).astype(np.float64)
        residual_stack = np.stack(residuals, axis=0).astype(np.float64)
        motion_delta = float(np.sqrt(np.mean(motion_residual ** 2))) / body_height
        temporal_delta = float(np.sqrt(np.mean(np.diff(residual_stack, axis=0) ** 2))) / body_height
        if (
            not math.isfinite(motion_delta)
            or motion_delta < 0.0
            or not math.isfinite(temporal_delta)
            or temporal_delta < 0.0
        ):
            raise ExAvatarQuest2FidelityDeltaError(
                "accepted ExAvatar pose residual measurements are invalid"
            )

        return {
            "np": np,
            "torch": torch,
            "device": torch.device("cuda"),
            "teacher_xyz": refined_zero["xyz"],
            "teacher_rgb": refined_zero["rgb"],
            "zero_mesh": zero_mesh_np,
            "body_height": body_height,
            "motion_delta": motion_delta,
            "temporal_delta": temporal_delta,
        }
    finally:
        os.chdir(old_cwd)


def _nearest(
    torch: Any,
    *,
    query: Any,
    reference: Any,
    device: Any,
    query_chunk: int = 384,
    reference_chunk: int = 8192,
) -> tuple[Any, Any]:
    query_tensor = torch.as_tensor(query, dtype=torch.float32, device=device)
    ref_tensor = torch.as_tensor(reference, dtype=torch.float32, device=device)
    if (
        query_tensor.ndim != 2
        or ref_tensor.ndim != 2
        or query_tensor.shape[1] != 3
        or ref_tensor.shape[1] != 3
        or query_tensor.shape[0] < 1
        or ref_tensor.shape[0] < 1
    ):
        raise ExAvatarQuest2FidelityDeltaError(
            "nearest-surface query/reference arrays are invalid"
        )

    all_distance: list[Any] = []
    all_index: list[Any] = []
    with torch.no_grad():
        for start in range(0, int(query_tensor.shape[0]), query_chunk):
            chunk = query_tensor[start : start + query_chunk]
            best_distance = torch.full(
                (chunk.shape[0],),
                float("inf"),
                dtype=torch.float32,
                device=device,
            )
            best_index = torch.zeros(
                (chunk.shape[0],),
                dtype=torch.long,
                device=device,
            )
            for ref_start in range(0, int(ref_tensor.shape[0]), reference_chunk):
                ref = ref_tensor[ref_start : ref_start + reference_chunk]
                distance = torch.cdist(chunk.unsqueeze(0), ref.unsqueeze(0)).squeeze(0)
                local_distance, local_index = torch.min(distance, dim=1)
                improve = local_distance < best_distance
                best_distance = torch.where(improve, local_distance, best_distance)
                best_index = torch.where(
                    improve,
                    local_index + ref_start,
                    best_index,
                )
            if not bool(torch.all(torch.isfinite(best_distance)).item()):
                raise ExAvatarQuest2FidelityDeltaError(
                    "nearest-surface measurement produced non-finite distance"
                )
            all_distance.append(best_distance.detach().cpu())
            all_index.append(best_index.detach().cpu())
    return torch.cat(all_distance).numpy(), torch.cat(all_index).numpy()


def _chamfer_rms(
    torch: Any,
    np: Any,
    *,
    left: Any,
    right: Any,
    device: Any,
) -> float:
    a = _finite_array(np, left, label="left surface")
    b = _finite_array(np, right, label="right surface")
    left_distance, _ = _nearest(
        torch,
        query=a,
        reference=b,
        device=device,
    )
    right_distance, _ = _nearest(
        torch,
        query=b,
        reference=a,
        device=device,
    )
    result = math.sqrt(
        (
            float(np.mean(left_distance.astype(np.float64) ** 2))
            + float(np.mean(right_distance.astype(np.float64) ** 2))
        )
        / 2.0
    )
    if not math.isfinite(result) or result < 0.0:
        raise ExAvatarQuest2FidelityDeltaError(
            "symmetric surface Chamfer RMS is invalid"
        )
    return result


def _named_primitives(
    document: Mapping[str, Any],
    binary: bytes,
    *,
    node_name: str,
) -> list[dict[str, Any]]:
    nodes = document.get("nodes")
    meshes = document.get("meshes")
    if not isinstance(nodes, list) or not isinstance(meshes, list):
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 student VRM lacks node/mesh arrays"
        )
    matching = [
        node for node in nodes
        if isinstance(node, Mapping) and node.get("name") == node_name
    ]
    if len(matching) != 1:
        raise ExAvatarQuest2FidelityDeltaError(
            f"Quest2 student VRM node is missing/repeated: {node_name}"
        )
    mesh_index = matching[0].get("mesh")
    if (
        isinstance(mesh_index, bool)
        or not isinstance(mesh_index, int)
        or mesh_index < 0
        or mesh_index >= len(meshes)
        or not isinstance(meshes[mesh_index], Mapping)
    ):
        raise ExAvatarQuest2FidelityDeltaError(
            f"Quest2 student VRM node has invalid mesh: {node_name}"
        )
    primitives = meshes[mesh_index].get("primitives")
    if not isinstance(primitives, list) or not primitives:
        raise ExAvatarQuest2FidelityDeltaError(
            f"Quest2 student VRM mesh has no primitives: {node_name}"
        )

    result: list[dict[str, Any]] = []
    for primitive in primitives:
        if not isinstance(primitive, Mapping):
            raise ExAvatarQuest2FidelityDeltaError(
                f"Quest2 student primitive is invalid: {node_name}"
            )
        attrs = primitive.get("attributes")
        if not isinstance(attrs, Mapping):
            raise ExAvatarQuest2FidelityDeltaError(
                f"Quest2 student primitive attributes are invalid: {node_name}"
            )
        try:
            positions = _accessor_values(
                document,
                binary,
                attrs["POSITION"],
                label=f"{node_name} POSITION",
                component_type=5126,
                kind="VEC3",
            )
            uvs = _accessor_values(
                document,
                binary,
                attrs["TEXCOORD_0"],
                label=f"{node_name} TEXCOORD_0",
                component_type=5126,
                kind="VEC2",
            )
        except (KeyError, HandsFeetNailsFingernailGeometryError) as exc:
            raise ExAvatarQuest2FidelityDeltaError(
                f"Quest2 student primitive payload is invalid: {node_name}"
            ) from exc
        if len(positions) != len(uvs):
            raise ExAvatarQuest2FidelityDeltaError(
                f"Quest2 student primitive POSITION/UV counts differ: {node_name}"
            )
        extras = primitive.get("extras")
        role = None
        if isinstance(extras, Mapping):
            role = extras.get("bodyrigP3EyeRole") or extras.get("bodyrigP3HairRole")
        result.append(
            {
                "role": str(role) if isinstance(role, str) else "",
                "positions": positions,
                "uvs": uvs,
            }
        )
    return result


def _texture_samples(
    np: Any,
    png: bytes,
    uvs: Sequence[Sequence[float | int]],
) -> Any:
    try:
        from PIL import Image
    except ImportError as exc:
        raise ExAvatarQuest2FidelityDeltaError(
            f"Pillow is required for fidelity texture sampling: {exc}"
        ) from exc
    try:
        with Image.open(io.BytesIO(png)) as image:
            image = image.convert("RGB")
            rgb = np.asarray(image, dtype=np.float32) / 255.0
    except (OSError, ValueError) as exc:
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 student basecolor is unreadable"
        ) from exc
    height, width, channels = rgb.shape
    if channels != 3 or width < 1 or height < 1:
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 student basecolor dimensions are invalid"
        )

    result = np.empty((len(uvs), 3), dtype=np.float32)
    for index, raw in enumerate(uvs):
        if len(raw) < 2:
            raise ExAvatarQuest2FidelityDeltaError(
                "Quest2 student UV tuple is invalid"
            )
        u = float(raw[0])
        v = float(raw[1])
        if (
            not math.isfinite(u)
            or not math.isfinite(v)
            or not 0.0 <= u <= 1.0
            or not 0.0 <= v <= 1.0
        ):
            raise ExAvatarQuest2FidelityDeltaError(
                "Quest2 student UV escaped normalized bounds"
            )
        x = min(width - 1, max(0, int(round(u * (width - 1)))))
        y = min(height - 1, max(0, int(round((1.0 - v) * (height - 1)))))
        result[index] = rgb[y, x]
    return result


def _joint_group_mask(
    np: Any,
    *,
    joints: Sequence[Sequence[float | int]],
    weights: Sequence[Sequence[float | int]],
    joint_names: Sequence[str],
    targets: set[str],
    threshold: float = 0.35,
) -> Any:
    normalized_names = [
        name[6:] if name.startswith("smplx_") else name
        for name in joint_names
    ]
    target_indices = {
        index for index, name in enumerate(normalized_names)
        if name in targets
    }
    if not target_indices:
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 student semantic joint group is missing"
        )
    values = []
    for joint_row, weight_row in zip(joints, weights, strict=True):
        total = sum(
            float(weight)
            for joint, weight in zip(joint_row, weight_row, strict=True)
            if int(joint) in target_indices
        )
        if not math.isfinite(total) or total < 0.0:
            raise ExAvatarQuest2FidelityDeltaError(
                "Quest2 student semantic skinning weight is invalid"
            )
        values.append(total >= threshold)
    return np.asarray(values, dtype=bool)


def _rmse(np: Any, left: Any, right: Any) -> float:
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.shape != b.shape or a.size == 0:
        raise ExAvatarQuest2FidelityDeltaError(
            "fidelity appearance arrays are empty/shape-incompatible"
        )
    value = float(np.sqrt(np.mean((a - b) ** 2)))
    if not math.isfinite(value) or value < 0.0:
        raise ExAvatarQuest2FidelityDeltaError(
            "fidelity appearance RMSE is invalid"
        )
    return value


def _component(metric: str, value: float, unit: str) -> dict[str, Any]:
    if not math.isfinite(value) or value < 0.0:
        raise ExAvatarQuest2FidelityDeltaError(
            f"fidelity component metric is invalid: {metric}"
        )
    return {
        "metric": metric,
        "value": round(float(value), 9),
        "unit": unit,
    }


def _measurement(
    dimension: str,
    components: list[dict[str, Any]],
    *,
    teacher_reference: str,
    student_reference: str,
) -> dict[str, Any]:
    expected = EXPECTED_COMPONENT_METRICS[dimension]
    if [item["metric"] for item in components] != list(expected):
        raise ExAvatarQuest2FidelityDeltaError(
            f"fidelity component metric order differs: {dimension}"
        )
    value = max(float(item["value"]) for item in components)
    metric = expected[0] if len(expected) == 1 else "worst-axis(" + ",".join(expected) + ")"
    unit = components[0]["unit"] if len(components) == 1 else "dimensionless-worst-axis-delta"
    return {
        "dimension": dimension,
        "metric": metric,
        "value": round(value, 9),
        "unit": unit,
        "teacher_reference": teacher_reference,
        "student_reference": student_reference,
        "component_metrics": components,
    }


def build_fidelity_evidence(
    *,
    candidate_workspace: str | Path,
    exavatar_workspace_root: str | Path,
    hair_output_root: str | Path,
) -> dict[str, Any]:
    candidate_root = Path(candidate_workspace).expanduser().resolve()
    exavatar_root = Path(exavatar_workspace_root).expanduser().resolve()
    hair_root = Path(hair_output_root).expanduser().resolve()
    request_path = candidate_root / "request.json"
    candidate_receipt_path = candidate_root / "p3-quest2-student-candidate-receipt.json"
    hair_receipt_path = hair_root / "p3-quest2-hair-student-receipt.json"
    for path, label in (
        (request_path, "P3 candidate request"),
        (candidate_receipt_path, "P3 candidate receipt"),
        (hair_receipt_path, "P3 hair receipt"),
    ):
        if not path.is_file() or path.is_symlink():
            raise ExAvatarQuest2FidelityDeltaError(
                f"{label} is missing/not regular: {path}"
            )

    request = _read_json(request_path, label="P3 candidate request")
    try:
        _validate_request(
            request,
            adapter=str(request.get("adapter")),
            revision=str(request.get("adapter_revision")),
            representation=str(request.get("student_representation")),
            student_components=",".join(
                str(item) for item in request.get("student_components", [])
            ),
        )
        candidate = validate_candidate_receipt(
            _read_json(
                candidate_receipt_path,
                label="P3 candidate receipt",
            ),
            candidate_output_root=candidate_root / "output",
        )
        hair = validate_hair_student_receipt(
            _read_hair_json(hair_receipt_path, label="P3 hair receipt"),
            hair_output_root=hair_root,
        )
        if (
            candidate["p3_device_distillation_request_sha256"]
            != request["p3_device_distillation_request_sha256"]
            or hair["p3_quest2_student_candidate_receipt_sha256"]
            != candidate["p3_quest2_student_candidate_receipt_sha256"]
        ):
            raise ExAvatarQuest2FidelityDeltaError(
                "Quest2 fidelity candidate/hair lineage differs"
            )
        repo = _verify_workspace(exavatar_root, request)
        staged_root = candidate_root / "staged-teacher"
        sources = _verify_staged_teacher(request, staged_root)
    except (Quest2StudentCandidateError, ValueError) as exc:
        raise ExAvatarQuest2FidelityDeltaError(str(exc)) from exc

    subject = "bodyrig-p3-fidelity"
    with tempfile.TemporaryDirectory(prefix="bodyrig-p3-exavatar-fidelity-") as temp:
        try:
            main_dir = _prepare_exavatar_stage(
                stage=Path(temp),
                repo=repo,
                sources=sources,
                subject=subject,
            )
            state = _load_teacher_state(main_dir=main_dir, subject=subject)
        except Quest2StudentCandidateError as exc:
            raise ExAvatarQuest2FidelityDeltaError(str(exc)) from exc

    np = state["np"]
    torch = state["torch"]
    device = state["device"]
    teacher_xyz = _finite_array(np, state["teacher_xyz"], label="teacher geometry")
    teacher_rgb = _finite_array(np, state["teacher_rgb"], label="teacher RGB")
    if teacher_xyz.shape != teacher_rgb.shape:
        raise ExAvatarQuest2FidelityDeltaError(
            "accepted ExAvatar teacher geometry/RGB counts differ"
        )
    if float(np.min(teacher_rgb)) < -1e-6 or float(np.max(teacher_rgb)) > 1.000001:
        raise ExAvatarQuest2FidelityDeltaError(
            "accepted ExAvatar teacher RGB is outside normalized 0..1"
        )
    body_height = float(state["body_height"])

    avatar_record = next(
        item for item in hair["student_artifacts"]
        if item["kind"] == "student-runtime-package"
    )
    basecolor_record = next(
        item for item in hair["student_artifacts"]
        if item["kind"] == "teacher-derived-basecolor"
    )
    avatar_path = hair_root / avatar_record["relative_path"]
    basecolor_path = hair_root / basecolor_record["relative_path"]
    try:
        document, binary = _read_glb(avatar_path.read_bytes())
        (
            body_primitive,
            body_positions_raw,
            _body_normals,
            body_uvs,
            body_joints,
            body_weights,
            _body_indices,
            joint_names,
        ) = _body_geometry_inputs(document, binary)
    except (PbrMaterialError, HandsFeetNailsFingernailGeometryError) as exc:
        raise ExAvatarQuest2FidelityDeltaError(
            f"Quest2 fidelity student VRM is invalid: {exc}"
        ) from exc
    body_positions = _finite_array(
        np,
        body_positions_raw,
        label="Quest2 body positions",
    )
    body_attrs = body_primitive.get("attributes")
    if not isinstance(body_attrs, Mapping) or "_BODYRIG_SOURCE_VERTEX" not in body_attrs:
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 refined body lacks exact ExAvatar source-vertex authority"
        )
    try:
        source_rows = _accessor_values(
            document,
            binary,
            body_attrs["_BODYRIG_SOURCE_VERTEX"],
            label="Quest2 body source vertex",
            component_type=5123,
            kind="SCALAR",
        )
    except HandsFeetNailsFingernailGeometryError as exc:
        raise ExAvatarQuest2FidelityDeltaError(
            f"Quest2 body source-vertex authority is invalid: {exc}"
        ) from exc
    if len(source_rows) != len(body_positions):
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 body source-vertex authority count differs from render vertices"
        )
    source_indices = np.asarray(
        [int(row[0]) for row in source_rows],
        dtype=np.int64,
    )
    teacher_surface = _finite_array(
        np,
        state["teacher_xyz"],
        label="accepted ExAvatar refined surface",
    )
    zero_surface = _finite_array(
        np,
        state["zero_upsampled"],
        label="accepted ExAvatar zero surface",
    )
    if (
        teacher_surface.shape != zero_surface.shape
        or np.any(source_indices < 0)
        or np.any(source_indices >= len(teacher_surface))
    ):
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 body source-vertex authority escapes ExAvatar geometry"
        )

    base_face_count = len(state["faces"])
    source_face_count = int(state["subdivider_source_face_count"])
    subdivided = np.asarray(state["first_subdivision_faces"], dtype=np.int64)
    expected_source_vertices: set[int] = set()
    for block in range(4):
        start = block * source_face_count
        rows = subdivided[start : start + base_face_count]
        expected_source_vertices.update(int(value) for value in rows.reshape(-1))
    if set(int(value) for value in source_indices.tolist()) != expected_source_vertices:
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 body source-vertex universe differs from canonical first subdivision"
        )
    expected_positions = teacher_surface[source_indices]
    if not np.array_equal(body_positions, expected_positions):
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 base body bytes no longer preserve exact subdivided ExAvatar source geometry"
        )
    if np.array_equal(body_positions, zero_surface[source_indices]):
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 base body regressed to the zero-surface mannequin geometry"
        )

    eye_primitives = _named_primitives(
        document,
        binary,
        node_name=EYE_NODE_NAME,
    )
    hair_primitives = _named_primitives(
        document,
        binary,
        node_name=HAIR_NODE_NAME,
    )
    eye_positions = _finite_array(
        np,
        [
            position
            for primitive in eye_primitives
            for position in primitive["positions"]
        ],
        label="Quest2 eye component",
    )
    eye_surface_positions = _finite_array(
        np,
        [
            position
            for primitive in eye_primitives
            if primitive["role"].endswith("_surface")
            for position in primitive["positions"]
        ],
        label="Quest2 eye surface component",
    )
    eye_surface_uvs = [
        uv
        for primitive in eye_primitives
        if primitive["role"].endswith("_surface")
        for uv in primitive["uvs"]
    ]
    hair_positions = _finite_array(
        np,
        [
            position
            for primitive in hair_primitives
            for position in primitive["positions"]
        ],
        label="Quest2 hair component",
    )
    hair_uvs = [
        uv
        for primitive in hair_primitives
        for uv in primitive["uvs"]
    ]

    eye_mask = _joint_group_mask(
        np,
        joints=body_joints,
        weights=body_weights,
        joint_names=joint_names,
        targets={"left_eye", "right_eye"},
        threshold=0.35,
    )
    head_mask = _joint_group_mask(
        np,
        joints=body_joints,
        weights=body_weights,
        joint_names=joint_names,
        targets={"neck", "head", "jaw", "left_eye", "right_eye"},
        threshold=0.35,
    )
    extremity_targets = {
        "left_wrist",
        "right_wrist",
        "left_ankle",
        "right_ankle",
        "left_foot",
        "right_foot",
    }
    extremity_targets.update(
        name
        for name in (
            "left_index1", "left_index2", "left_index3",
            "left_middle1", "left_middle2", "left_middle3",
            "left_pinky1", "left_pinky2", "left_pinky3",
            "left_ring1", "left_ring2", "left_ring3",
            "left_thumb1", "left_thumb2", "left_thumb3",
            "right_index1", "right_index2", "right_index3",
            "right_middle1", "right_middle2", "right_middle3",
            "right_pinky1", "right_pinky2", "right_pinky3",
            "right_ring1", "right_ring2", "right_ring3",
            "right_thumb1", "right_thumb2", "right_thumb3",
        )
    )
    extremity_mask = _joint_group_mask(
        np,
        joints=body_joints,
        weights=body_weights,
        joint_names=joint_names,
        targets=extremity_targets,
        threshold=0.35,
    )

    _hair_distance, hair_base_index = _nearest(
        torch,
        query=hair_positions,
        reference=body_positions,
        device=device,
    )
    hair_base_mask = np.zeros((len(body_positions),), dtype=bool)
    hair_base_mask[np.asarray(hair_base_index, dtype=np.int64)] = True
    if int(np.count_nonzero(hair_base_mask)) < 3:
        raise ExAvatarQuest2FidelityDeltaError(
            "Quest2 hair component does not bind a usable base-head domain"
        )
    face_mask = head_mask & (~eye_mask) & (~hair_base_mask)
    skin_mask = (~eye_mask) & (~hair_base_mask)
    for label, mask in (
        ("face", face_mask),
        ("eye", eye_mask),
        ("hair", hair_base_mask),
        ("skin", skin_mask),
        ("extremity", extremity_mask),
    ):
        if int(np.count_nonzero(mask)) < 3:
            raise ExAvatarQuest2FidelityDeltaError(
                f"Quest2 fidelity semantic region is too small: {label}"
            )

    teacher_to_body_distance, teacher_to_body_index = _nearest(
        torch,
        query=teacher_xyz,
        reference=body_positions,
        device=device,
    )
    teacher_to_body_index = np.asarray(teacher_to_body_index, dtype=np.int64)
    teacher_face = teacher_xyz[face_mask[teacher_to_body_index]]
    teacher_eye = teacher_xyz[eye_mask[teacher_to_body_index]]
    teacher_hair = teacher_xyz[hair_base_mask[teacher_to_body_index]]
    teacher_extremity = teacher_xyz[extremity_mask[teacher_to_body_index]]
    for label, values in (
        ("face", teacher_face),
        ("eyes", teacher_eye),
        ("hair", teacher_hair),
        ("extremities", teacher_extremity),
    ):
        if len(values) < 8:
            raise ExAvatarQuest2FidelityDeltaError(
                f"accepted ExAvatar teacher has too little mapped {label} evidence"
            )

    body_to_teacher_distance, body_to_teacher_index = _nearest(
        torch,
        query=body_positions,
        reference=teacher_xyz,
        device=device,
    )
    body_to_teacher_index = np.asarray(body_to_teacher_index, dtype=np.int64)
    teacher_rgb_at_body = teacher_rgb[body_to_teacher_index]
    student_rgb_at_body = _texture_samples(
        np,
        basecolor_path.read_bytes(),
        body_uvs,
    )

    face_rgb = _rmse(
        np,
        teacher_rgb_at_body[face_mask],
        student_rgb_at_body[face_mask],
    )

    _eye_teacher_distance, eye_teacher_index = _nearest(
        torch,
        query=eye_surface_positions,
        reference=teacher_xyz,
        device=device,
    )
    eye_teacher_rgb = teacher_rgb[
        np.asarray(eye_teacher_index, dtype=np.int64)
    ]
    eye_student_rgb = _texture_samples(
        np,
        basecolor_path.read_bytes(),
        eye_surface_uvs,
    )
    eye_rgb = _rmse(
        np,
        eye_teacher_rgb,
        eye_student_rgb,
    )

    _hair_teacher_distance, hair_teacher_index = _nearest(
        torch,
        query=hair_positions,
        reference=teacher_xyz,
        device=device,
    )
    hair_teacher_rgb = teacher_rgb[
        np.asarray(hair_teacher_index, dtype=np.int64)
    ]
    hair_student_rgb = _texture_samples(
        np,
        basecolor_path.read_bytes(),
        hair_uvs,
    )
    hair_rgb = _rmse(
        np,
        hair_teacher_rgb,
        hair_student_rgb,
    )

    skin_rgb = _rmse(
        np,
        teacher_rgb_at_body[skin_mask],
        student_rgb_at_body[skin_mask],
    )

    identity_geometry = _chamfer_rms(
        torch,
        np,
        left=teacher_xyz,
        right=np.concatenate(
            [body_positions, eye_surface_positions, hair_positions],
            axis=0,
        ),
        device=device,
    ) / body_height
    face_geometry = _chamfer_rms(
        torch,
        np,
        left=teacher_face,
        right=body_positions[face_mask],
        device=device,
    ) / body_height
    eye_geometry = _chamfer_rms(
        torch,
        np,
        left=teacher_eye,
        right=eye_positions,
        device=device,
    ) / body_height
    hair_geometry = _chamfer_rms(
        torch,
        np,
        left=teacher_hair,
        right=hair_positions,
        device=device,
    ) / body_height
    extremity_geometry = _chamfer_rms(
        torch,
        np,
        left=teacher_extremity,
        right=body_positions[extremity_mask],
        device=device,
    ) / body_height

    checkpoint_sha = _file_sha(sources["teacher-checkpoint"])
    avatar_sha = avatar_record["sha256"]
    basecolor_sha = basecolor_record["sha256"]
    teacher_static_ref = (
        f"sha256:{checkpoint_sha}#accepted-exavatar-refined-zero-pose"
    )
    teacher_motion_ref = (
        f"sha256:{checkpoint_sha}#accepted-exavatar-canonical-pose-sweep-v1"
    )
    student_geometry_ref = (
        f"sha256:{avatar_sha}#quest2-vrm-body-eye-hair-surfaces"
    )
    student_appearance_ref = (
        f"sha256:{avatar_sha}#quest2-vrm;"
        f"sha256:{basecolor_sha}#teacher-derived-basecolor"
    )

    measurements = [
        _measurement(
            "identity_likeness",
            [
                _component(
                    "symmetric-surface-chamfer-rms/body-height",
                    identity_geometry,
                    "normalized-rmse",
                )
            ],
            teacher_reference=teacher_static_ref,
            student_reference=student_geometry_ref,
        ),
        _measurement(
            "face_detail",
            [
                _component(
                    "face-surface-chamfer-rms/body-height",
                    face_geometry,
                    "normalized-rmse",
                ),
                _component(
                    "face-basecolor-rgb-rmse",
                    face_rgb,
                    "rgb-0-1-rmse",
                ),
            ],
            teacher_reference=teacher_static_ref,
            student_reference=student_appearance_ref,
        ),
        _measurement(
            "eyes",
            [
                _component(
                    "eye-surface-chamfer-rms/body-height",
                    eye_geometry,
                    "normalized-rmse",
                ),
                _component(
                    "eye-basecolor-rgb-rmse",
                    eye_rgb,
                    "rgb-0-1-rmse",
                ),
            ],
            teacher_reference=teacher_static_ref,
            student_reference=student_appearance_ref,
        ),
        _measurement(
            "hair_silhouette_and_appearance",
            [
                _component(
                    "hair-surface-chamfer-rms/body-height",
                    hair_geometry,
                    "normalized-rmse",
                ),
                _component(
                    "hair-basecolor-rgb-rmse",
                    hair_rgb,
                    "rgb-0-1-rmse",
                ),
            ],
            teacher_reference=teacher_static_ref,
            student_reference=student_appearance_ref,
        ),
        _measurement(
            "skin_material_response",
            [
                _component(
                    "skin-basecolor-rgb-rmse",
                    skin_rgb,
                    "rgb-0-1-rmse",
                )
            ],
            teacher_reference=teacher_static_ref,
            student_reference=student_appearance_ref,
        ),
        _measurement(
            "hands_and_extremities",
            [
                _component(
                    "extremity-surface-chamfer-rms/body-height",
                    extremity_geometry,
                    "normalized-rmse",
                )
            ],
            teacher_reference=teacher_static_ref,
            student_reference=student_geometry_ref,
        ),
        _measurement(
            "motion_identity_preservation",
            [
                _component(
                    "teacher-pose-dependent-refinement-residual-rmse/body-height",
                    float(state["motion_delta"]),
                    "normalized-rmse",
                )
            ],
            teacher_reference=teacher_motion_ref,
            student_reference=student_geometry_ref,
        ),
        _measurement(
            "temporal_stability",
            [
                _component(
                    "teacher-refinement-frame-delta-rmse/body-height",
                    float(state["temporal_delta"]),
                    "normalized-rmse",
                )
            ],
            teacher_reference=teacher_motion_ref,
            student_reference=student_geometry_ref,
        ),
    ]

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": hair["performer_id"],
        "selected_epoch_id": hair["selected_epoch_id"],
        "teacher_input_sha256": hair["teacher_input_sha256"],
        "p3_device_distillation_plan_sha256": hair[
            "p3_device_distillation_plan_sha256"
        ],
        "p3_device_distillation_request_sha256": hair[
            "p3_device_distillation_request_sha256"
        ],
        "p3_quest2_student_candidate_receipt_sha256": hair[
            "p3_quest2_student_candidate_receipt_sha256"
        ],
        "p3_quest2_eye_student_receipt_sha256": hair[
            "p3_quest2_eye_student_receipt_sha256"
        ],
        "p3_quest2_hair_student_receipt_sha256": hair[
            "p3_quest2_hair_student_receipt_sha256"
        ],
        "target_model": "quest-2",
        "student_representation": "skinned-mesh-pbr",
        "implemented_student_components": list(hair["implemented_student_components"]),
        "teacher_checkpoint_sha256": checkpoint_sha,
        "teacher_point_count": int(teacher_xyz.shape[0]),
        "student_artifacts": list(hair["student_artifacts"]),
        "measurement_policy_revision": POLICY_REVISION,
        "fidelity_delta_measurements": measurements,
        "fidelity_delta_complete": True,
        "p3_distillation_complete": False,
        "remaining_blockers": list(REMAINING_BLOCKERS),
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p3_quest2_fidelity_delta_evidence_sha256"] = _digest(
        result,
        omit="p3_quest2_fidelity_delta_evidence_sha256",
    )
    return validate_fidelity_delta_evidence_structure(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure the exact modular Quest2 student against the accepted "
            "ExAvatar teacher over the canonical P3 fidelity dimensions."
        )
    )
    parser.add_argument("--candidate-workspace", type=Path, required=True)
    parser.add_argument("--exavatar-workspace-root", type=Path, required=True)
    parser.add_argument("--hair-output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        output = args.output.expanduser().resolve()
        if output.exists():
            raise ExAvatarQuest2FidelityDeltaError(
                f"Quest2 fidelity evidence output already exists: {output}"
            )
        hair_root = args.hair_output_root.expanduser().resolve()
        try:
            output.relative_to(hair_root)
        except ValueError:
            pass
        else:
            raise ExAvatarQuest2FidelityDeltaError(
                "Quest2 fidelity evidence must be written outside the immutable hair output root"
            )
        result = build_fidelity_evidence(
            candidate_workspace=args.candidate_workspace,
            exavatar_workspace_root=args.exavatar_workspace_root,
            hair_output_root=args.hair_output_root,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except (OSError, ExAvatarQuest2FidelityDeltaError) as exc:
        print(f"BodyRig ExAvatar Quest2 fidelity delta: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P3_QUEST2_FIDELITY_DELTA_COMPLETE",
                "dimension_count": len(result["fidelity_delta_measurements"]),
                "remaining_blockers": result["remaining_blockers"],
                "p3_distillation_complete": False,
                "human_runtime_visual_acceptance_required": True,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
