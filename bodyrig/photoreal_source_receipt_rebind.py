from __future__ import annotations

import hashlib
import json
import ntpath
from pathlib import Path
from typing import Any, Callable, Mapping

from .photoreal_source_verify import (
    FORMAT,
    VERSION,
    PhotorealSourceVerifyError,
    _records,
    _sha256_bytes,
    _validate_inventory_header,
    resolve_path_transport,
    translate_stash_path,
)

PROOF_FORMAT = "bodyrig-photoreal-source-receipt-rebind-proof"
PROOF_VERSION = 1

ExistsFile = Callable[[Path], bool]
FileSize = Callable[[Path], int]


class PhotorealSourceReceiptRebindError(PhotorealSourceVerifyError):
    pass


def _read_object(path: Path, *, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealSourceReceiptRebindError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PhotorealSourceReceiptRebindError(f"{label} must be a JSON object")
    return raw, value


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise PhotorealSourceReceiptRebindError(f"{label} is invalid")
    return text


def _windows_path_key(value: str) -> str:
    return ntpath.normcase(ntpath.normpath(str(value or "").strip().replace("/", "\\")))


def _receipt_sources(receipt: Mapping[str, Any], records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise PhotorealSourceReceiptRebindError("verified source receipt format/version mismatch")
    if receipt.get("all_sources_readable") is not True or receipt.get("all_sources_sha256_bound") is not True:
        raise PhotorealSourceReceiptRebindError("verified source receipt is incomplete")
    if receipt.get("source_keys_path_specific") is not True or receipt.get("teacher_input_authority") is not True:
        raise PhotorealSourceReceiptRebindError("verified source receipt authority boundary is invalid")
    if receipt.get("build_only") is not True or receipt.get("runtime_dependency") is not False:
        raise PhotorealSourceReceiptRebindError("verified source receipt build/runtime boundary is invalid")
    if receipt.get("production_activation") is not False:
        raise PhotorealSourceReceiptRebindError("verified source receipt crossed production authority")

    values = receipt.get("sources")
    if not isinstance(values, list) or len(values) != len(records):
        raise PhotorealSourceReceiptRebindError("verified source receipt source count mismatch")
    expected = {record["source_key"].casefold(): record for record in records}
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealSourceReceiptRebindError("verified source receipt contains a non-object source")
        key = str(raw.get("source_key") or "").strip()
        record = expected.get(key.casefold())
        if record is None:
            raise PhotorealSourceReceiptRebindError(f"verified source receipt contains unknown source: {key}")
        if key.casefold() in result:
            raise PhotorealSourceReceiptRebindError(f"verified source receipt repeats source: {key}")
        if (
            raw.get("kind") != record["kind"]
            or str(raw.get("source_id") or "").strip() != record["source_id"]
            or str(raw.get("catalog_path") or "").strip() != record["catalog_path"]
            or int(raw.get("size_bytes") or -1) != int(record["expected_size_bytes"])
        ):
            raise PhotorealSourceReceiptRebindError(f"verified source receipt record mismatch: {key}")
        resolved_path = str(raw.get("resolved_path") or "").strip()
        if not resolved_path:
            raise PhotorealSourceReceiptRebindError(f"verified source receipt lacks resolved path: {key}")
        digest = _sha(raw.get("sha256"), label=f"verified source SHA-256 for {key}")
        result[key.casefold()] = {
            "kind": record["kind"],
            "source_id": record["source_id"],
            "source_key": key,
            "catalog_path": record["catalog_path"],
            "resolved_path": resolved_path,
            "size_bytes": int(record["expected_size_bytes"]),
            "sha256": digest,
        }
    if set(result) != set(expected):
        raise PhotorealSourceReceiptRebindError("verified source receipt source universe mismatch")
    return result


def rebind_verified_source_receipt(
    *,
    prior_inventory: Mapping[str, Any],
    prior_inventory_raw: bytes,
    prior_receipt: Mapping[str, Any],
    prior_receipt_raw: bytes,
    new_inventory: Mapping[str, Any],
    new_inventory_raw: bytes,
    new_path_map: Mapping[str, Any],
    stash_url: str,
    exists_file: ExistsFile | None = None,
    file_size: FileSize | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prior_performer, _ = _validate_inventory_header(prior_inventory)
    new_performer, new_performer_name = _validate_inventory_header(new_inventory)
    if prior_performer != new_performer:
        raise PhotorealSourceReceiptRebindError("prior/new inventory performer mismatch")
    if str(prior_receipt.get("performer_id") or "").strip() != prior_performer:
        raise PhotorealSourceReceiptRebindError("verified source receipt performer mismatch")

    prior_inventory_sha = _sha256_bytes(prior_inventory_raw)
    if _sha(prior_receipt.get("inventory_sha256"), label="verified receipt inventory SHA-256") != prior_inventory_sha:
        raise PhotorealSourceReceiptRebindError("verified source receipt is not bound to the supplied prior inventory")

    prior_records = _records(prior_inventory)
    new_records = _records(new_inventory)
    prior_by_key = {record["source_key"].casefold(): record for record in prior_records}
    new_by_key = {record["source_key"].casefold(): record for record in new_records}
    if set(prior_by_key) != set(new_by_key):
        raise PhotorealSourceReceiptRebindError("new inventory changes the verified source universe")

    for key in sorted(prior_by_key):
        left = prior_by_key[key]
        right = new_by_key[key]
        for field in ("kind", "source_id", "source_key", "catalog_path", "expected_size_bytes"):
            if left[field] != right[field]:
                raise PhotorealSourceReceiptRebindError(
                    f"new inventory changes byte-relevant source field {field}: {left['source_key']}"
                )

    verified = _receipt_sources(prior_receipt, prior_records)
    validated_transport = resolve_path_transport(
        new_path_map,
        stash_url=stash_url,
        performer_id=new_performer,
        expected_direct_scope="primary",
        expected_direct_source_count=len(new_records),
    )
    exists = exists_file or (lambda path: path.is_file())
    size_of = file_size or (lambda path: path.stat().st_size)

    rebound_sources: list[dict[str, Any]] = []
    total_bytes = 0
    for record in new_records:
        prior = verified[record["source_key"].casefold()]
        translated = translate_stash_path(record["catalog_path"], validated_transport["mapping"])
        if _windows_path_key(translated) != _windows_path_key(prior["resolved_path"]):
            raise PhotorealSourceReceiptRebindError(
                f"new path transport resolves source differently: {record['source_key']}"
            )
        local = Path(translated)
        if not exists(local):
            raise PhotorealSourceReceiptRebindError(
                f"rebind source is not currently readable: {record['catalog_path']}"
            )
        observed_size = int(size_of(local))
        if observed_size != int(prior["size_bytes"]):
            raise PhotorealSourceReceiptRebindError(
                f"rebind source size changed since verified receipt: {record['source_key']}"
            )
        total_bytes += observed_size
        rebound_sources.append(
            {
                "kind": record["kind"],
                "source_id": record["source_id"],
                "source_key": record["source_key"],
                "catalog_path": record["catalog_path"],
                "resolved_path": translated,
                "size_bytes": observed_size,
                "sha256": prior["sha256"],
            }
        )

    rebound_sources.sort(key=lambda item: (item["kind"], item["source_key"].casefold()))
    new_inventory_sha = _sha256_bytes(new_inventory_raw)
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": new_performer,
        "performer_name": new_performer_name,
        "source_count": len(rebound_sources),
        "video_count": sum(1 for item in rebound_sources if item["kind"] == "video"),
        "image_count": sum(1 for item in rebound_sources if item["kind"] == "image"),
        "total_bytes": total_bytes,
        "sources": rebound_sources,
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "teacher_input_authority": True,
        "runtime_dependency": False,
        "production_activation": False,
        "inventory_sha256": new_inventory_sha,
        "path_map_mode": validated_transport["cache_mode"],
        "stash_origin": validated_transport["stash_origin"],
    }
    proof = {
        "format": PROOF_FORMAT,
        "version": PROOF_VERSION,
        "performer_id": new_performer,
        "prior_inventory_sha256": prior_inventory_sha,
        "prior_receipt_sha256": hashlib.sha256(prior_receipt_raw).hexdigest(),
        "new_inventory_sha256": new_inventory_sha,
        "source_count": len(rebound_sources),
        "all_source_records_exactly_preserved": True,
        "all_current_sizes_match_verified_receipt": True,
        "source_rehash_skipped_explicitly": True,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    return receipt, proof


def rebind_verified_source_receipt_files(
    *,
    prior_inventory_path: str | Path,
    prior_receipt_path: str | Path,
    new_inventory_path: str | Path,
    new_path_map_path: str | Path,
    output_path: str | Path,
    proof_output_path: str | Path,
    stash_url: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prior_inventory_file = Path(prior_inventory_path).expanduser().resolve()
    prior_receipt_file = Path(prior_receipt_path).expanduser().resolve()
    new_inventory_file = Path(new_inventory_path).expanduser().resolve()
    new_path_map_file = Path(new_path_map_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    proof_output = Path(proof_output_path).expanduser().resolve()
    if output.exists() or proof_output.exists():
        raise PhotorealSourceReceiptRebindError("rebind output already exists")

    prior_inventory_raw, prior_inventory = _read_object(prior_inventory_file, label="prior source inventory")
    prior_receipt_raw, prior_receipt = _read_object(prior_receipt_file, label="prior source receipt")
    new_inventory_raw, new_inventory = _read_object(new_inventory_file, label="new source inventory")
    _, new_path_map = _read_object(new_path_map_file, label="new source path map")

    receipt, proof = rebind_verified_source_receipt(
        prior_inventory=prior_inventory,
        prior_inventory_raw=prior_inventory_raw,
        prior_receipt=prior_receipt,
        prior_receipt_raw=prior_receipt_raw,
        new_inventory=new_inventory,
        new_inventory_raw=new_inventory_raw,
        new_path_map=new_path_map,
        stash_url=stash_url,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    proof_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    proof_output.write_text(json.dumps(proof, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return receipt, proof
