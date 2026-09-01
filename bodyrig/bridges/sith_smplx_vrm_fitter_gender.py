#!/usr/bin/env python
"""Gender-aware high-fidelity entrypoint for BodyRig donor-topology fitting.

The production fitter keeps licensed SMPL-X model selection process-local and
post-processes the completed VRM with deterministic source-derived appearance
refinements. Geometry authority lives in ``sith_smplx_vrm_fitter_donor.py``:
SMPL-X owns final vertices/faces/LBS, while SiTH supplies source appearance.

Neither the pinned SiTH checkout nor licensed SMPL-X assets are modified.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

GENDERS = ("female", "male", "neutral")
GENDER_MARKER = 'gender="male",'


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
    except (OSError, UnicodeDecodeError, RuntimeError) as exc:
        print(f"BodyRig gender-aware fitter: FAIL: {exc}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(target.parent))
    try:
        _install_pbr_refinement()
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
