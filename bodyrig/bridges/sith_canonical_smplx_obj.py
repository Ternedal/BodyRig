#!/usr/bin/env python
"""Regenerate the canonical SMPL-X OBJ from SiTH's final fit parameters.

Pinned SiTH exports its debug JSON after the final optimizer step but exports the
OBJ from the vertices computed immediately before that step. BodyRig therefore
rebuilds the private OBJ from the final parameters without modifying the pinned
SiTH checkout.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

FIT_PARAM_LENGTHS = {
    "global_orient": 3,
    "body_pose": 63,
    "betas": 10,
    "left_hand_pose": 45,
    "right_hand_pose": 45,
    "jaw_pose": 3,
    "expression": 10,
    "leye_pose": 3,
    "reye_pose": 3,
    "transl": 3,
    "scale": 1,
}
SMPLX_GENDERS = ("female", "male", "neutral")


class CanonicalSmplxError(RuntimeError):
    pass


def _finite_vector(value: Any, *, field: str, length: int) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise CanonicalSmplxError(f"fit parameter {field} must contain exactly {length} values")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise CanonicalSmplxError(f"fit parameter {field} contains a non-finite value")
        result.append(float(item))
    return result


def load_fit_params(path: str | Path) -> dict[str, list[float]]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CanonicalSmplxError("fit parameter JSON is invalid") from exc
    if not isinstance(value, dict) or set(value) != set(FIT_PARAM_LENGTHS):
        raise CanonicalSmplxError("fit parameter fields do not match BodyRig v1")
    params = {
        field: _finite_vector(value[field], field=field, length=length)
        for field, length in FIT_PARAM_LENGTHS.items()
    }
    if not 0.05 <= params["scale"][0] <= 20.0:
        raise CanonicalSmplxError("fit scale is outside the accepted range")
    return params


def write_obj(
    path: str | Path,
    vertices: Iterable[Sequence[float]],
    faces: Iterable[Sequence[int]],
) -> Path:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            vertex_count = 0
            for raw in vertices:
                values = tuple(float(raw[index]) for index in range(3))
                if not all(math.isfinite(value) for value in values):
                    raise CanonicalSmplxError("canonical SMPL-X vertex is non-finite")
                stream.write("v " + " ".join(format(value, ".10g") for value in values) + "\n")
                vertex_count += 1
            face_count = 0
            for raw in faces:
                values = tuple(int(raw[index]) for index in range(3))
                if any(value < 0 or value >= vertex_count for value in values):
                    raise CanonicalSmplxError("canonical SMPL-X face index is invalid")
                stream.write(f"f {values[0] + 1} {values[1] + 1} {values[2] + 1}\n")
                face_count += 1
            if vertex_count < 3 or face_count < 1:
                raise CanonicalSmplxError("canonical SMPL-X topology is implausibly small")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return destination


def regenerate(*, model_dir: str, fit_params: str | Path, output: str | Path, gender: str = "neutral") -> Path:
    gender = str(gender).strip().lower()
    if gender not in SMPLX_GENDERS:
        raise CanonicalSmplxError(f"SMPL-X gender must be one of: {', '.join(SMPLX_GENDERS)}")
    params = load_fit_params(fit_params)
    try:
        import torch
        from smplx import SMPLX
    except ImportError as exc:
        raise CanonicalSmplxError("torch and smplx are required in the SiTH environment") from exc
    if not torch.cuda.is_available():
        raise CanonicalSmplxError("canonical SMPL-X regeneration requires CUDA")

    device = torch.device("cuda")
    try:
        model = SMPLX(
            model_path=model_dir,
            gender=gender,
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        ).to(device)
    except Exception as exc:
        raise CanonicalSmplxError(f"failed to load the licensed SMPL-X {gender} model") from exc
    model.eval()

    def tensor(field: str, width: int) -> Any:
        return torch.tensor(params[field], dtype=torch.float32, device=device).view(1, width)

    with torch.no_grad():
        result = model(
            betas=tensor("betas", 10),
            expression=tensor("expression", 10),
            global_orient=tensor("global_orient", 3),
            body_pose=tensor("body_pose", 63),
            left_hand_pose=tensor("left_hand_pose", 45),
            right_hand_pose=tensor("right_hand_pose", 45),
            jaw_pose=tensor("jaw_pose", 3),
            leye_pose=tensor("leye_pose", 3),
            reye_pose=tensor("reye_pose", 3),
            transl=tensor("transl", 3),
            return_verts=True,
        )
        vertices = (result.vertices[0] * float(params["scale"][0])).detach().cpu().tolist()
    return write_obj(output, vertices, model.faces.tolist())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate BodyRig's canonical SMPL-X OBJ from final SiTH fit parameters.")
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--fit-params", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--gender", choices=SMPLX_GENDERS, default="neutral")
    args = parser.parse_args(argv)
    try:
        destination = regenerate(model_dir=args.smplx_model_dir, fit_params=args.fit_params, output=args.output, gender=args.gender)
    except (CanonicalSmplxError, OSError) as exc:
        print(f"BodyRig canonical SMPL-X OBJ: FAIL: {exc}", file=__import__("sys").stderr)
        return 1
    print(f"BodyRig canonical SMPL-X OBJ: PASS | gender={args.gender} | {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
