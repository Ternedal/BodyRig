from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .photoreal_source_verify import (
    PhotorealSourceVerifyError,
    resolve_path_transport,
    translate_stash_path,
)

INVENTORY_FORMAT = "bodyrig-photoreal-identity-negative-inventory"
INVENTORY_VERSION = 1
LABEL_AUTHORITY = "stash-single-performer-other-id-v1"
FORMAT = "bodyrig-photoreal-identity-negative-receipt"
VERSION = 1


class PhotorealIdentityNegativeVerifyError(ValueError):
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


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealIdentityNegativeVerifyError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityNegativeVerifyError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealIdentityNegativeVerifyError(f"{label} is invalid")
    return result


def _validate_inventory(inventory: Mapping[str, Any]) -> tuple[str, list[Mapping[str, Any]]]:
    if inventory.get("format") != INVENTORY_FORMAT or inventory.get("version") != INVENTORY_VERSION:
        raise PhotorealIdentityNegativeVerifyError("identity negative inventory format/version mismatch")
    if inventory.get("label_authority") != LABEL_AUTHORITY:
        raise PhotorealIdentityNegativeVerifyError("identity negative inventory label authority mismatch")
    if inventory.get("calibration_only") is not True or inventory.get("photoreal_teacher_input") is not False:
        raise PhotorealIdentityNegativeVerifyError("identity negative inventory crossed calibration/teacher boundary")
    if inventory.get("teacher_training_authorized") is not False or inventory.get("identity_matching_authorized") is not False:
        raise PhotorealIdentityNegativeVerifyError("identity negative inventory crossed matching/training authority")
    if inventory.get("build_only") is not True or inventory.get("runtime_dependency") is not False:
        raise PhotorealIdentityNegativeVerifyError("identity negative inventory authority boundary is invalid")
    if inventory.get("production_activation") is not False:
        raise PhotorealIdentityNegativeVerifyError("identity negative inventory crossed production authority")
    target = str(inventory.get("target_performer_id") or "").strip()
    if not target:
        raise PhotorealIdentityNegativeVerifyError("identity negative inventory target performer is missing")
    values = inventory.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealIdentityNegativeVerifyError("identity negative inventory contains no sources")
    return target, values


def verify_identity_negative_sources(
    inventory: Mapping[str, Any],
    *,
    path_mapping: Mapping[str, str],
    exists_file: ExistsFile | None = None,
    file_size: FileSize | None = None,
    hash_file: HashFile | None = None,
) -> dict[str, Any]:
    target, values = _validate_inventory(inventory)
    exists = exists_file or (lambda path: path.is_file())
    size_of = file_size or (lambda path: path.stat().st_size)
    hasher = hash_file or _sha256

    verified: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    seen_paths: set[str] = set()
    total_bytes = 0
    negative_subjects: set[str] = set()
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealIdentityNegativeVerifyError("identity negative source is invalid")
        source_key = str(raw.get("source_key") or "").strip()
        catalog_path = str(raw.get("path") or "").strip()
        subject = str(raw.get("subject_performer_id") or "").strip()
        kind = str(raw.get("kind") or "").strip()
        binding = str(raw.get("source_binding") or "").strip()
        if not source_key or not catalog_path or not subject or kind not in {"video", "image"}:
            raise PhotorealIdentityNegativeVerifyError("identity negative source identity/path is invalid")
        if subject == target:
            raise PhotorealIdentityNegativeVerifyError("target performer cannot be verified as a negative subject")
        if raw.get("target_performer_id") != target or raw.get("target_performer_absent") is not True:
            raise PhotorealIdentityNegativeVerifyError("identity negative source lacks target-absence authority")
        if raw.get("label_authority") != LABEL_AUTHORITY:
            raise PhotorealIdentityNegativeVerifyError("identity negative source label authority mismatch")
        if binding not in {"scene-single-performer", "direct-performer"}:
            raise PhotorealIdentityNegativeVerifyError("identity negative source binding is not single-performer authoritative")
        if source_key in seen_keys:
            raise PhotorealIdentityNegativeVerifyError(f"identity negative source key is duplicated: {source_key}")
        seen_keys.add(source_key)

        translated = translate_stash_path(catalog_path, path_mapping)
        local = Path(translated)
        normalized_path = os.path.normcase(str(local))
        if normalized_path in seen_paths:
            raise PhotorealIdentityNegativeVerifyError("multiple negative sources resolve to the same local file")
        seen_paths.add(normalized_path)
        if not exists(local):
            raise PhotorealIdentityNegativeVerifyError(
                f"identity negative source is not readable after path mapping: {catalog_path} -> {translated}"
            )
        observed_size = int(size_of(local))
        if observed_size < 1:
            raise PhotorealIdentityNegativeVerifyError(f"identity negative source is empty: {translated}")
        expected_size = int(raw.get("size_bytes") or 0)
        if expected_size > 0 and expected_size != observed_size:
            raise PhotorealIdentityNegativeVerifyError(
                f"identity negative source size changed: {catalog_path} expected={expected_size} observed={observed_size}"
            )
        digest = _sha(hasher(local), label="identity negative source SHA-256")
        total_bytes += observed_size
        negative_subjects.add(subject)
        record: dict[str, Any] = {
            "source_key": source_key,
            "subject_performer_id": subject,
            "subject_performer_name": str(raw.get("subject_performer_name") or ""),
            "target_performer_id": target,
            "target_performer_absent": True,
            "label_authority": LABEL_AUTHORITY,
            "kind": kind,
            "source_binding": binding,
            "catalog_path": catalog_path,
            "resolved_path": str(local),
            "size_bytes": observed_size,
            "sha256": digest,
            "width": int(raw.get("width") or 0),
            "height": int(raw.get("height") or 0),
        }
        if kind == "video":
            record.update(
                {
                    "projection": str(raw.get("projection") or "unknown"),
                    "stereo_layout": str(raw.get("stereo_layout") or "unknown"),
                    "duration_seconds": float(raw.get("duration_seconds") or 0.0),
                    "frame_rate": float(raw.get("frame_rate") or 0.0),
                }
            )
        else:
            record["megapixels"] = float(raw.get("megapixels") or 0.0)
        verified.append(record)

    verified.sort(key=lambda item: (item["subject_performer_id"], item["kind"], item["source_key"]))
    return {
        "format": FORMAT,
        "version": VERSION,
        "target_performer_id": target,
        "label_authority": LABEL_AUTHORITY,
        "negative_performer_count": len(negative_subjects),
        "source_count": len(verified),
        "total_bytes": total_bytes,
        "sources": verified,
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "calibration_only": True,
        "photoreal_teacher_input": False,
        "teacher_training_authorized": False,
        "identity_matching_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def verify_identity_negative_inventory_file(
    inventory_path: str | Path,
    path_map_path: str | Path,
    output_path: str | Path,
    *,
    stash_url: str,
) -> dict[str, Any]:
    inventory_file = Path(inventory_path).expanduser().resolve()
    path_map_file = Path(path_map_path).expanduser().resolve()
    inventory = _read_json(inventory_file, label="identity negative inventory")
    path_map = _read_json(path_map_file, label="Stash path transport proof")
    target, _ = _validate_inventory(inventory)
    try:
        validated = resolve_path_transport(path_map, stash_url=stash_url, performer_id=target)
    except PhotorealSourceVerifyError as exc:
        raise PhotorealIdentityNegativeVerifyError(
            f"Stash path transport is not valid for negative calibration: {exc}"
        ) from exc
    result = verify_identity_negative_sources(inventory, path_mapping=validated["mapping"])
    result["path_map_mode"] = validated["cache_mode"]
    result["stash_origin"] = validated["stash_origin"]

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityNegativeVerifyError(f"identity negative receipt already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
