#!/usr/bin/env python
"""Gender-aware high-fidelity entrypoint for BodyRig donor-topology fitting.

The production fitter keeps licensed SMPL-X model selection process-local and
post-processes the completed VRM with deterministic source-derived appearance
refinements. Geometry authority remains byte-for-byte in
``sith_smplx_vrm_fitter_donor.py``: fitted SMPL-X owns final vertices/faces/LBS.

Appearance is installed process-locally before that fitter executes. The donor
uses SiTH's canonical SMPL-X UV atlas and receives an anatomy-restricted,
normal-aware closest-surface texture bake from the retained SiTH reconstruction.
The reconstruction UV atlas is therefore never serialized onto donor topology.

Neither the pinned SiTH checkout nor licensed SMPL-X assets are modified.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

GENDERS = ("female", "male", "neutral")
GENDER_MARKER = 'gender="male",'
R8_BAKE_RESOLUTION = 1024


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source marker, found {count}")
    return source.replace(old, new, 1)


def _patch_source(source: str, gender: str) -> str:
    source = _replace_once(
        source,
        GENDER_MARKER,
        f"gender={gender!r},",
        label="SMPL-X gender patch",
    )
    source = _replace_once(
        source,
        "failed to load the licensed SMPL-X male model",
        f"failed to load the licensed SMPL-X {gender} model",
        label="SMPL-X gender error patch",
    )
    return source


def _install_pbr_refinement() -> None:
    try:
        import sith_smplx_vrm_fitter as base
        from sith_basecolor_detail import (
            BaseColorDetailError,
            derive_basecolor_detail,
            refine_glb_basecolor,
        )
        from sith_pbr_material import PbrMaterialError, derive_pbr_maps, refine_glb_pbr
    except ImportError as exc:
        raise RuntimeError(f"appearance refinement modules are unavailable: {exc}") from exc

    original = base._build_vrm

    def refined_build_vrm(*args: Any, **kwargs: Any):
        texture_png = kwargs.get("texture_png")
        np = kwargs.get("np")
        if np is None or not isinstance(texture_png, bytes):
            raise base.FitterError("BodyRig appearance refinement requires numpy and the source PNG texture")
        avatar_vrm, thumbnail = original(*args, **kwargs)
        try:
            normal_png, roughness_png, metrics = derive_pbr_maps(np, texture_png)
            refined = refine_glb_pbr(
                avatar_vrm,
                normal_png=normal_png,
                metallic_roughness_png=roughness_png,
                metrics=metrics,
            )
            detail_png, detail_metrics = derive_basecolor_detail(np, texture_png)
            refined = refine_glb_basecolor(
                refined,
                refined_basecolor_png=detail_png,
                metrics=detail_metrics,
            )
        except (PbrMaterialError, BaseColorDetailError) as exc:
            raise base.FitterError(f"source-derived appearance refinement failed: {exc}") from exc
        print(
            "BodyRig source-derived PBR: "
            f"roughness_mean={float(metrics['roughness_mean']):.4f} "
            f"normal_scale={float(metrics['normal_scale']):.3f} "
            f"normal_sha256={str(metrics['normal_texture_sha256'])[:12]}... "
            f"roughness_sha256={str(metrics['metallic_roughness_texture_sha256'])[:12]}...",
            file=sys.stderr,
        )
        print(
            "BodyRig bounded base-color detail: "
            f"strength={float(detail_metrics['detail_strength']):.3f} "
            f"max_delta={float(detail_metrics['max_observed_channel_delta']):.4f} "
            f"mean_delta={float(detail_metrics['mean_abs_channel_delta']):.4f} "
            f"changed={float(detail_metrics['changed_pixel_fraction']):.3f} "
            f"source_sha256={str(detail_metrics['source_basecolor_sha256'])[:12]}... "
            f"refined_sha256={str(detail_metrics['refined_basecolor_sha256'])[:12]}...",
            file=sys.stderr,
        )
        return refined, thumbnail

    base._build_vrm = refined_build_vrm


def _install_canonical_texture_bake(*, model_dir: str, gender: str) -> None:
    try:
        import numpy as np
        import torch
        import sith_anatomy_texture_bake as anatomy_bake
        import sith_donor_vrm_metadata as donor_metadata
        import sith_smplx_vrm_fitter as base
        import sith_surface_uv_transfer as surface_uv
        from sith_anatomy_bake_metadata import (
            AnatomyBakeMetadataError,
            replace_with_anatomy_bake_metadata,
        )
    except ImportError as exc:
        raise RuntimeError(f"anatomy-aware SMPL-X texture bake modules are unavailable: {exc}") from exc

    resolved_model_dir = Path(model_dir).expanduser().resolve()
    if resolved_model_dir.name != "smplx" or resolved_model_dir.parent.name != "body_models":
        raise RuntimeError("anatomy texture bake could not resolve the pinned SiTH repository")
    try:
        sith_repo = resolved_model_dir.parents[2]
    except IndexError as exc:
        raise RuntimeError("anatomy texture bake could not resolve the pinned SiTH repository") from exc
    if not (sith_repo / "data" / "smplx_uv.obj").is_file():
        raise RuntimeError("pinned SiTH canonical SMPL-X UV template is missing")
    if gender not in GENDERS:
        raise RuntimeError("anatomy texture bake gender authority is invalid")

    state: dict[str, Any] = {}
    original_validate_workspace = base._validate_workspace
    refined_build_vrm = base._build_vrm
    original_mark_donor_topology = donor_metadata.mark_donor_topology

    def capture_workspace(workspace: Path, request: dict[str, Any]):
        paths = original_validate_workspace(workspace, request)
        state["paths"] = paths
        return paths

    def canonical_surface_transfer(
        *,
        donor_faces,
        donor_positions,
        source_positions,
        source_faces,
        source_texcoords,
        donor_to_source_vertex,
    ):
        # The legacy source-UV projection API is retained only as an injection
        # point. R8 never executes that projector. Donor geometry is still the
        # fitted SMPL-X mesh; source geometry is used only as appearance input.
        del source_positions, source_faces, source_texcoords, donor_to_source_vertex
        paths = state.get("paths")
        if not isinstance(paths, dict):
            raise surface_uv.SurfaceUvTransferError("anatomy texture bake workspace authority is unavailable")
        if not torch.cuda.is_available():
            raise surface_uv.SurfaceUvTransferError("anatomy texture bake requires CUDA")
        try:
            texcoords, faces, baked_texture, metrics = anatomy_bake.bake_sith_surface_to_anatomy_canonical_smplx(
                torch=torch,
                np=np,
                donor_positions=donor_positions,
                donor_faces=donor_faces,
                sith_repo=sith_repo,
                source_mesh_obj=paths["mesh_obj"],
                source_texture_path=paths["texture"],
                model_dir=resolved_model_dir,
                gender=gender,
                device=torch.device("cuda"),
                resolution=R8_BAKE_RESOLUTION,
            )
        except (anatomy_bake.AnatomyTextureBakeError, OSError, RuntimeError) as exc:
            raise surface_uv.SurfaceUvTransferError(f"anatomy-aware SMPL-X texture bake failed: {exc}") from exc

        bake_metrics = dict(metrics)
        compatibility_metrics = dict(metrics)
        compatibility_metrics["projection_distance_p95"] = 0.0
        compatibility_metrics["projection_distance_max"] = 0.0
        compatibility_metrics["seam_seed_corner_ratio"] = 0.0
        compatibility_metrics["degenerate_source_candidate_count"] = 0.0
        compatibility_metrics["maximum_local_source_face_candidates"] = 1.0

        state["baked_texture"] = baked_texture
        state["bake_metrics"] = bake_metrics
        print(
            "BodyRig anatomy-aware SMPL-X texture bake: "
            f"size={int(float(metrics['bake_width']))}x{int(float(metrics['bake_height']))} "
            f"occupied={float(metrics['bake_occupied_ratio']):.3f} "
            f"surface_p95={float(metrics['bake_surface_distance_p95']):.6f} "
            f"surface_max={float(metrics['bake_surface_distance_max']):.6f} "
            f"normal_retry={float(metrics['normal_retry_texel_ratio']):.3f} "
            f"normal_p05={float(metrics['normal_alignment_p05']):.3f} "
            f"texture_sha256={str(metrics['baked_basecolor_sha256'])[:12]}...",
            file=sys.stderr,
        )
        return texcoords, faces, compatibility_metrics

    def baked_build_vrm(*args: Any, **kwargs: Any):
        baked_texture = state.get("baked_texture")
        if not isinstance(baked_texture, bytes):
            raise base.FitterError("anatomy-aware SMPL-X baked texture was not produced")
        kwargs["texture_png"] = baked_texture
        return refined_build_vrm(*args, **kwargs)

    def baked_mark_donor_topology(avatar_vrm: bytes, *, mapping_metrics):
        bake_metrics = state.get("bake_metrics")
        if not isinstance(bake_metrics, dict):
            raise donor_metadata.DonorVrmMetadataError("anatomy texture bake metrics are unavailable")
        legacy_metrics = dict(mapping_metrics)
        legacy_metrics.update(bake_metrics)
        try:
            marked = original_mark_donor_topology(avatar_vrm, mapping_metrics=legacy_metrics)
            return replace_with_anatomy_bake_metadata(marked, mapping_metrics=bake_metrics)
        except AnatomyBakeMetadataError as exc:
            raise donor_metadata.DonorVrmMetadataError(
                f"anatomy texture bake metadata binding failed: {exc}"
            ) from exc

    base._validate_workspace = capture_workspace
    base._build_vrm = baked_build_vrm
    surface_uv.build_surface_projected_donor_uvs = canonical_surface_transfer
    donor_metadata.mark_donor_topology = baked_mark_donor_topology


def _model_dir_from_remainder(remainder: list[str]) -> str:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smplx-model-dir", required=True)
    try:
        args, _unknown = parser.parse_known_args(remainder)
    except SystemExit as exc:
        raise RuntimeError("SMPL-X model directory is missing from fitter invocation") from exc
    value = str(args.smplx_model_dir).strip()
    if not value:
        raise RuntimeError("SMPL-X model directory is missing from fitter invocation")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--bodyrig-smplx-gender", required=True, choices=GENDERS)
    args, remainder = parser.parse_known_args(argv)

    target = Path(__file__).resolve().with_name("sith_smplx_vrm_fitter_donor.py")
    if not target.is_file():
        print("BodyRig gender-aware fitter: FAIL: donor-topology fitter source is missing", file=sys.stderr)
        return 1
    try:
        source = target.read_text(encoding="utf-8")
        patched = _patch_source(source, args.bodyrig_smplx_gender)
        model_dir = _model_dir_from_remainder(remainder)
    except (OSError, UnicodeDecodeError, RuntimeError) as exc:
        print(f"BodyRig gender-aware fitter: FAIL: {exc}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(target.parent))
    try:
        _install_pbr_refinement()
        _install_canonical_texture_bake(model_dir=model_dir, gender=args.bodyrig_smplx_gender)
    except RuntimeError as exc:
        print(f"BodyRig gender-aware fitter: FAIL: {exc}", file=sys.stderr)
        return 1

    sys.argv = [str(target), *remainder]
    namespace = {
        "__name__": "__main__",
        "__file__": str(target),
        "__package__": None,
        "__cached__": None,
    }
    try:
        exec(compile(patched, str(target), "exec"), namespace, namespace)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(str(code), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
