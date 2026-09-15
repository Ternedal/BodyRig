from __future__ import annotations

import json
import ntpath
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from .photoreal_source_verify import translate_stash_path
from .stash_path_cache import FORMAT, VERSION, StashPathCacheError, normalize_origin, validate_cache

INVENTORY_FORMAT = "bodyrig-photoreal-source-inventory"
INVENTORY_VERSION = 1
NEGATIVE_INVENTORY_FORMAT = "bodyrig-photoreal-identity-negative-inventory"
NEGATIVE_INVENTORY_VERSION = 1
NEGATIVE_LABEL_AUTHORITY = "stash-single-performer-other-id-v1"
DIRECT_PATH_PROOF_FORMAT = "bodyrig-photoreal-direct-path-proof"
DIRECT_PATH_PROOF_VERSION = 1
DIRECT_PATH_SCOPE_PRIMARY = "primary"
DIRECT_PATH_SCOPE_NEGATIVE_CALIBRATION = "negative-calibration"
_DRIVE = re.compile(r"^[A-Za-z]:$")


class PhotorealInventoryPathMapError(ValueError):
    pass


IsFile = Callable[[str], bool]
IsDir = Callable[[str], bool]


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealInventoryPathMapError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealInventoryPathMapError(f"{label} must be a JSON object")
    return value


def _strict_v1(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and value == 1


def _strict_bool(value: Any, expected: bool) -> bool:
    return isinstance(value, bool) and value is expected


def _inventory_paths(inventory: Mapping[str, Any]) -> tuple[str, list[str]]:
    if inventory.get("format") != INVENTORY_FORMAT or not _strict_v1(inventory.get("version")):
        raise PhotorealInventoryPathMapError("photoreal source inventory format/version mismatch")
    summary = inventory.get("summary")
    if not isinstance(summary, Mapping) or not _strict_bool(summary.get("source_universe_exhaustive"), True):
        raise PhotorealInventoryPathMapError("photoreal source inventory is not exhaustive")
    if not _strict_bool(inventory.get("photoreal_teacher_input"), True):
        raise PhotorealInventoryPathMapError("photoreal source inventory lacks teacher-input authority")
    if not _strict_bool(inventory.get("build_only"), True):
        raise PhotorealInventoryPathMapError("photoreal source inventory is not build-only")
    if not _strict_bool(inventory.get("runtime_dependency"), False) or not _strict_bool(
        inventory.get("production_activation"), False
    ):
        raise PhotorealInventoryPathMapError("photoreal source inventory crossed runtime/production authority")

    performer_id = inventory.get("performer_id")
    if not isinstance(performer_id, str) or not performer_id.strip():
        raise PhotorealInventoryPathMapError("photoreal source inventory performer_id is invalid")

    paths: list[str] = []
    for key, expected_count_field in (("videos", "video_file_count"), ("images", "image_file_count")):
        values = inventory.get(key)
        if not isinstance(values, list):
            raise PhotorealInventoryPathMapError(f"photoreal source inventory {key} is invalid")
        expected_count = inventory.get(expected_count_field)
        if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count != len(values):
            raise PhotorealInventoryPathMapError(f"photoreal source inventory {expected_count_field} mismatch")
        for index, raw in enumerate(values):
            if not isinstance(raw, Mapping):
                raise PhotorealInventoryPathMapError(f"photoreal source inventory {key}[{index}] is invalid")
            path = raw.get("path")
            if not isinstance(path, str) or not path.strip():
                raise PhotorealInventoryPathMapError(f"photoreal source inventory {key}[{index}] path is invalid")
            paths.append(path.strip().replace("/", "\\"))

    if not paths:
        raise PhotorealInventoryPathMapError("photoreal source inventory contains no source paths")
    return performer_id.strip(), paths


def _negative_paths(inventory: Mapping[str, Any], *, performer_id: str) -> list[str]:
    if inventory.get("format") != NEGATIVE_INVENTORY_FORMAT or not _strict_v1(inventory.get("version")):
        raise PhotorealInventoryPathMapError("identity negative inventory format/version mismatch")
    if inventory.get("label_authority") != NEGATIVE_LABEL_AUTHORITY:
        raise PhotorealInventoryPathMapError("identity negative inventory label authority mismatch")
    target = inventory.get("target_performer_id")
    if not isinstance(target, str) or target.strip() != performer_id:
        raise PhotorealInventoryPathMapError("identity negative inventory targets a different performer")
    for field, expected in (
        ("calibration_only", True),
        ("photoreal_teacher_input", False),
        ("teacher_training_authorized", False),
        ("identity_matching_authorized", False),
        ("build_only", True),
        ("runtime_dependency", False),
        ("production_activation", False),
    ):
        if not _strict_bool(inventory.get(field), expected):
            raise PhotorealInventoryPathMapError(f"identity negative inventory {field} authority mismatch")

    values = inventory.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealInventoryPathMapError("identity negative inventory contains no sources")
    paths: list[str] = []
    for index, raw in enumerate(values):
        if not isinstance(raw, Mapping):
            raise PhotorealInventoryPathMapError(f"identity negative inventory source {index} is invalid")
        if raw.get("target_performer_id") != performer_id or not _strict_bool(raw.get("target_performer_absent"), True):
            raise PhotorealInventoryPathMapError("identity negative source lacks target-absence authority")
        if raw.get("label_authority") != NEGATIVE_LABEL_AUTHORITY:
            raise PhotorealInventoryPathMapError("identity negative source label authority mismatch")
        path = raw.get("path")
        if not isinstance(path, str) or not path.strip():
            raise PhotorealInventoryPathMapError(f"identity negative inventory source {index} path is invalid")
        paths.append(path.strip().replace("/", "\\"))
    return paths


def _path_prefixes(path: str) -> list[str]:
    normalized = path.replace("/", "\\")
    drive, tail = ntpath.splitdrive(normalized)
    drive = drive.rstrip("\\")
    if not _DRIVE.fullmatch(drive):
        return []
    result = [drive]
    directory = ntpath.dirname(tail).strip("\\")
    if directory:
        parts = [part for part in directory.split("\\") if part]
        for depth in range(1, len(parts) + 1):
            result.append(drive + "\\" + "\\".join(parts[:depth]))
    return result


def _path_under_prefix(path: str, prefix: str) -> bool:
    normalized = path.replace("/", "\\")
    normalized_folded = normalized.casefold()
    folded = prefix.casefold()
    if normalized_folded == folded:
        return True
    return (
        normalized_folded.startswith(folded)
        and len(normalized) > len(prefix)
        and normalized[len(prefix)] == "\\"
    )


def _common_candidate_prefixes(paths: list[str]) -> list[str]:
    if not paths:
        return []
    candidates = _path_prefixes(paths[0])
    return sorted(
        (prefix for prefix in candidates if all(_path_under_prefix(path, prefix) for path in paths)),
        key=lambda item: (len(item), item.casefold()),
        reverse=True,
    )


def _direct_path_proof(
    *,
    performer_id: str,
    origin: str,
    host: str,
    source_scope: str,
    source_count: int,
    timestamp: datetime,
) -> dict[str, Any]:
    return {
        "format": DIRECT_PATH_PROOF_FORMAT,
        "version": DIRECT_PATH_PROOF_VERSION,
        "transport_mode": "direct-local",
        "stash_origin": origin,
        "stash_host": host,
        "performer_ids": [performer_id],
        "source_scope": source_scope,
        "source_count": source_count,
        "all_sources_directly_readable": True,
        "mapping": {},
        "proof": [],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
        "updated_utc": timestamp.isoformat().replace("+00:00", "Z"),
    }


def build_inventory_path_map(
    inventory: Mapping[str, Any],
    *,
    stash_url: str,
    is_file: IsFile,
    is_dir: IsDir,
    negative_inventory: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    performer_id, raw_primary_paths = _inventory_paths(inventory)
    primary_paths = sorted(set(raw_primary_paths), key=str.casefold)
    negative_paths: list[str] = []
    if negative_inventory is not None:
        negative_paths = sorted(set(_negative_paths(negative_inventory, performer_id=performer_id)), key=str.casefold)
        primary_folded = {path.casefold() for path in primary_paths}
        negative_folded = {path.casefold() for path in negative_paths}
        if primary_folded.intersection(negative_folded):
            raise PhotorealInventoryPathMapError(
                "one source path cannot be both target-performer media and target-absent negative calibration media"
            )
    paths = sorted(primary_paths + negative_paths, key=str.casefold)

    try:
        origin = normalize_origin(stash_url)
    except StashPathCacheError as exc:
        raise PhotorealInventoryPathMapError(str(exc)) from exc
    host = urlsplit(origin).hostname or ""
    if not host:
        raise PhotorealInventoryPathMapError("Stash URL has no host")

    drive_paths: dict[str, list[str]] = {}
    for path in paths:
        drive, _ = ntpath.splitdrive(path)
        drive = drive.rstrip("\\")
        if _DRIVE.fullmatch(drive):
            drive_paths.setdefault(drive.upper(), []).append(path)
        elif not is_file(path):
            raise PhotorealInventoryPathMapError(f"source path is neither readable nor a Windows drive path: {path}")

    mapping: dict[str, str] = {}
    proof: list[dict[str, Any]] = []
    for drive, values in sorted(drive_paths.items()):
        share_root = f"\\\\{host}\\VR_{drive[0]}"
        if not is_dir(share_root):
            if all(is_file(path) for path in values):
                continue
            raise PhotorealInventoryPathMapError(
                f"canonical Stash SMB share is not readable for {drive}: {share_root}"
            )

        chosen_prefix: str | None = None
        for prefix in _common_candidate_prefixes(values):
            all_readable = True
            for path in values:
                relative = path[len(prefix) :].lstrip("\\/")
                candidate = share_root if not relative else ntpath.join(share_root, relative)
                if not is_file(candidate):
                    all_readable = False
                    break
            if all_readable:
                chosen_prefix = prefix
                break

        if chosen_prefix is None:
            if all(is_file(path) for path in values):
                continue
            raise PhotorealInventoryPathMapError(
                f"could not prove one complete SMB source-prefix mapping for {drive} from authoritative inventories"
            )

        mapping[chosen_prefix] = share_root
        proof.append(
            {
                "drive": drive[0],
                "source_prefix": chosen_prefix,
                "share": share_root,
                "verified_files": len(values),
                "candidate_files": len(values),
            }
        )

    for path in paths:
        translated = translate_stash_path(path, mapping)
        if not is_file(translated):
            raise PhotorealInventoryPathMapError(
                f"exhaustive source path is not readable after generated path mapping: {path} -> {translated}"
            )

    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not mapping:
        if negative_inventory is None:
            source_scope = DIRECT_PATH_SCOPE_PRIMARY
            source_count = len(primary_paths)
        else:
            source_scope = DIRECT_PATH_SCOPE_NEGATIVE_CALIBRATION
            source_count = len(negative_paths)
        return _direct_path_proof(
            performer_id=performer_id,
            origin=origin,
            host=host,
            source_scope=source_scope,
            source_count=source_count,
            timestamp=timestamp,
        )

    result = {
        "format": FORMAT,
        "version": VERSION,
        "stash_origin": origin,
        "stash_host": host,
        "performer_ids": [performer_id],
        "mapping": dict(sorted(mapping.items(), key=lambda item: item[0].casefold())),
        "proof": sorted(proof, key=lambda item: str(item["source_prefix"]).casefold()),
        "updated_utc": timestamp.isoformat().replace("+00:00", "Z"),
    }
    try:
        validate_cache(
            result,
            stash_url=stash_url,
            performer_ids=[performer_id],
            now=timestamp,
            is_dir=is_dir,
        )
    except StashPathCacheError as exc:
        raise PhotorealInventoryPathMapError(f"generated path map failed canonical validation: {exc}") from exc
    return result


def build_inventory_path_map_file(
    inventory_path: str | Path,
    output_path: str | Path,
    *,
    stash_url: str,
    negative_inventory_path: str | Path | None = None,
) -> dict[str, Any]:
    inventory_file = Path(inventory_path).expanduser().resolve()
    inventory = _read_json(inventory_file, label="photoreal source inventory")
    negative_inventory = None
    if negative_inventory_path is not None:
        negative_inventory = _read_json(
            Path(negative_inventory_path).expanduser().resolve(),
            label="identity negative inventory",
        )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealInventoryPathMapError(f"Photoreal path-map output already exists: {output}")

    result = build_inventory_path_map(
        inventory,
        stash_url=stash_url,
        is_file=lambda value: Path(value).is_file(),
        is_dir=lambda value: Path(value).is_dir(),
        negative_inventory=negative_inventory,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise PhotorealInventoryPathMapError(f"Photoreal path-map output already exists: {output}") from exc
    except OSError as exc:
        raise PhotorealInventoryPathMapError(f"failed to persist Photoreal path map: {output}") from exc
    return result
