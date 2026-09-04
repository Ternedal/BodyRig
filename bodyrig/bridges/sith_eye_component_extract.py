from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import sith_smplx_vrm_fitter as base


FORMAT = "bodyrig-eye-component-candidate"
VERSION = 1
LEFT_EYE_JOINT = 23
RIGHT_EYE_JOINT = 24
MIN_EYE_FACE_COUNT = 8
VERTEX_EYE_WEIGHT_THRESHOLD = 0.35
FACE_EYE_WEIGHT_THRESHOLD = 0.45


class EyeComponentExtractError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_eye_faces(
    *,
    lbs_weights: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    joint_index: int,
) -> list[int]:
    if joint_index < 0:
        raise EyeComponentExtractError("eye joint index is invalid")
    if len(lbs_weights) < 3 or not faces:
        raise EyeComponentExtractError("eye component topology is incomplete")
    selected: list[int] = []
    for face_index, face in enumerate(faces):
        if len(face) != 3:
            raise EyeComponentExtractError("eye component source topology is not triangular")
        values: list[float] = []
        for raw_vertex in face:
            vertex = int(raw_vertex)
            if vertex < 0 or vertex >= len(lbs_weights):
                raise EyeComponentExtractError("eye component face index is outside weight topology")
            row = lbs_weights[vertex]
            if joint_index >= len(row):
                raise EyeComponentExtractError("eye joint is outside SMPL-X LBS topology")
            weight = float(row[joint_index])
            if not math.isfinite(weight) or weight < 0.0:
                raise EyeComponentExtractError("eye component LBS weight is invalid")
            values.append(weight)
        # Explicit eye components must be interior eye geometry, never a mixed
        # eye/face boundary triangle. Requiring all three corners to carry eye
        # authority keeps eyelid/skin faces out of this component fail-closed.
        if all(value >= VERTEX_EYE_WEIGHT_THRESHOLD for value in values) and sum(values) / 3.0 >= FACE_EYE_WEIGHT_THRESHOLD:
            selected.append(face_index)
    return selected


def _write_obj(path: Path, *, positions: Sequence[Sequence[float]], faces: Sequence[Sequence[int]], selected: Sequence[int]) -> None:
    vertices = sorted({int(vertex) for face_index in selected for vertex in faces[face_index]})
    remap = {vertex: index + 1 for index, vertex in enumerate(vertices)}
    lines: list[str] = []
    for vertex in vertices:
        x, y, z = positions[vertex]
        lines.append(f"v {float(x):.9f} {float(y):.9f} {float(z):.9f}")
    for face_index in selected:
        a, b, c = (remap[int(vertex)] for vertex in faces[face_index])
        lines.append(f"f {a} {b} {c}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract(*, model_dir: Path, target_family: str, donor_obj: Path, output_dir: Path) -> dict[str, Any]:
    if target_family not in {"female", "male", "neutral"}:
        raise EyeComponentExtractError("eye component target model family is invalid")
    try:
        import numpy as np
        import torch
        from smplx import SMPLX
    except ImportError as exc:
        raise EyeComponentExtractError(f"eye component dependencies are unavailable: {exc}") from exc

    donor_obj = donor_obj.expanduser().resolve()
    model_dir = model_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise EyeComponentExtractError(f"eye component output already exists: {output_dir}")
    if not donor_obj.is_file():
        raise EyeComponentExtractError("eye component donor OBJ is missing")
    positions = base._parse_positions(donor_obj)
    try:
        model = SMPLX(
            model_path=str(model_dir),
            gender=target_family,
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        )
    except Exception as exc:
        raise EyeComponentExtractError(f"failed to load licensed SMPL-X {target_family} model") from exc

    weights_raw = model.lbs_weights.detach().cpu().numpy()
    if int(weights_raw.shape[0]) != len(positions):
        raise EyeComponentExtractError("eye component donor topology does not match SMPL-X LBS weights")
    weights = np.asarray(weights_raw, dtype=np.float64).tolist()
    faces_raw = getattr(model, "faces", None)
    if faces_raw is None:
        faces_raw = getattr(model, "faces_tensor", None)
        if faces_raw is None:
            raise EyeComponentExtractError("SMPL-X model exposes no face topology")
        faces_values = faces_raw.detach().cpu().tolist()
    else:
        faces_values = faces_raw.tolist() if hasattr(faces_raw, "tolist") else list(faces_raw)
    faces = [[int(value) for value in face] for face in faces_values]

    left = select_eye_faces(lbs_weights=weights, faces=faces, joint_index=LEFT_EYE_JOINT)
    right = select_eye_faces(lbs_weights=weights, faces=faces, joint_index=RIGHT_EYE_JOINT)
    if len(left) < MIN_EYE_FACE_COUNT or len(right) < MIN_EYE_FACE_COUNT:
        raise EyeComponentExtractError(
            f"SMPL-X eye geometry is insufficiently isolated by LBS authority (left={len(left)}, right={len(right)})"
        )
    if set(left) & set(right):
        raise EyeComponentExtractError("left/right eye geometry overlaps under LBS authority")

    output_dir.mkdir(parents=True, exist_ok=False)
    left_obj = output_dir / "left_eye.obj"
    right_obj = output_dir / "right_eye.obj"
    _write_obj(left_obj, positions=positions, faces=faces, selected=left)
    _write_obj(right_obj, positions=positions, faces=faces, selected=right)
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "method": "smplx-eye-joint-lbs-submesh-v1",
        "targetModelFamily": target_family,
        "donorObjSha256": _sha256(donor_obj),
        "leftEyeObjSha256": _sha256(left_obj),
        "rightEyeObjSha256": _sha256(right_obj),
        "leftEyeFaceCount": len(left),
        "rightEyeFaceCount": len(right),
        "leftEyeJointIndex": LEFT_EYE_JOINT,
        "rightEyeJointIndex": RIGHT_EYE_JOINT,
        "explicitEyeGeometry": True,
        "geometryAuthority": "licensed-smplx-lbs-and-subject-fit",
        "sourceDerivedIrisAppearance": False,
        "irisAppearanceStatus": "missing",
        "cornealMaterialStatus": "missing",
        "eyelashStatus": "missing",
        "bodyTopologyModified": False,
        "generativeIdentitySynthesis": False,
        "componentStatus": "partial",
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
    }
    (output_dir / "eye-component-candidate.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract explicit eye geometry candidates from SMPL-X LBS authority.")
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--target-family", required=True, choices=("female", "male", "neutral"))
    parser.add_argument("--donor-obj", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = extract(
            model_dir=Path(args.smplx_model_dir),
            target_family=args.target_family,
            donor_obj=Path(args.donor_obj),
            output_dir=Path(args.output_dir),
        )
    except Exception as exc:
        print(f"BodyRig eye component extraction: FAIL: {exc}")
        return 1
    print(
        "BodyRig eye component extraction: PARTIAL PASS | "
        f"left_faces={receipt['leftEyeFaceCount']} | right_faces={receipt['rightEyeFaceCount']} | "
        "iris=missing | cornea=missing | human_review=required"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
