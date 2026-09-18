from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .photoreal_exavatar_preflight import (
    PhotorealExAvatarPreflightError,
    build_exavatar_preflight,
)

# These assets are listed/read by the pinned ExAvatar checkout but were not
# part of the first BodyRig preflight inventory. Keep this supplemental layer
# fail-closed so an incomplete benchmark environment can never report READY.
STRICT_FLAME_ASSETS: tuple[tuple[str, str], ...] = (
    ("flame_dynamic_embedding", "human_model_files/flame/flame_dynamic_embedding.npy"),
    ("flame_static_embedding", "human_model_files/flame/flame_static_embedding.pkl"),
    ("flame_texture", "human_model_files/flame/FLAME_texture.npz"),
)

# The pinned Hand4Whole demo imports utils.human_models at process startup.
# That module instantiates both SMPLX() and SMPL(), and directly opens the
# J14 regressor. Its documented human-model tree also supplies MANO files used
# by the vendored SMPL-X utilities. ExAvatar's first preflight did not include
# these files because its own fitting/avatar code does not open them directly.
STRICT_HAND4WHOLE_ASSETS: tuple[tuple[str, str], ...] = (
    ("hand4whole_smpl_neutral", "human_model_files/smpl/SMPL_NEUTRAL.pkl"),
    ("hand4whole_smplx_to_j14", "human_model_files/smplx/SMPLX_to_J14.pkl"),
    ("hand4whole_mano_left", "human_model_files/mano/MANO_LEFT.pkl"),
    ("hand4whole_mano_right", "human_model_files/mano/MANO_RIGHT.pkl"),
)

STRICT_EXTRA_ASSETS = STRICT_FLAME_ASSETS + STRICT_HAND4WHOLE_ASSETS


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
    existing_paths = {str(item.get("relative_path") or "") for item in asset_records if isinstance(item, dict)}

    for name, relative in STRICT_EXTRA_ASSETS:
        if name in existing_names:
            raise PhotorealExAvatarPreflightError(f"strict ExAvatar asset name collides with base preflight: {name}")
        if relative in existing_paths:
            raise PhotorealExAvatarPreflightError(f"strict ExAvatar asset path collides with base preflight: {relative}")
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
        existing_names.add(name)
        existing_paths.add(relative)

    blockers = sorted(set(blockers))
    result["assets"] = asset_records
    result["strict_upstream_asset_inventory"] = True
    result["strict_flame_asset_count"] = len(STRICT_FLAME_ASSETS)
    result["strict_hand4whole_asset_count"] = len(STRICT_HAND4WHOLE_ASSETS)
    result["strict_extra_asset_count"] = len(STRICT_EXTRA_ASSETS)
    result["blockers"] = blockers
    result["benchmark_environment_ready"] = not blockers
    _recompute_digest(result)
    return result


def validate_exavatar_preflight_strict_file(
    preflight_path: str | Path,
    *,
    dependency_root: str | Path,
    asset_root: str | Path,
    reference_model_root: str | Path,
    smplx_gender: str,
    require_colmap: bool = True,
) -> dict[str, Any]:
    source = Path(preflight_path).expanduser().resolve()
    try:
        existing = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealExAvatarPreflightError(f"ExAvatar preflight output is unreadable: {source}") from exc
    if not isinstance(existing, dict):
        raise PhotorealExAvatarPreflightError("ExAvatar preflight output must be a JSON object")
    expected = build_exavatar_preflight_strict(
        dependency_root=dependency_root,
        asset_root=asset_root,
        reference_model_root=reference_model_root,
        smplx_gender=smplx_gender,
        require_colmap=require_colmap,
    )
    if existing != expected:
        raise PhotorealExAvatarPreflightError(
            "existing ExAvatar strict preflight does not match the current pinned environment/assets"
        )
    return existing


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
