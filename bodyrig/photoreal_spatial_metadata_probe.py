from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, BinaryIO, Mapping

FORMAT = "bodyrig-photoreal-spatial-container-probe"
VERSION = 1
VISUAL_HEADER = 78
VISUAL_TYPES = {"avc1", "avc2", "avc3", "avc4", "hvc1", "hev1", "mp4v", "av01", "vp08", "vp09", "s263", "encv", "apcn", "apch", "apcs", "apco"}
PROJECTION_TYPES = {"equi", "cbmp", "mshp"}
STEREO_MODES = {0: "mono", 1: "top-bottom", 2: "left-right", 3: "stereo-custom", 4: "right-left"}
LEGACY_SPHERICAL_V1_UUID = bytes.fromhex("ffcc8263f8554a938814587a02521fdd")
LEGACY_SPHERICAL_V1_NAMESPACE = "http://ns.google.com/videos/1.0/spherical/"
LEGACY_STEREO_MODES = {"mono", "left-right", "top-bottom"}
MAX_LEGACY_XML_BYTES = 1024 * 1024


class PhotorealSpatialMetadataProbeError(ValueError):
    pass


def _read_json(path: str | Path, label: str) -> tuple[dict[str, Any], bytes]:
    source = Path(path).expanduser().resolve()
    try:
        raw = source.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealSpatialMetadataProbeError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealSpatialMetadataProbeError(f"{label} must be a JSON object")
    return value, raw


def _sha(value: Any, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealSpatialMetadataProbeError(f"{label} is invalid")
    return result


def _text(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result or len(result) > 4096:
        raise PhotorealSpatialMetadataProbeError(f"{label} is invalid")
    return result


def _read(stream: BinaryIO, offset: int, count: int) -> bytes:
    stream.seek(offset)
    raw = stream.read(count)
    if len(raw) != count:
        raise PhotorealSpatialMetadataProbeError("ISO BMFF box is truncated")
    return raw


def _header(stream: BinaryIO, offset: int, end: int) -> tuple[str, int, int, int]:
    if end - offset < 8:
        raise PhotorealSpatialMetadataProbeError("ISO BMFF partial box header")
    raw = _read(stream, offset, 8)
    size = int.from_bytes(raw[:4], "big")
    box_type = raw[4:8].decode("latin-1")
    header = 8
    if size == 1:
        if end - offset < 16:
            raise PhotorealSpatialMetadataProbeError("ISO BMFF extended box header is truncated")
        size = int.from_bytes(_read(stream, offset + 8, 8), "big")
        header = 16
    elif size == 0:
        size = end - offset
    if size < header or offset + size > end:
        raise PhotorealSpatialMetadataProbeError(f"ISO BMFF box {box_type!r} has invalid bounds")
    return box_type, offset + header, offset + size, size


def _boxes(stream: BinaryIO, start: int, end: int):
    offset = start
    count = 0
    while offset < end:
        if end - offset < 8:
            if _read(stream, offset, end - offset) == b"\x00" * (end - offset):
                break
            raise PhotorealSpatialMetadataProbeError("ISO BMFF container has trailing bytes")
        box_type, payload, box_end, _ = _header(stream, offset, end)
        yield box_type, payload, box_end
        offset = box_end
        count += 1
        if count > 100_000:
            raise PhotorealSpatialMetadataProbeError("ISO BMFF box safety bound exceeded")


def _fullbox(stream: BinaryIO, payload: int, end: int) -> tuple[int, int]:
    if end - payload < 4:
        raise PhotorealSpatialMetadataProbeError("ISO BMFF FullBox header is truncated")
    raw = _read(stream, payload, 4)
    return raw[0], int.from_bytes(raw[1:4], "big")


def _parse_st3d(stream: BinaryIO, payload: int, end: int, result: dict[str, Any]) -> None:
    version, flags = _fullbox(stream, payload, end)
    if end - payload < 5:
        raise PhotorealSpatialMetadataProbeError("st3d box is truncated")
    mode = _read(stream, payload + 4, 1)[0]
    result.update(
        st3d_present=True,
        st3d_version=version,
        st3d_flags=flags,
        stereo_mode_code=mode,
        stereo_mode=STEREO_MODES.get(mode, "reserved-or-unknown"),
    )


def _parse_sv3d(stream: BinaryIO, start: int, end: int, result: dict[str, Any]) -> None:
    result["sv3d_present"] = True
    projection_types: list[str] = []
    for box_type, payload, box_end in _boxes(stream, start, end):
        if box_type == "svhd":
            result["svhd_present"] = True
            _fullbox(stream, payload, box_end)
            raw = _read(stream, payload + 4, min(512, max(0, box_end - payload - 4))) if box_end > payload + 4 else b""
            source = raw.split(b"\x00", 1)[0]
            result["svhd_metadata_source_present"] = bool(source)
            result["svhd_metadata_source_sha256"] = hashlib.sha256(source).hexdigest() if source else None
        elif box_type == "proj":
            result["proj_present"] = True
            for child_type, child_payload, child_end in _boxes(stream, payload, box_end):
                if child_type == "prhd":
                    result["prhd_present"] = True
                elif child_type in PROJECTION_TYPES:
                    projection_types.append(child_type)
                    if child_type == "mshp":
                        _fullbox(stream, child_payload, child_end)
                        if child_end - child_payload >= 12:
                            result["mesh_projection_encoding"] = _read(stream, child_payload + 8, 4).decode("latin-1")
    result["projection_type"] = projection_types[0] if len(projection_types) == 1 else "multiple" if projection_types else None


def _legacy_bool(value: str | None) -> bool | None:
    normalized = str(value or "").strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _parse_legacy_v1_uuid(stream: BinaryIO, payload: int, end: int, result: dict[str, Any]) -> None:
    if end - payload < 16:
        return
    if _read(stream, payload, 16) != LEGACY_SPHERICAL_V1_UUID:
        return
    result["spherical_v1_present"] = True
    xml_size = end - payload - 16
    result["spherical_v1_xml_size_bytes"] = xml_size
    if xml_size < 1:
        result["spherical_v1_parse_status"] = "empty"
        return
    if xml_size > MAX_LEGACY_XML_BYTES:
        result["spherical_v1_parse_status"] = "too-large"
        return
    raw = _read(stream, payload + 16, xml_size).rstrip(b"\x00")
    result["spherical_v1_xml_sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        root = ET.fromstring(raw.decode("utf-8-sig"))
    except (UnicodeError, ET.ParseError):
        result["spherical_v1_parse_status"] = "invalid-xml"
        return

    namespace = f"{{{LEGACY_SPHERICAL_V1_NAMESPACE}}}"
    fields: dict[str, str] = {}
    for element in root.iter():
        if not isinstance(element.tag, str) or not element.tag.startswith(namespace):
            continue
        local_name = element.tag[len(namespace) :]
        if local_name not in {"Spherical", "Stitched", "ProjectionType", "StereoMode"}:
            continue
        value = str(element.text or "").strip()
        if value and len(value) <= 128:
            fields[local_name] = value

    projection = fields.get("ProjectionType", "").strip().lower()
    stereo = fields.get("StereoMode", "mono").strip().lower()
    result["spherical_v1_xml_valid"] = True
    result["spherical_v1_spherical"] = _legacy_bool(fields.get("Spherical"))
    result["spherical_v1_stitched"] = _legacy_bool(fields.get("Stitched"))
    result["spherical_v1_projection_type"] = projection if projection else None
    result["spherical_v1_stereo_mode"] = stereo if stereo in LEGACY_STEREO_MODES else "unsupported-or-unknown"
    result["spherical_v1_parse_status"] = (
        "valid-v1-equirectangular"
        if result["spherical_v1_spherical"] is True
        and result["spherical_v1_stitched"] is True
        and projection == "equirectangular"
        and stereo in LEGACY_STEREO_MODES
        else "xml-valid-but-nonconforming-v1"
    )


def _parse_stsd(stream: BinaryIO, payload: int, end: int, result: dict[str, Any]) -> None:
    if end - payload < 8:
        raise PhotorealSpatialMetadataProbeError("stsd box is truncated")
    entry_count = int.from_bytes(_read(stream, payload + 4, 4), "big")
    entries = list(_boxes(stream, payload + 8, end))
    if entry_count != len(entries) or entry_count > 4096:
        raise PhotorealSpatialMetadataProbeError("stsd entry count is invalid")
    for entry_type, entry_payload, entry_end in entries:
        result["sample_entry_types"].add(entry_type)
        if entry_type == "camm":
            result["camm_sample_entry_present"] = True
        if entry_type not in VISUAL_TYPES:
            continue
        children = entry_payload + VISUAL_HEADER
        if children > entry_end:
            raise PhotorealSpatialMetadataProbeError(f"visual sample entry {entry_type!r} is truncated")
        for child_type, child_payload, child_end in _boxes(stream, children, entry_end):
            if child_type == "st3d":
                _parse_st3d(stream, child_payload, child_end, result)
            elif child_type == "sv3d":
                _parse_sv3d(stream, child_payload, child_end, result)


def _walk(stream: BinaryIO, start: int, end: int, result: dict[str, Any]) -> None:
    for box_type, payload, box_end in _boxes(stream, start, end):
        if box_type == "moov":
            result["moov_present"] = True
        if box_type == "stsd":
            _parse_stsd(stream, payload, box_end, result)
        elif box_type == "uuid":
            _parse_legacy_v1_uuid(stream, payload, box_end, result)
        elif box_type in {"moov", "trak", "mdia", "minf", "stbl"}:
            _walk(stream, payload, box_end, result)


def probe_isobmff_file(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    result: dict[str, Any] = {
        "probe_status": "unsupported-container",
        "moov_present": False,
        "sample_entry_types": set(),
        "st3d_present": False,
        "st3d_version": None,
        "st3d_flags": None,
        "stereo_mode_code": None,
        "stereo_mode": None,
        "sv3d_present": False,
        "svhd_present": False,
        "svhd_metadata_source_present": False,
        "svhd_metadata_source_sha256": None,
        "proj_present": False,
        "prhd_present": False,
        "projection_type": None,
        "mesh_projection_encoding": None,
        "camm_sample_entry_present": False,
        "spherical_v1_present": False,
        "spherical_v1_xml_size_bytes": None,
        "spherical_v1_xml_sha256": None,
        "spherical_v1_xml_valid": False,
        "spherical_v1_spherical": None,
        "spherical_v1_stitched": None,
        "spherical_v1_projection_type": None,
        "spherical_v1_stereo_mode": None,
        "spherical_v1_parse_status": None,
        "probe_error": None,
    }
    try:
        size = source.stat().st_size
        if size >= 8:
            with source.open("rb") as stream:
                first_type, _, _, _ = _header(stream, 0, size)
                if first_type in {"ftyp", "moov", "free", "wide", "mdat", "skip", "uuid"}:
                    result["probe_status"] = "parsed-isobmff"
                    _walk(stream, 0, size, result)
                    if result["moov_present"] is not True:
                        raise PhotorealSpatialMetadataProbeError("ISO BMFF file has no moov box")
    except OSError as exc:
        result["probe_status"] = "invalid-or-unreadable-isobmff"
        result["probe_error"] = f"os-error:{type(exc).__name__}"
    except PhotorealSpatialMetadataProbeError as exc:
        result["probe_status"] = "invalid-or-unreadable-isobmff"
        result["probe_error"] = str(exc)[:512]
    result["sample_entry_types"] = sorted(result["sample_entry_types"])
    if result["probe_status"] != "parsed-isobmff":
        status = result["probe_status"]
    elif result["sv3d_present"]:
        status = f"spherical-v2-{result['projection_type']}" if result["projection_type"] in PROJECTION_TYPES else "spherical-v2-incomplete"
    elif result["spherical_v1_present"]:
        status = (
            "spherical-v1-equirectangular-diagnostic"
            if result["spherical_v1_parse_status"] == "valid-v1-equirectangular"
            else "spherical-v1-incomplete-or-nonconforming"
        )
    elif result["st3d_present"]:
        status = "stereo-only-no-spherical-v2"
    else:
        status = "no-spherical-metadata"
    result["projection_metadata_status"] = status
    result["metadata_precedence"] = "v2" if result["sv3d_present"] else "v1" if result["spherical_v1_present"] else None
    return result


def _inventory_keys(inventory: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    if inventory.get("format") != "bodyrig-photoreal-source-inventory" or inventory.get("version") != 1:
        raise PhotorealSpatialMetadataProbeError("photoreal source inventory format/version mismatch")
    if inventory.get("build_only") is not True or inventory.get("photoreal_teacher_input") is not True or inventory.get("production_activation") is not False:
        raise PhotorealSpatialMetadataProbeError("photoreal source inventory authority boundary is invalid")
    videos: dict[str, Mapping[str, Any]] = {}
    keys: set[str] = set()
    for kind, values, id_field, prefix in (
        ("video", inventory.get("videos"), "scene_id", "scene"),
        ("image", inventory.get("images"), "image_id", "image"),
    ):
        if not isinstance(values, list):
            raise PhotorealSpatialMetadataProbeError(f"photoreal {kind} inventory is invalid")
        for raw in values:
            if not isinstance(raw, Mapping):
                raise PhotorealSpatialMetadataProbeError(f"photoreal {kind} inventory entry is invalid")
            source_id = _text(raw.get(id_field), f"inventory {kind} id")
            source_path = _text(raw.get("path"), f"inventory {kind} path")
            key = f"{prefix}:{source_id}:{source_path}"
            if key in keys:
                raise PhotorealSpatialMetadataProbeError("photoreal inventory repeats source key")
            keys.add(key)
            if kind == "video":
                videos[key] = raw
    return videos, keys


def build_spatial_container_probe(
    inventory: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    receipt_sha256: str,
) -> dict[str, Any]:
    videos, inventory_keys = _inventory_keys(inventory)
    performer_id = _text(inventory.get("performer_id"), "inventory performer id")
    if receipt.get("format") != "bodyrig-photoreal-source-receipt" or receipt.get("version") != 1:
        raise PhotorealSpatialMetadataProbeError("photoreal source receipt format/version mismatch")
    if (
        receipt.get("all_sources_readable") is not True
        or receipt.get("all_sources_sha256_bound") is not True
        or receipt.get("build_only") is not True
        or receipt.get("production_activation") is not False
    ):
        raise PhotorealSpatialMetadataProbeError("photoreal source receipt authority boundary is invalid")
    if _text(receipt.get("performer_id"), "receipt performer id") != performer_id:
        raise PhotorealSpatialMetadataProbeError("photoreal inventory/receipt performer mismatch")
    values = receipt.get("sources")
    if not isinstance(values, list):
        raise PhotorealSpatialMetadataProbeError("photoreal source receipt sources are invalid")
    receipt_by_key = {
        _text(raw.get("source_key"), "receipt source key"): raw
        for raw in values
        if isinstance(raw, Mapping)
    }
    if len(receipt_by_key) != len(values) or set(receipt_by_key) != inventory_keys:
        raise PhotorealSpatialMetadataProbeError("photoreal inventory/source receipt disagree on exact source universe")

    sources: list[dict[str, Any]] = []
    for source_key, inventory_video in sorted(videos.items()):
        receipt_source = receipt_by_key[source_key]
        if receipt_source.get("kind") != "video":
            raise PhotorealSpatialMetadataProbeError("photoreal source receipt video kind mismatch")
        source_id = _text(receipt_source.get("source_id"), "receipt video source id")
        if source_id != _text(inventory_video.get("scene_id"), "inventory scene id"):
            raise PhotorealSpatialMetadataProbeError("photoreal inventory/receipt video source id mismatch")
        resolved_path = _text(receipt_source.get("resolved_path"), "receipt resolved video path")
        source_sha = _sha(receipt_source.get("sha256"), "receipt video SHA-256")
        raw_size = receipt_source.get("size_bytes")
        if isinstance(raw_size, bool):
            raise PhotorealSpatialMetadataProbeError("receipt video size is invalid")
        try:
            receipt_size = int(raw_size)
        except (TypeError, ValueError) as exc:
            raise PhotorealSpatialMetadataProbeError("receipt video size is invalid") from exc
        if receipt_size < 1:
            raise PhotorealSpatialMetadataProbeError("receipt video size is invalid")
        path = Path(resolved_path)
        probe = probe_isobmff_file(path)
        try:
            size_matches = path.stat().st_size == receipt_size
        except OSError:
            size_matches = False
        sources.append(
            {
                "source_id": source_id,
                "source_key_sha256": hashlib.sha256(source_key.encode("utf-8")).hexdigest(),
                "source_sha256": source_sha,
                "source_size_bytes": receipt_size,
                "source_size_matches_receipt": size_matches,
                "container_extension": path.suffix.lower(),
                "inventory_projection": str(inventory_video.get("projection") or "unknown"),
                "inventory_stereo_layout": str(inventory_video.get("stereo_layout") or "unknown"),
                **probe,
                "diagnostic_only": True,
                "deprojection_authority": False,
                "production_activation": False,
            }
        )
    parsed = [item for item in sources if item["probe_status"] == "parsed-isobmff"]
    return {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "source_receipt_sha256": _sha(receipt_sha256, "source receipt SHA-256"),
        "video_source_count": len(sources),
        "parsed_isobmff_count": len(parsed),
        "spherical_v2_source_count": sum(1 for item in parsed if item["sv3d_present"]),
        "spherical_v1_source_count": sum(1 for item in parsed if item["spherical_v1_present"]),
        "dual_v1_v2_source_count": sum(1 for item in parsed if item["sv3d_present"] and item["spherical_v1_present"]),
        "mesh_projection_source_count": sum(1 for item in parsed if item["projection_type"] == "mshp"),
        "camm_source_count": sum(1 for item in parsed if item["camm_sample_entry_present"]),
        "size_mismatch_count": sum(1 for item in sources if not item["source_size_matches_receipt"]),
        "sources": sources,
        "diagnostic_only": True,
        "deprojection_authority": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def build_spatial_container_probe_files(
    inventory_path: str | Path,
    receipt_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    inventory, _ = _read_json(inventory_path, "photoreal source inventory")
    receipt, receipt_raw = _read_json(receipt_path, "photoreal source receipt")
    result = build_spatial_container_probe(
        inventory,
        receipt,
        receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealSpatialMetadataProbeError(f"spatial container probe output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
