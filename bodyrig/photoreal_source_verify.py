from __future__ import annotations

import hashlib
import json
import ntpath
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .photoreal_dataset_plan import INVENTORY_FORMAT, INVENTORY_VERSION
from .stash_path_cache import StashPathCacheError, normalize_origin, validate_cache

FORMAT = "bodyrig-photoreal-source-receipt"
VERSION = 1
DIRECT_PATH_PROOF_FORMAT = "bodyrig-photoreal-direct-path-proof"
DIRECT_PATH_PROOF_VERSION = 1
DIRECT_PATH_MODE = "direct-local"


class PhotorealSourceVerifyError(ValueError):
    pass


HashFile = Callable[[Path], str]
ExistsFile = Callable[[Path], bool]
FileSize = Callable[[Path], int]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealSourceVerifyError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealSourceVerifyError(f"{label} must be a JSON object")
    return value


def translate_stash_path(raw_path: str, mapping: Mapping[str, str]) -> str:
    value = str(raw_path or "").strip()
    if not value:
        raise PhotorealSourceVerifyError("source path is empty")
    normalized = value.replace("/", "\\")
    drive, _ = ntpath.splitdrive(normalized)
    if not drive:
        return normalized

    normalized_folded = normalized.casefold()
    matches: list[tuple[int, str, str]] = []
    for raw_source, raw_target in mapping.items():
        source = str(raw_source or "").strip().replace("/", "\\").rstrip("\\")
        target = str(raw_target or "").strip().replace("/", "\\").rstrip("\\")
        if not source or not target:
            continue
        source_folded = source.casefold()
        if normalized_folded == source_folded:
            matches.append((len(source), source, target))
            continue
        if not normalized_folded.startswith(source_folded):
            continue
        boundary_index = len(source)
        if boundary_index < len(normalized) and normalized[boundary_index] == "\\":
            matches.append((len(source), source, target))

    if not matches:
        return normalized

    _, source_prefix, target_prefix = max(matches, key=lambda item: item[0])
    relative = normalized[len(source_prefix) :].lstrip("\\/")
    if not relative:
        return target_prefix
    return ntpath.join(target_prefix, relative)


def resolve_path_transport(
    path_map: Mapping[str, Any],
    *,
    stash_url: str,
    performer_id: str,
) -> dict[str, Any]:
    if path_map.get("format") == DIRECT_PATH_PROOF_FORMAT:
        version = path_map.get("version")
        if isinstance(version, bool) or not isinstance(version, (int, float)) or version != DIRECT_PATH_PROOF_VERSION:
            raise PhotorealSourceVerifyError("Photoreal direct-path proof format/version mismatch")
        if path_map.get("transport_mode") != DIRECT_PATH_MODE:
            raise PhotorealSourceVerifyError("Photoreal direct-path proof transport mode is invalid")
        try:
            origin = normalize_origin(stash_url)
        except StashPathCacheError as exc:
            raise PhotorealSourceVerifyError(f"Stash URL is invalid for direct-path proof: {exc}") from exc
        if str(path_map.get("stash_origin") or "").strip().lower().rstrip("/") != origin:
            raise PhotorealSourceVerifyError("Photoreal direct-path proof belongs to a different Stash origin")
        performers = path_map.get("performer_ids")
        if performers != [performer_id]:
            raise PhotorealSourceVerifyError("Photoreal direct-path proof performer scope mismatch")
        source_count = path_map.get("source_count")
        if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count < 1:
            raise PhotorealSourceVerifyError("Photoreal direct-path proof source count is invalid")
        if path_map.get("all_sources_directly_readable") is not True:
            raise PhotorealSourceVerifyError("Photoreal direct-path proof lacks direct-readability evidence")
        if path_map.get("mapping") != {} or path_map.get("proof") != []:
            raise PhotorealSourceVerifyError("Photoreal direct-path proof must not contain path remapping authority")
        if path_map.get("build_only") is not True or path_map.get("runtime_dependency") is not False:
            raise PhotorealSourceVerifyError("Photoreal direct-path proof build/runtime boundary is invalid")
        if path_map.get("production_activation") is not False:
            raise PhotorealSourceVerifyError("Photoreal direct-path proof crossed production authority")
        return {
            "mapping": {},
            "cache_mode": "photoreal-direct-local-v1",
            "stash_origin": origin,
        }

    try:
        return validate_cache(
            path_map,
            stash_url=stash_url,
            performer_ids=[performer_id],
            allow_performer_superset=True,
        )
    except StashPathCacheError as exc:
        raise PhotorealSourceVerifyError(f"Stash path map is not valid for photoreal inventory: {exc}") from exc


def _expected_size(item: Mapping[str, Any]) -> int:
    value = item.get("size_bytes")
    if value is None:
        return 0
    if isinstance(value, bool):
        raise PhotorealSourceVerifyError("source size_bytes is invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealSourceVerifyError("source size_bytes is invalid") from exc
    if parsed < 0:
        raise PhotorealSourceVerifyError("source size_bytes cannot be negative")
    return parsed


def _records(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    if inventory.get("format") != INVENTORY_FORMAT or inventory.get("version") != INVENTORY_VERSION:
        raise PhotorealSourceVerifyError("photoreal source inventory format/version mismatch")
    if inventory.get("build_only") is not True or inventory.get("photoreal_teacher_input") is not True:
        raise PhotorealSourceVerifyError("photoreal source inventory authority boundary is invalid")
    if inventory.get("runtime_dependency") is not False or inventory.get("production_activation") is not False:
        raise PhotorealSourceVerifyError("photoreal source inventory crossed runtime/production authority")

    result: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for kind, key, id_field, prefix in (
        ("video", "videos", "scene_id", "scene"),
        ("image", "images", "image_id", "image"),
    ):
        values = inventory.get(key)
        if not isinstance(values, list):
            raise PhotorealSourceVerifyError(f"photoreal source inventory {key} is invalid")
        for index, item in enumerate(values):
            if not isinstance(item, Mapping):
                raise PhotorealSourceVerifyError(f"photoreal source inventory {key}[{index}] is invalid")
            source_id = str(item.get(id_field) or "").strip()
            path = str(item.get("path") or "").strip()
            if not source_id or not path:
                raise PhotorealSourceVerifyError(f"photoreal {kind} source lacks id/path")
            source_key = f"{prefix}:{source_id}:{path}"
            normalized_key = source_key.casefold()
            if normalized_key in seen_keys:
                raise PhotorealSourceVerifyError(f"duplicate photoreal source key: {source_key}")
            seen_keys.add(normalized_key)
            result.append(
                {
                    "kind": kind,
                    "source_id": source_id,
                    "source_key": source_key,
                    "catalog_path": path,
                    "expected_size_bytes": _expected_size(item),
                }
            )
    if not result:
        raise PhotorealSourceVerifyError("photoreal source inventory has no media to verify")
    return result


def verify_inventory_sources(
    inventory: Mapping[str, Any],
    *,
    path_mapping: Mapping[str, str],
    exists_file: ExistsFile | None = None,
    file_size: FileSize | None = None,
    hash_file: HashFile | None = None,
) -> dict[str, Any]:
    exists = exists_file or (lambda path: path.is_file())
    size_of = file_size or (lambda path: path.stat().st_size)
    hasher = hash_file or _sha256

    verified: list[dict[str, Any]] = []
    seen_local: set[str] = set()
    total_bytes = 0
    for source in _records(inventory):
        translated = translate_stash_path(source["catalog_path"], path_mapping)
        local = Path(translated)
        if not exists(local):
            raise PhotorealSourceVerifyError(
                f"photoreal source is not readable after path mapping: {source['catalog_path']} -> {translated}"
            )
        normalized_key = os.path.normcase(str(local))
        if normalized_key in seen_local:
            raise PhotorealSourceVerifyError(f"multiple inventory entries resolve to the same local file: {translated}")
        seen_local.add(normalized_key)

        observed_size = int(size_of(local))
        if observed_size < 1:
            raise PhotorealSourceVerifyError(f"photoreal source is empty: {translated}")
        expected_size = int(source["expected_size_bytes"])
        if expected_size > 0 and expected_size != observed_size:
            raise PhotorealSourceVerifyError(
                f"photoreal source size changed: {source['catalog_path']} expected={expected_size} observed={observed_size}"
            )
        digest = str(hasher(local)).strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise PhotorealSourceVerifyError(f"photoreal source hash is invalid: {translated}")
        total_bytes += observed_size
        verified.append(
            {
                "kind": source["kind"],
                "source_id": source["source_id"],
                "source_key": source["source_key"],
                "catalog_path": source["catalog_path"],
                "resolved_path": str(local),
                "size_bytes": observed_size,
                "sha256": digest,
            }
        )

    verified.sort(key=lambda item: (item["kind"], item["source_key"].casefold()))
    return {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": str(inventory.get("performer_id") or ""),
        "performer_name": str(inventory.get("performer_name") or ""),
        "source_count": len(verified),
        "video_count": sum(1 for item in verified if item["kind"] == "video"),
        "image_count": sum(1 for item in verified if item["kind"] == "image"),
        "total_bytes": total_bytes,
        "sources": verified,
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "teacher_input_authority": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def verify_inventory_file(
    inventory_path: str | Path,
    path_map_path: str | Path,
    output_path: str | Path,
    *,
    stash_url: str,
) -> dict[str, Any]:
    inventory_file = Path(inventory_path).expanduser().resolve()
    mapping_file = Path(path_map_path).expanduser().resolve()
    inventory_raw = inventory_file.read_bytes()
    inventory = _read_json(inventory_file, label="photoreal source inventory")
    path_map = _read_json(mapping_file, label="Stash path transport proof")
    performer_id = str(inventory.get("performer_id") or "").strip()
    if not performer_id:
        raise PhotorealSourceVerifyError("photoreal source inventory has no performer_id")
    validated = resolve_path_transport(path_map, stash_url=stash_url, performer_id=performer_id)

    result = verify_inventory_sources(inventory, path_mapping=validated["mapping"])
    result["inventory_sha256"] = _sha256_bytes(inventory_raw)
    result["path_map_mode"] = validated["cache_mode"]
    result["stash_origin"] = validated["stash_origin"]

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealSourceVerifyError(f"photoreal source receipt already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
