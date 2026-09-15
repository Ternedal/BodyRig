from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .photoreal_exavatar_preflight import (
    PhotorealExAvatarPreflightError,
    build_exavatar_preflight,
)

# These assets are listed by the pinned ExAvatar checkout and are read by its
# FLAME/texture code, but were not part of the first BodyRig preflight asset
# inventory. Keep this supplemental layer fail-closed so an old incomplete
# preflight can never report READY through the operator CLI.
STRICT_FLAME_ASSETS: tuple[tuple[str, str], ...] = (
    ("flame_dynamic_embedding", "human_model_files/flame/flame_dynamic_embedding.npy"),
    ("flame_static_embedding", "human_model_files/flame/flame_static_embedding.pkl"),
    ("flame_texture", "human_model_files/flame/FLAME_texture.npz"),
)


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recompute_digest(result: dict[str, Any]) -> None:
    result.pop("preflight_sha256", None)
    canonical = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    result["preflight_sha256"] = hashlib.sha256(canonical).hexdigest()


def build_exavatar_preflight_strict(
    *,
    dependency_root: str | Path,
    asset_root: str | Path,
    reference_model_root: str | Path,
    smplx_gender: str,
    require_colmap: bool = True,
) -> dict[str, Any]:
    result = build_exavatar_preflight(
        dependency_root=dependency_root,
        asset_root=asset_root,
        reference_model_root=reference_model_root,
        smplx_gender=smplx_gender,
        require_colmap=require_colmap,
    )

    assets_root = Path(asset_root).expanduser().resolve()
    blockers = list(result.get("blockers") or [])
    asset_records = list(result.get("assets") or [])
    existing_names = {str(item.get("name") or "") for item in asset_records if isinstance(item, dict)}

    for name, relative in STRICT_FLAME_ASSETS:
        if name in existing_names:
            raise PhotorealExAvatarPreflightError(f"strict ExAvatar asset name collides with base preflight: {name}")
        path = assets_root / relative
        record: dict[str, Any] = {
            "name": name,
            "relative_path": relative,
            "restricted_or_operator_supplied": True,
            "present": path.is_file(),
            "size_bytes": 0,
            "sha256": None,
        }
        if not path.is_file():
            blockers.append(f"missing asset: {relative}")
        else:
            size = path.stat().st_size
            if size < 1:
                blockers.append(f"empty asset: {relative}")
            else:
                record["size_bytes"] = size
                record["sha256"] = _file_sha(path)
        asset_records.append(record)

    blockers = sorted(set(blockers))
    result["assets"] = asset_records
    result["strict_upstream_asset_inventory"] = True
    result["strict_flame_asset_count"] = len(STRICT_FLAME_ASSETS)
    result["blockers"] = blockers
    result["benchmark_environment_ready"] = not blockers
    _recompute_digest(result)
    return result


def build_exavatar_preflight_strict_files(
    *,
    dependency_root: str | Path,
    asset_root: str | Path,
    reference_model_root: str | Path,
    smplx_gender: str,
    output_path: str | Path,
    require_colmap: bool = True,
) -> dict[str, Any]:
    result = build_exavatar_preflight_strict(
        dependency_root=dependency_root,
        asset_root=asset_root,
        reference_model_root=reference_model_root,
        smplx_gender=smplx_gender,
        require_colmap=require_colmap,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealExAvatarPreflightError(f"ExAvatar preflight output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
