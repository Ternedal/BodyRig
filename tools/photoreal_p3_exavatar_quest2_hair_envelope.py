from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bodyrig.photoreal_p3_quest2_eye_student_runner import validate_candidate_receipt
from bodyrig.photoreal_p3_quest2_hair_component import (
    PhotorealP3Quest2HairComponentError,
    select_teacher_hair_faces,
)
from tools.photoreal_p3_exavatar_quest2_student_candidate import (
    Quest2StudentCandidateError,
    _load_zero_pose_teacher,
    _prepare_exavatar_stage,
    _read_json,
    _sha_file,
    _validate_request,
    _verify_staged_teacher,
    _verify_workspace,
)


FORMAT = "bodyrig-photoreal-p3-exavatar-quest2-hair-envelope"
VERSION = 1


class ExAvatarQuest2HairEnvelopeError(ValueError):
    pass


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExAvatarQuest2HairEnvelopeError(
            "hair envelope cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _vertex_normals(np: Any, positions: Any, faces: Any) -> Any:
    vertices = np.asarray(positions, dtype=np.float32)
    triangles = np.asarray(faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ExAvatarQuest2HairEnvelopeError("hair donor vertices are invalid")
    if triangles.ndim != 2 or triangles.shape[1] != 3 or len(triangles) < 1:
        raise ExAvatarQuest2HairEnvelopeError("hair donor faces are invalid")
    normals = np.zeros_like(vertices, dtype=np.float64)
    for a, b, c in triangles:
        if min(int(a), int(b), int(c)) < 0 or max(int(a), int(b), int(c)) >= len(vertices):
            raise ExAvatarQuest2HairEnvelopeError("hair donor face escapes vertex universe")
        edge1 = vertices[b].astype(np.float64) - vertices[a].astype(np.float64)
        edge2 = vertices[c].astype(np.float64) - vertices[a].astype(np.float64)
        normal = np.cross(edge1, edge2)
        normals[a] += normal
        normals[b] += normal
        normals[c] += normal
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(~np.isfinite(lengths)) or np.any(lengths <= 1e-12):
        raise ExAvatarQuest2HairEnvelopeError("hair donor contains invalid vertex normals")
    return (normals / lengths[:, None]).astype(np.float32)


def _teacher_outward_offsets(
    *,
    torch: Any,
    np: Any,
    donor_positions: Any,
    donor_normals: Any,
    teacher_points: Any,
    device: Any,
) -> Any:
    donor = torch.as_tensor(
        np.asarray(donor_positions, dtype=np.float32),
        dtype=torch.float32,
        device=device,
    )
    normals = torch.as_tensor(
        np.asarray(donor_normals, dtype=np.float32),
        dtype=torch.float32,
        device=device,
    )
    teacher = torch.as_tensor(
        np.asarray(teacher_points, dtype=np.float32),
        dtype=torch.float32,
        device=device,
    )
    if teacher.ndim != 2 or teacher.shape[1] != 3 or teacher.shape[0] < 16:
        raise ExAvatarQuest2HairEnvelopeError("accepted ExAvatar teacher point universe is invalid")

    height = float((donor[:, 1].max() - donor[:, 1].min()).item())
    if not math.isfinite(height) or height <= 1e-6:
        raise ExAvatarQuest2HairEnvelopeError("hair donor height is invalid")
    max_distance = height * 0.20

    offsets = torch.zeros((donor.shape[0],), dtype=torch.float32, device=device)
    with torch.no_grad():
        for start in range(0, int(teacher.shape[0]), 1024):
            points = teacher[start : start + 1024]
            best_distance = torch.full(
                (points.shape[0],),
                float("inf"),
                dtype=torch.float32,
                device=device,
            )
            best_index = torch.zeros(
                (points.shape[0],),
                dtype=torch.long,
                device=device,
            )
            for donor_start in range(0, int(donor.shape[0]), 4096):
                local = donor[donor_start : donor_start + 4096]
                distance = torch.cdist(points.unsqueeze(0), local.unsqueeze(0)).squeeze(0)
                local_distance, local_index = torch.min(distance, dim=1)
                update = local_distance < best_distance
                best_distance = torch.where(update, local_distance, best_distance)
                best_index = torch.where(update, local_index + donor_start, best_index)

            delta = points - donor[best_index]
            projection = torch.sum(delta * normals[best_index], dim=1)
            valid = (
                torch.isfinite(best_distance)
                & torch.isfinite(projection)
                & (best_distance > 0.0)
                & (best_distance <= max_distance)
                & (projection > 0.0)
                & (projection <= max_distance)
            )
            values = torch.where(valid, projection, torch.zeros_like(projection))
            if hasattr(offsets, "scatter_reduce_"):
                offsets.scatter_reduce_(0, best_index, values, reduce="amax", include_self=True)
            else:
                for index, value in zip(
                    best_index.detach().cpu().tolist(),
                    values.detach().cpu().tolist(),
                ):
                    if value > float(offsets[index].item()):
                        offsets[index] = float(value)

    result = offsets.detach().cpu().numpy().astype(np.float64)
    if not np.any(result > 0.0):
        raise ExAvatarQuest2HairEnvelopeError(
            "accepted ExAvatar teacher produced no outward head/body refinement"
        )
    return result


def build_hair_envelope(
    *,
    candidate_workspace: str | Path,
    exavatar_workspace_root: str | Path,
) -> dict[str, Any]:
    candidate_root = Path(candidate_workspace).expanduser().resolve()
    exavatar_root = Path(exavatar_workspace_root).expanduser().resolve()
    request_path = candidate_root / "request.json"
    staged_root = candidate_root / "staged-teacher"
    candidate_receipt_path = candidate_root / "p3-quest2-student-candidate-receipt.json"
    candidate_output_root = candidate_root / "output"

    for path, label in (
        (request_path, "P3 candidate request"),
        (candidate_receipt_path, "P3 candidate receipt"),
    ):
        if not path.is_file() or path.is_symlink():
            raise ExAvatarQuest2HairEnvelopeError(f"{label} is missing/not regular: {path}")
    if not staged_root.is_dir() or staged_root.is_symlink():
        raise ExAvatarQuest2HairEnvelopeError("P3 staged teacher root is missing/not regular")

    request = _read_json(request_path, label="P3 candidate request")
    try:
        _validate_request(
            request,
            adapter=str(request.get("adapter")),
            revision=str(request.get("adapter_revision")),
            representation=str(request.get("student_representation")),
            student_components=",".join(str(item) for item in request.get("student_components", [])),
        )
        candidate = validate_candidate_receipt(
            _read_json(candidate_receipt_path, label="P3 candidate receipt"),
            candidate_output_root=candidate_output_root,
        )
        if candidate["p3_device_distillation_request_sha256"] != request[
            "p3_device_distillation_request_sha256"
        ]:
            raise ExAvatarQuest2HairEnvelopeError(
                "candidate receipt/request lineage differs before hair extraction"
            )
        repo = _verify_workspace(exavatar_root, request)
        sources = _verify_staged_teacher(request, staged_root)
    except (Quest2StudentCandidateError, ValueError) as exc:
        raise ExAvatarQuest2HairEnvelopeError(str(exc)) from exc

    subject = "bodyrig-p3-hair"
    with tempfile.TemporaryDirectory(prefix="bodyrig-p3-exavatar-hair-") as temp:
        try:
            main_dir = _prepare_exavatar_stage(
                stage=Path(temp),
                repo=repo,
                sources=sources,
                subject=subject,
            )
            state = _load_zero_pose_teacher(main_dir=main_dir, subject=subject)
        except Quest2StudentCandidateError as exc:
            raise ExAvatarQuest2HairEnvelopeError(str(exc)) from exc

    np = state["np"]
    torch = state["torch"]
    donor_positions = np.asarray(state["zero_mesh"], dtype=np.float32)
    donor_faces = np.asarray(state["faces"], dtype=np.int64)
    teacher_points = np.asarray(state["teacher_xyz"], dtype=np.float32)
    normals = _vertex_normals(np, donor_positions, donor_faces)
    offsets = _teacher_outward_offsets(
        torch=torch,
        np=np,
        donor_positions=donor_positions,
        donor_normals=normals,
        teacher_points=teacher_points,
        device=state["device"],
    )

    try:
        selection = select_teacher_hair_faces(
            donor_positions=donor_positions.tolist(),
            donor_normals=normals.tolist(),
            donor_faces=donor_faces.tolist(),
            outward_offsets=offsets.tolist(),
        )
    except PhotorealP3Quest2HairComponentError as exc:
        raise ExAvatarQuest2HairEnvelopeError(str(exc)) from exc

    selected_faces = []
    for face_index in selection["selected_face_indices"]:
        triangle = donor_faces[int(face_index)]
        selected_faces.append(
            {
                "face_index": int(face_index),
                "corner_offsets": [
                    round(float(offsets[int(vertex)]), 9)
                    for vertex in triangle
                ],
            }
        )

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": candidate["performer_id"],
        "selected_epoch_id": candidate["selected_epoch_id"],
        "teacher_input_sha256": candidate["teacher_input_sha256"],
        "p3_device_distillation_request_sha256": candidate[
            "p3_device_distillation_request_sha256"
        ],
        "p3_quest2_student_candidate_receipt_sha256": candidate[
            "p3_quest2_student_candidate_receipt_sha256"
        ],
        "teacher_checkpoint_sha256": _sha_file(sources["teacher-checkpoint"]),
        "generator_sha256": _sha_file(Path(__file__).resolve()),
        "body_vertex_count": int(donor_positions.shape[0]),
        "body_face_count": int(donor_faces.shape[0]),
        "teacher_point_count": int(teacher_points.shape[0]),
        "selection_mode": selection["selection_mode"],
        "selected_face_count": selection["selected_face_count"],
        "selected_vertex_count": selection["selected_vertex_count"],
        "seed_face_count": selection["seed_face_count"],
        "body_height": round(float(selection["body_height"]), 9),
        "head_search_radius": round(float(selection["head_search_radius"]), 9),
        "outward_offset_p50": round(float(selection["outward_offset_p50"]), 9),
        "outward_offset_p95": round(float(selection["outward_offset_p95"]), 9),
        "outward_offset_max": round(float(selection["outward_offset_max"]), 9),
        "head_footprint_span_body_ratio": round(
            float(selection["head_footprint_span_body_ratio"]), 9
        ),
        "vertical_span_body_ratio": round(float(selection["vertical_span_body_ratio"]), 9),
        "selected_faces": selected_faces,
        "source_derived": True,
        "generative_geometry": False,
        "body_topology_modified": False,
        "physical_silhouette_review_required": True,
        "hair_component_authority": False,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["hair_envelope_sha256"] = _digest(result, omit="hair_envelope_sha256")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Derive a bounded connected Quest2 hair shell from exact accepted "
            "ExAvatar teacher geometry without granting visual/runtime authority."
        )
    )
    parser.add_argument("--candidate-workspace", type=Path, required=True)
    parser.add_argument("--exavatar-workspace-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        output = args.output.expanduser().resolve()
        if output.exists():
            raise ExAvatarQuest2HairEnvelopeError(f"hair envelope output already exists: {output}")
        result = build_hair_envelope(
            candidate_workspace=args.candidate_workspace,
            exavatar_workspace_root=args.exavatar_workspace_root,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, ExAvatarQuest2HairEnvelopeError) as exc:
        print(f"BodyRig ExAvatar Quest2 teacher hair: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P3_QUEST2_TEACHER_HAIR_ENVELOPE_READY",
                "selection_mode": result["selection_mode"],
                "selected_face_count": result["selected_face_count"],
                "selected_vertex_count": result["selected_vertex_count"],
                "physical_silhouette_review_required": True,
                "hair_component_authority": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
