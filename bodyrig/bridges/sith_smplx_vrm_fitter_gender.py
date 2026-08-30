#!/usr/bin/env python
"""Gender-aware high-fidelity entrypoint for BodyRig's pinned SiTH bridge.

The reviewed fitter still contains a literal SMPL-X ``male`` constructor and the
historical source-shell skinning path.  This wrapper applies two fail-closed,
in-memory patches for the current process only:

* select the requested licensed SMPL-X body model (female/male/neutral), and
* run BodyRig's bounded source-shell repair before BodyPrint adjustment and VRM
  serialization so clothing/silhouette offsets cannot become armpit membranes.

Neither the pinned SiTH checkout nor the reviewed bridge file is modified.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

GENDERS = ("female", "male", "neutral")
GENDER_MARKER = 'gender="male",'
IMPORT_ANCHOR = "from sith_anatomy_guard import (\n"
MESH_ANCHOR = """        rest_positions = torch.cat(rest_chunks, dim=0).numpy()\n        joints4 = torch.cat(joint_chunks, dim=0).numpy()\n        weights4 = torch.cat(weight_chunks, dim=0).numpy()\n\n        adjustment_metrics: dict[str, float] = {\"max_joint_delta\": 0.0}\n"""
QUALITY_ANCHOR = '        "anatomy_guard_distance_max": guarded_distance_max,\n'
PRINT_ANCHOR = """    print(\n        \"BodyRig anatomy guard: \"\n"""


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

    source = _replace_once(
        source,
        IMPORT_ANCHOR,
        "from sith_mesh_fidelity import MeshFidelityError, repair_source_shell\n" + IMPORT_ANCHOR,
        label="source-shell import patch",
    )

    repaired_mesh_block = """        rest_positions = torch.cat(rest_chunks, dim=0).numpy()\n        joints4 = torch.cat(joint_chunks, dim=0).numpy()\n        weights4 = torch.cat(weight_chunks, dim=0).numpy()\n\n        donor_rest_positions = v_shaped[0, selected_nearest].detach().cpu().numpy()\n        try:\n            rest_positions, faces, shell_metrics = repair_source_shell(\n                np=np,\n                rest_positions=rest_positions,\n                donor_rest_positions=donor_rest_positions,\n                joints4=joints4,\n                faces=faces,\n                rest_joints=rest_joints_np,\n            )\n        except MeshFidelityError as exc:\n            raise base.FitterError(f\"SiTH source-shell fidelity repair failed: {exc}\") from exc\n\n        adjustment_metrics: dict[str, float] = {\"max_joint_delta\": 0.0}\n"""
    source = _replace_once(
        source,
        MESH_ANCHOR,
        repaired_mesh_block,
        label="source-shell mesh patch",
    )

    quality_extension = QUALITY_ANCHOR + """        "source_shell_body_height": float(shell_metrics["body_height"]),\n        "source_shell_body_residual_cap": float(shell_metrics["body_residual_cap"]),\n        "source_shell_body_vertices_clamped": float(shell_metrics["body_vertices_clamped"]),\n        "source_shell_head_vertices_preserved": float(shell_metrics["head_shell_vertices_preserved"]),\n        "source_shell_cross_region_faces_removed": float(shell_metrics["cross_region_faces_removed"]),\n        "source_shell_cross_region_face_ratio": float(shell_metrics["cross_region_face_ratio"]),\n"""
    source = _replace_once(
        source,
        QUALITY_ANCHOR,
        quality_extension,
        label="source-shell quality patch",
    )

    print_extension = """    print(\n        \"BodyRig source-shell repair: \"\n        f\"clamped={int(shell_metrics['body_vertices_clamped'])} \"\n        f\"head_preserved={int(shell_metrics['head_shell_vertices_preserved'])} \"\n        f\"cross_region_faces_removed={int(shell_metrics['cross_region_faces_removed'])} \"\n        f\"cross_region_face_ratio={shell_metrics['cross_region_face_ratio']:.6f}\",\n        file=sys.stderr,\n    )\n""" + PRINT_ANCHOR
    source = _replace_once(
        source,
        PRINT_ANCHOR,
        print_extension,
        label="source-shell diagnostic patch",
    )
    return source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--bodyrig-smplx-gender", required=True, choices=GENDERS)
    args, remainder = parser.parse_known_args(argv)

    target = Path(__file__).resolve().with_name("sith_smplx_vrm_fitter_adjusted.py")
    if not target.is_file():
        print("BodyRig gender-aware fitter: FAIL: adjusted fitter source is missing", file=sys.stderr)
        return 1
    try:
        source = target.read_text(encoding="utf-8")
        patched = _patch_source(source, args.bodyrig_smplx_gender)
    except (OSError, UnicodeDecodeError, RuntimeError) as exc:
        print(f"BodyRig gender-aware fitter: FAIL: {exc}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(target.parent))
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
