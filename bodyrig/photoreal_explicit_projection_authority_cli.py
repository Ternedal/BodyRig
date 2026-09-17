from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoreal_explicit_projection_authority import (
    MANIFEST_FORMAT,
    MANIFEST_VERSION,
    PLAN_FORMAT,
    PLAN_VERSION,
    PROJECTION_AUTHORITY_FORMAT,
    PROJECTION_AUTHORITY_VERSION,
    RECEIPT_FORMAT,
    RECEIPT_VERSION,
    SPATIAL_HINT_PROJECTIONS,
)


class PhotorealExplicitProjectionAuthorityCliError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealExplicitProjectionAuthorityCliError(f"{label} is unreadable JSON: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealExplicitProjectionAuthorityCliError(f"{label} must be a JSON object")
    return value


def _require_sha256(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealExplicitProjectionAuthorityCliError(f"{label} is not a SHA-256 digest")
    return result


def _require_source_key(value: Any, *, label: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 4096:
        raise PhotorealExplicitProjectionAuthorityCliError(f"{label} is invalid")
    return result


def _receipt_sha_index(receipt: Mapping[str, Any], *, performer_id: str) -> dict[str, str]:
    version = receipt.get("version")
    if receipt.get("format") != RECEIPT_FORMAT or isinstance(version, bool) or version != RECEIPT_VERSION:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal source receipt format/version mismatch")
    if str(receipt.get("performer_id") or "").strip() != performer_id:
        raise PhotorealExplicitProjectionAuthorityCliError("dataset plan/source receipt performer mismatch")
    if receipt.get("all_sources_readable") is not True or receipt.get("all_sources_sha256_bound") is not True:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal source receipt is incomplete")
    if receipt.get("source_keys_path_specific") is not True:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal source receipt lacks path-specific source keys")
    if receipt.get("build_only") is not True or receipt.get("runtime_dependency") is not False:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal source receipt authority boundary is invalid")
    if receipt.get("production_activation") is not False:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal source receipt crossed production authority")

    sources = receipt.get("sources")
    if not isinstance(sources, list) or not sources:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal source receipt contains no sources")
    result: dict[str, str] = {}
    for raw in sources:
        if not isinstance(raw, Mapping) or str(raw.get("kind") or "").strip() != "video":
            continue
        source_key = _require_source_key(raw.get("source_key"), label="receipt source key")
        if source_key in result:
            raise PhotorealExplicitProjectionAuthorityCliError("photoreal source receipt repeats a source key")
        result[source_key] = _require_sha256(raw.get("sha256"), label="receipt source SHA-256")
    return result


def _spatial_source_keys(plan: Mapping[str, Any]) -> tuple[str, list[str]]:
    version = plan.get("version")
    if plan.get("format") != PLAN_FORMAT or isinstance(version, bool) or version != PLAN_VERSION:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal dataset plan format/version mismatch")
    performer_id = str(plan.get("performer_id") or "").strip()
    if not performer_id:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal dataset plan performer id is invalid")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal dataset plan authority boundary is invalid")
    if plan.get("production_activation") is not False:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal dataset plan crossed production authority")

    result: list[str] = []
    seen: set[str] = set()
    for split in ("train", "evaluation"):
        sources = plan.get(split)
        if not isinstance(sources, list) or not sources:
            raise PhotorealExplicitProjectionAuthorityCliError(f"photoreal dataset plan has no {split} sources")
        for raw in sources:
            if not isinstance(raw, Mapping) or str(raw.get("kind") or "").strip() != "video":
                continue
            projection = str(raw.get("projection") or "").strip()
            if projection not in SPATIAL_HINT_PROJECTIONS:
                continue
            source_key = _require_source_key(raw.get("source_id"), label="dataset source key")
            if source_key in seen:
                raise PhotorealExplicitProjectionAuthorityCliError("photoreal dataset plan repeats a source key")
            seen.add(source_key)
            result.append(source_key)
    if not result:
        raise PhotorealExplicitProjectionAuthorityCliError("photoreal dataset plan contains no spatial sources requiring explicit authority")
    return performer_id, sorted(result)


def _vr180_equi_authority() -> dict[str, Any]:
    return {
        "format": PROJECTION_AUTHORITY_FORMAT,
        "version": PROJECTION_AUTHORITY_VERSION,
        "projection_type": "equi",
        "pose_degrees": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "equirectangular_bounds_fraction": {
            "top": 0.0,
            "bottom": 0.0,
            "left": 0.25,
            "right": 0.25,
        },
        "cubemap_layout": None,
        "cubemap_padding_pixels": None,
        "mesh_projection_crc32": None,
        "mesh_projection_encoding": None,
        "mesh_projection_payload_bytes": None,
        "mesh_projection_geometry_sha256": None,
        "mesh_projection_mesh_count": None,
        "mesh_projection_total_vertex_count": None,
        "mesh_projection_total_index_count": None,
        "mesh_projection_texture_ids": None,
        "mesh_projection_index_types": None,
        "mesh_projection_unknown_box_types": None,
        "deprojection_authority": False,
    }


def build_verified_vr180_manifest(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    stereo_layout: str,
    operator_verified: bool,
) -> dict[str, Any]:
    if operator_verified is not True:
        raise PhotorealExplicitProjectionAuthorityCliError(
            "explicit projection authority requires the operator to verify all selected spatial sources as VR180 equirectangular"
        )
    if stereo_layout not in {"side-by-side", "over-under", "mono"}:
        raise PhotorealExplicitProjectionAuthorityCliError("explicit stereo layout is unsupported")

    performer_id, spatial_keys = _spatial_source_keys(plan)
    receipt_sha = _receipt_sha_index(receipt, performer_id=performer_id)
    missing = [source_key for source_key in spatial_keys if source_key not in receipt_sha]
    if missing:
        raise PhotorealExplicitProjectionAuthorityCliError(
            f"photoreal source receipt does not bind every spatial dataset source ({len(missing)} missing)"
        )

    authority = _vr180_equi_authority()
    return {
        "format": MANIFEST_FORMAT,
        "version": MANIFEST_VERSION,
        "performer_id": performer_id,
        "sources": [
            {
                "source_key": source_key,
                "source_sha256": receipt_sha[source_key],
                "stereo_layout": stereo_layout,
                "authority_basis": "operator-verified",
                "projection_authority": dict(authority),
            }
            for source_key in spatial_keys
        ],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an operator-verified, SHA-bound explicit projection authority manifest for spatial VR180 sources."
    )
    parser.add_argument("--plan", required=True, help="Photoreal dataset-plan.json")
    parser.add_argument("--receipt", required=True, help="SHA-bound photoreal source-receipt.json")
    parser.add_argument("--out", required=True, help="New projection-authority.json output path")
    parser.add_argument(
        "--stereo-layout",
        required=True,
        choices=("side-by-side", "over-under", "mono"),
        help="Operator-verified stereo layout shared by every spatial source in the dataset plan.",
    )
    parser.add_argument(
        "--operator-verified-vr180-equi",
        action="store_true",
        help="Attest that every spatial source selected by the dataset plan is VR180 equirectangular with zero pose rotation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        plan = _read_json(args.plan, label="photoreal dataset plan")
        receipt = _read_json(args.receipt, label="photoreal source receipt")
        manifest = build_verified_vr180_manifest(
            plan,
            receipt,
            stereo_layout=args.stereo_layout,
            operator_verified=args.operator_verified_vr180_equi,
        )
        output = Path(args.out).expanduser().resolve()
        if output.exists():
            raise PhotorealExplicitProjectionAuthorityCliError(
                f"explicit projection authority output already exists: {output}"
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "format": MANIFEST_FORMAT,
                    "performer_id": manifest["performer_id"],
                    "source_count": len(manifest["sources"]),
                    "projection_type": "equi",
                    "geometry": "vr180",
                    "stereo_layout": args.stereo_layout,
                    "operator_verified": True,
                    "production_activation": False,
                    "output": str(output),
                },
                sort_keys=True,
            )
        )
        return 0
    except PhotorealExplicitProjectionAuthorityCliError as exc:
        print(f"BodyRig explicit projection authority: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
