from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import sith_anatomy_texture_bake as anatomy_bake
import sith_eye_component_extract as eye_geometry
import sith_smplx_vrm_fitter as base


FORMAT = "bodyrig-eye-appearance-candidate"
VERSION = 1
BAKE_RESOLUTION = 1024
MASK_PADDING_PIXELS = 4


class EyeAppearanceExtractError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def eye_uv_face_indices(
    *,
    bound_faces: Sequence[Sequence[Sequence[int]]],
    selected_faces: Sequence[int],
) -> list[tuple[int, int, int]]:
    result: list[tuple[int, int, int]] = []
    seen: set[int] = set()
    for raw_face_index in selected_faces:
        face_index = int(raw_face_index)
        if face_index in seen:
            raise EyeAppearanceExtractError("eye appearance face selection contains duplicates")
        seen.add(face_index)
        if face_index < 0 or face_index >= len(bound_faces):
            raise EyeAppearanceExtractError("eye appearance face selection is outside canonical topology")
        face = bound_faces[face_index]
        if len(face) != 3:
            raise EyeAppearanceExtractError("eye appearance canonical face is not triangular")
        uv: list[int] = []
        for corner in face:
            if len(corner) != 2:
                raise EyeAppearanceExtractError("eye appearance canonical corner is invalid")
            index = int(corner[1])
            if index < 0:
                raise EyeAppearanceExtractError("eye appearance UV index is invalid")
            uv.append(index)
        result.append((uv[0], uv[1], uv[2]))
    if not result:
        raise EyeAppearanceExtractError("eye appearance face selection is empty")
    return result


def build_receipt(
    *,
    target_family: str,
    donor_sha256: str,
    reconstruction_sha256: str,
    source_mesh_sha256: str,
    source_texture_sha256: str,
    canonical_bake_sha256: str,
    left_png_sha256: str,
    right_png_sha256: str,
    left_face_count: int,
    right_face_count: int,
    left_mask_pixels: int,
    right_mask_pixels: int,
) -> dict[str, Any]:
    if target_family not in {"female", "male", "neutral"}:
        raise EyeAppearanceExtractError("eye appearance target family is invalid")
    digests = {
        "donorObjSha256": donor_sha256,
        "sourceReconstructionSha256": reconstruction_sha256,
        "sourceMeshSha256": source_mesh_sha256,
        "sourceTextureSha256": source_texture_sha256,
        "canonicalBakeSha256": canonical_bake_sha256,
        "leftEyeAppearancePngSha256": left_png_sha256,
        "rightEyeAppearancePngSha256": right_png_sha256,
    }
    for label, value in digests.items():
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise EyeAppearanceExtractError(f"{label} is not lowercase SHA-256")
    for label, value in (
        ("leftEyeFaceCount", left_face_count),
        ("rightEyeFaceCount", right_face_count),
        ("leftMaskPixelCount", left_mask_pixels),
        ("rightMaskPixelCount", right_mask_pixels),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise EyeAppearanceExtractError(f"{label} is invalid")
    return {
        "format": FORMAT,
        "version": VERSION,
        "method": "canonical-anatomy-bake-eye-face-mask-v1",
        "targetModelFamily": target_family,
        **digests,
        "leftEyeFaceCount": left_face_count,
        "rightEyeFaceCount": right_face_count,
        "leftMaskPixelCount": left_mask_pixels,
        "rightMaskPixelCount": right_mask_pixels,
        "bakeResolution": BAKE_RESOLUTION,
        "sourceDerivedEyeSurfaceAppearance": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "missing",
        "eyelashStatus": "missing",
        "bodyTopologyModified": False,
        "generativeIdentitySynthesis": False,
        "componentStatus": "partial",
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
    }


def _masked_eye_crop(*, image: Any, texcoords: Sequence[Sequence[float]], uv_faces: Sequence[Sequence[int]]) -> tuple[bytes, int]:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError as exc:
        raise EyeAppearanceExtractError(f"Pillow is required for eye appearance masking: {exc}") from exc
    if image.mode != "RGB":
        image = image.convert("RGB")
    width, height = image.size
    if width < 1 or height < 1:
        raise EyeAppearanceExtractError("eye appearance bake has invalid dimensions")
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for face in uv_faces:
        if len(face) != 3:
            raise EyeAppearanceExtractError("eye appearance UV face is not triangular")
        polygon: list[tuple[float, float]] = []
        for raw_index in face:
            index = int(raw_index)
            if index < 0 or index >= len(texcoords):
                raise EyeAppearanceExtractError("eye appearance UV index is outside canonical atlas")
            u, v = texcoords[index]
            u = float(u)
            v = float(v)
            if not math.isfinite(u) or not math.isfinite(v):
                raise EyeAppearanceExtractError("eye appearance UV coordinate is non-finite")
            polygon.append((u * (width - 1), (1.0 - v) * (height - 1)))
        draw.polygon(polygon, fill=255)
    if MASK_PADDING_PIXELS > 0:
        size = 2 * MASK_PADDING_PIXELS + 1
        mask = mask.filter(ImageFilter.MaxFilter(size=size))
    bbox = mask.getbbox()
    if bbox is None:
        raise EyeAppearanceExtractError("eye appearance mask is empty")
    mask_pixels = sum(1 for value in mask.crop(bbox).getdata() if value > 0)
    if mask_pixels < 4:
        raise EyeAppearanceExtractError("eye appearance mask coverage is implausibly small")
    crop = image.crop(bbox).convert("RGBA")
    crop.putalpha(mask.crop(bbox))
    output = io.BytesIO()
    crop.save(output, format="PNG", optimize=False)
    value = output.getvalue()
    if not value.startswith(b"\x89PNG\r\n\x1a\n"):
        raise EyeAppearanceExtractError("eye appearance crop is not PNG")
    return value, mask_pixels


def extract(
    *,
    workspace: Path,
    donor_obj: Path,
    sith_repo: Path,
    model_dir: Path,
    target_family: str,
    output_dir: Path,
) -> dict[str, Any]:
    if target_family not in {"female", "male", "neutral"}:
        raise EyeAppearanceExtractError("eye appearance target family is invalid")
    try:
        import numpy as np
        import torch
        from PIL import Image
        from smplx import SMPLX
    except ImportError as exc:
        raise EyeAppearanceExtractError(f"eye appearance dependencies are unavailable: {exc}") from exc
    if not torch.cuda.is_available():
        raise EyeAppearanceExtractError("eye appearance extraction requires CUDA")

    workspace = workspace.expanduser().resolve()
    donor_obj = donor_obj.expanduser().resolve()
    sith_repo = sith_repo.expanduser().resolve()
    model_dir = model_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise EyeAppearanceExtractError(f"eye appearance output already exists: {output_dir}")
    if not donor_obj.is_file() or not sith_repo.is_dir() or not model_dir.is_dir():
        raise EyeAppearanceExtractError("eye appearance authority paths are missing")

    stage = workspace / "sith-input-v1"
    reconstruction_path = stage / "reconstruction.json"
    source_mesh = stage / "meshes" / "000_reco.obj"
    try:
        reconstruction = json.loads(reconstruction_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EyeAppearanceExtractError("retained reconstruction evidence is unreadable") from exc
    details = reconstruction.get("reconstruction") if isinstance(reconstruction, Mapping) else None
    if not isinstance(details, Mapping):
        raise EyeAppearanceExtractError("retained reconstruction detail block is missing")
    texture_name = details.get("mesh_texture_name")
    if not isinstance(texture_name, str) or Path(texture_name).name != texture_name:
        raise EyeAppearanceExtractError("retained reconstruction texture name is invalid")
    source_texture = stage / "meshes" / texture_name
    for artifact in (reconstruction_path, source_mesh, source_texture):
        if not artifact.is_file():
            raise EyeAppearanceExtractError(f"eye appearance source artifact is missing: {artifact}")

    donor_positions = base._parse_positions(donor_obj)
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
        raise EyeAppearanceExtractError(f"failed to load licensed SMPL-X {target_family} model") from exc
    weights = model.lbs_weights.detach().cpu().numpy().astype(np.float64).tolist()
    faces_raw = getattr(model, "faces", None)
    if faces_raw is None:
        faces_raw = getattr(model, "faces_tensor", None)
        if faces_raw is None:
            raise EyeAppearanceExtractError("SMPL-X model exposes no face topology")
        faces = [[int(value) for value in face] for face in faces_raw.detach().cpu().tolist()]
    else:
        values = faces_raw.tolist() if hasattr(faces_raw, "tolist") else list(faces_raw)
        faces = [[int(value) for value in face] for face in values]
    if len(donor_positions) != len(weights):
        raise EyeAppearanceExtractError("subject donor topology does not match target-family SMPL-X")

    left_faces = eye_geometry.select_eye_faces(
        lbs_weights=weights,
        faces=faces,
        joint_index=eye_geometry.LEFT_EYE_JOINT,
    )
    right_faces = eye_geometry.select_eye_faces(
        lbs_weights=weights,
        faces=faces,
        joint_index=eye_geometry.RIGHT_EYE_JOINT,
    )
    if len(left_faces) < eye_geometry.MIN_EYE_FACE_COUNT or len(right_faces) < eye_geometry.MIN_EYE_FACE_COUNT:
        raise EyeAppearanceExtractError("eye appearance cannot bind sufficient explicit eye geometry")

    texcoords, bound_faces, baked_png, metrics = anatomy_bake.bake_sith_surface_to_anatomy_canonical_smplx(
        torch=torch,
        np=np,
        donor_positions=donor_positions,
        donor_faces=faces,
        sith_repo=sith_repo,
        source_mesh_obj=source_mesh,
        source_texture_path=source_texture,
        model_dir=model_dir,
        gender=target_family,
        device=torch.device("cuda"),
        resolution=BAKE_RESOLUTION,
    )
    left_uv = eye_uv_face_indices(bound_faces=bound_faces, selected_faces=left_faces)
    right_uv = eye_uv_face_indices(bound_faces=bound_faces, selected_faces=right_faces)
    with Image.open(io.BytesIO(baked_png)) as image:
        baked_image = image.convert("RGB")
        left_png, left_pixels = _masked_eye_crop(image=baked_image, texcoords=texcoords, uv_faces=left_uv)
        right_png, right_pixels = _masked_eye_crop(image=baked_image, texcoords=texcoords, uv_faces=right_uv)

    output_dir.mkdir(parents=True, exist_ok=False)
    baked_path = output_dir / "canonical_eye_source_bake.png"
    left_path = output_dir / "left_eye_appearance.png"
    right_path = output_dir / "right_eye_appearance.png"
    baked_path.write_bytes(baked_png)
    left_path.write_bytes(left_png)
    right_path.write_bytes(right_png)

    receipt = build_receipt(
        target_family=target_family,
        donor_sha256=_sha256(donor_obj),
        reconstruction_sha256=_sha256(reconstruction_path),
        source_mesh_sha256=_sha256(source_mesh),
        source_texture_sha256=_sha256(source_texture),
        canonical_bake_sha256=_sha256_bytes(baked_png),
        left_png_sha256=_sha256_bytes(left_png),
        right_png_sha256=_sha256_bytes(right_png),
        left_face_count=len(left_faces),
        right_face_count=len(right_faces),
        left_mask_pixels=left_pixels,
        right_mask_pixels=right_pixels,
    )
    receipt["bakeSurfaceDistanceP95"] = float(metrics["bake_surface_distance_p95"])
    receipt["bakeSurfaceDistanceMax"] = float(metrics["bake_surface_distance_max"])
    (output_dir / "eye-appearance-candidate.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive review-only source eye-surface appearance crops from the canonical anatomy bake.")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--donor-obj", required=True)
    parser.add_argument("--sith-repo", required=True)
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--target-family", required=True, choices=("female", "male", "neutral"))
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = extract(
            workspace=Path(args.workspace),
            donor_obj=Path(args.donor_obj),
            sith_repo=Path(args.sith_repo),
            model_dir=Path(args.smplx_model_dir),
            target_family=args.target_family,
            output_dir=Path(args.output_dir),
        )
    except Exception as exc:
        print(f"BodyRig eye appearance extraction: FAIL: {exc}")
        return 1
    print(
        "BodyRig eye appearance extraction: PARTIAL PASS | "
        f"left_faces={receipt['leftEyeFaceCount']} | right_faces={receipt['rightEyeFaceCount']} | "
        "iris_identity=review-pending | cornea=missing | eyelashes=missing"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
