from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .avatar import AvatarError, validate_vrm1

FORMAT = "modelrig-body"
FORMAT_VERSION = 1
MAX_ENTRIES = 12
MAX_TOTAL_UNCOMPRESSED = 256 * 1024 * 1024
MAX_JSON = 512 * 1024
MAX_THUMBNAIL = 8 * 1024 * 1024
MAX_AVATAR = 192 * 1024 * 1024
MAX_MOTION = 32 * 1024 * 1024
REQUIRED = {"manifest.json", "checksums.json", "avatar.vrm", "bodyprint.json", "provenance.json", "thumbnail.png"}
OPTIONAL = {"motions/idle.vrma", "motions/walk.vrma", "motions/talk.vrma", "motions/gesture_01.vrma", "motions/gesture_02.vrma", "motions/gesture_03.vrma"}
ALLOWED = REQUIRED | OPTIONAL
SLUG_RE = re.compile(r"^[a-z0-9æøå_-]{1,160}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class MRBodyError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedBody:
    manifest: dict[str, Any]
    bodyprint: dict[str, Any]
    provenance: dict[str, Any]
    payload_names: tuple[str, ...]


def _loads_json(data: bytes, name: str) -> Any:
    if len(data) > MAX_JSON:
        raise MRBodyError(f"{name}: JSON payload exceeds limit")
    try:
        return json.loads(data.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise MRBodyError(f"{name}: invalid canonical JSON") from exc


def _num(value: Any, lo: float, hi: float, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not lo <= float(value) <= hi:
        raise MRBodyError(f"bodyprint.{field}: invalid number")


def validate_bodyprint(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("format") != "modelrig-bodyprint" or value.get("version") != 1:
        raise MRBodyError("bodyprint.json: unsupported format/version")
    allowed_top = {"format", "version", "shape", "motion", "expression", "runtime"}
    if set(value) - allowed_top:
        raise MRBodyError("bodyprint.json: unknown fields")
    rules = {
        "shape": {"height_scale": (1e-6, 4.0), "shoulder_to_height": (0.0, 1.0), "hip_to_height": (0.0, 1.0), "arm_to_height": (0.0, 1.0), "leg_to_height": (0.0, 1.0)},
        "motion": {"energy": (0.0, 1.0), "gesture_frequency": (0.0, 1.0), "gesture_amplitude": (0.0, 1.0), "head_motion": (0.0, 1.0), "turn_speed": (0.0, 1.0), "walk_cadence_spm": (0.0, 300.0)},
        "expression": {"blink_rate_per_min": (0.0, 120.0), "gaze_strength": (0.0, 1.0), "head_tilt": (0.0, 1.0), "speech_motion": (0.0, 1.0)},
        "runtime": {"idle_strength": (0.0, 1.0), "gaze_smoothing": (0.0, 1.0), "gesture_intensity": (0.0, 1.0), "breathing_strength": (0.0, 1.0)},
    }
    observed = 0
    for section, section_rules in rules.items():
        if section not in value:
            continue
        obj = value[section]
        if not isinstance(obj, dict) or not obj or set(obj) - set(section_rules):
            raise MRBodyError(f"bodyprint.{section}: invalid object")
        for key, item in obj.items():
            lo, hi = section_rules[key]
            _num(item, lo, hi, f"{section}.{key}")
            observed += 1
    if observed == 0:
        raise MRBodyError("bodyprint.json: no observed fields")
    return value


def validate_manifest(value: Any) -> dict[str, Any]:
    required = {"format", "format_version", "id", "name", "avatar", "bodyprint", "provenance", "thumbnail", "builder"}
    if not isinstance(value, dict) or set(value) != required:
        raise MRBodyError("manifest.json: fields must match v1 exactly")
    if value["format"] != FORMAT or value["format_version"] != FORMAT_VERSION:
        raise MRBodyError("manifest.json: unsupported format/version")
    if not isinstance(value["id"], str) or not SLUG_RE.fullmatch(value["id"]):
        raise MRBodyError("manifest.json: invalid id")
    if not isinstance(value["name"], str) or not 1 <= len(value["name"]) <= 160:
        raise MRBodyError("manifest.json: invalid name")
    if value["avatar"] != {"format": "vrm", "version": "1.0", "path": "avatar.vrm"}:
        raise MRBodyError("manifest.json: invalid avatar descriptor")
    if value["bodyprint"] != "bodyprint.json" or value["provenance"] != "provenance.json" or value["thumbnail"] != "thumbnail.png":
        raise MRBodyError("manifest.json: invalid payload path")
    builder = value["builder"]
    if not isinstance(builder, dict) or set(builder) - {"name", "version", "revision"} or not {"name", "version"} <= set(builder):
        raise MRBodyError("manifest.json: invalid builder")
    if builder["name"] != "bodyrig" or not isinstance(builder["version"], str) or not 1 <= len(builder["version"]) <= 64:
        raise MRBodyError("manifest.json: invalid builder identity")
    revision = builder.get("revision")
    if revision is not None and (not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)):
        raise MRBodyError("manifest.json: invalid builder revision")
    return value


def validate_provenance(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"format", "version", "created_at", "source", "synthetic_avatar", "pipeline"}:
        raise MRBodyError("provenance.json: fields must match v1 exactly")
    if value["format"] != "modelrig-body-provenance" or value["version"] != 1 or value["synthetic_avatar"] is not True:
        raise MRBodyError("provenance.json: invalid format")
    if not isinstance(value["created_at"], str) or not value["created_at"]:
        raise MRBodyError("provenance.json: invalid created_at")
    source = value["source"]
    if not isinstance(source, dict) or set(source) != {"kind", "count"} or source["kind"] != "user-supplied-local-media":
        raise MRBodyError("provenance.json: invalid source")
    count = source["count"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise MRBodyError("provenance.json: invalid source count")
    pipeline = value["pipeline"]
    if not isinstance(pipeline, list) or not 1 <= len(pipeline) <= 32:
        raise MRBodyError("provenance.json: invalid pipeline")
    for item in pipeline:
        if not isinstance(item, dict) or set(item) != {"stage", "adapter", "revision"} or not all(isinstance(item[k], str) and item[k] for k in item):
            raise MRBodyError("provenance.json: invalid pipeline stage")
    return value


def _validate_glb(data: bytes, name: str) -> None:
    if len(data) < 12 or data[:4] != b"glTF" or int.from_bytes(data[4:8], "little") != 2 or int.from_bytes(data[8:12], "little") != len(data):
        raise MRBodyError(f"{name}: invalid glTF/GLB v2 container")


def _validate_vrm(data: bytes) -> None:
    try:
        validate_vrm1(data)
    except AvatarError as exc:
        raise MRBodyError(str(exc)) from exc


def _entry_limit(name: str) -> int:
    if name in {"manifest.json", "checksums.json", "bodyprint.json", "provenance.json"}:
        return MAX_JSON
    if name == "thumbnail.png":
        return MAX_THUMBNAIL
    if name == "avatar.vrm":
        return MAX_AVATAR
    if name.endswith(".vrma"):
        return MAX_MOTION
    return 0


def _safe_name(name: str) -> None:
    if "\\" in name or name.startswith("/") or any(part in {"", ".", ".."} for part in PurePosixPath(name).parts):
        raise MRBodyError(f"unsafe archive path: {name!r}")
    if name not in ALLOWED:
        raise MRBodyError(f"unknown payload path: {name}")


def validate_package(path: str | os.PathLike[str]) -> ValidatedBody:
    try:
        archive = zipfile.ZipFile(Path(path), "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise MRBodyError("invalid .mrbody ZIP") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise MRBodyError("too many archive entries")
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise MRBodyError("duplicate archive entries")
        total = 0
        for info in infos:
            _safe_name(info.filename)
            if info.flag_bits & 1:
                raise MRBodyError("encrypted entries are not allowed")
            unix_type = (info.external_attr >> 16) & 0o170000
            if unix_type == 0o120000:
                raise MRBodyError("symlink entries are not allowed")
            if info.is_dir():
                raise MRBodyError("directory entries are not allowed")
            if info.file_size > _entry_limit(info.filename):
                raise MRBodyError(f"{info.filename}: exceeds size limit")
            total += info.file_size
            if total > MAX_TOTAL_UNCOMPRESSED:
                raise MRBodyError("package exceeds total size limit")
        name_set = set(names)
        if not REQUIRED <= name_set:
            raise MRBodyError(f"missing required files: {sorted(REQUIRED-name_set)}")
        manifest = validate_manifest(_loads_json(archive.read("manifest.json"), "manifest.json"))
        bodyprint = validate_bodyprint(_loads_json(archive.read("bodyprint.json"), "bodyprint.json"))
        provenance = validate_provenance(_loads_json(archive.read("provenance.json"), "provenance.json"))
        checksums = _loads_json(archive.read("checksums.json"), "checksums.json")
        payloads = name_set - {"manifest.json", "checksums.json"}
        if not isinstance(checksums, dict) or set(checksums) != payloads:
            raise MRBodyError("checksums.json: entries must exactly match payload files")
        for name, expected in checksums.items():
            if not isinstance(expected, str) or not SHA_RE.fullmatch(expected):
                raise MRBodyError(f"checksums.json: invalid hash for {name}")
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise MRBodyError(f"checksum mismatch: {name}")
        _validate_vrm(archive.read("avatar.vrm"))
        if not archive.read("thumbnail.png").startswith(b"\x89PNG\r\n\x1a\n"):
            raise MRBodyError("thumbnail.png: invalid PNG signature")
        for name in payloads & OPTIONAL:
            _validate_glb(archive.read(name), name)
        return ValidatedBody(manifest, bodyprint, provenance, tuple(sorted(payloads)))


def build_package(
    destination: str | os.PathLike[str],
    *,
    body_id: str,
    name: str,
    avatar_vrm: bytes,
    bodyprint: Mapping[str, Any],
    provenance: Mapping[str, Any],
    thumbnail_png: bytes,
    motions: Mapping[str, bytes] | None = None,
    builder_version: str = "0.1.0",
    builder_revision: str | None = None,
) -> Path:
    if not SLUG_RE.fullmatch(body_id):
        raise MRBodyError("invalid body id")
    motions = dict(motions or {})
    if set(motions) - OPTIONAL:
        raise MRBodyError("unknown motion payload")
    manifest: dict[str, Any] = {
        "format": FORMAT,
        "format_version": 1,
        "id": body_id,
        "name": name,
        "avatar": {"format": "vrm", "version": "1.0", "path": "avatar.vrm"},
        "bodyprint": "bodyprint.json",
        "provenance": "provenance.json",
        "thumbnail": "thumbnail.png",
        "builder": {"name": "bodyrig", "version": builder_version},
    }
    if builder_revision is not None:
        manifest["builder"]["revision"] = builder_revision
    validate_manifest(manifest)
    validate_bodyprint(dict(bodyprint))
    validate_provenance(dict(provenance))
    _validate_vrm(avatar_vrm)
    if not thumbnail_png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MRBodyError("thumbnail_png: invalid PNG signature")
    for motion_name, motion_data in motions.items():
        _validate_glb(motion_data, motion_name)
    payloads = {
        "avatar.vrm": avatar_vrm,
        "bodyprint.json": json.dumps(bodyprint, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode(),
        "provenance.json": json.dumps(provenance, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode(),
        "thumbnail.png": thumbnail_png,
        **motions,
    }
    checksums = {key: hashlib.sha256(value).hexdigest() for key, value in payloads.items()}
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            archive.writestr("checksums.json", json.dumps(checksums, indent=2, sort_keys=True) + "\n")
            for payload_name, payload_data in payloads.items():
                archive.writestr(payload_name, payload_data)
        validate_package(temp)
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return destination


def _file_sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def install_package(
    package_path: str | os.PathLike[str],
    library_dir: str | os.PathLike[str],
    *,
    expected_sha256: str | None = None,
) -> Path:
    expected = None
    if expected_sha256 is not None:
        expected = str(expected_sha256).strip().lower()
        if not SHA_RE.fullmatch(expected):
            raise MRBodyError("invalid expected package SHA-256")

    source = Path(package_path)
    library = Path(library_dir)
    library.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".bodyrig-install-", suffix=".tmp", dir=library)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as output_stream, source.open("rb") as input_stream:
            for block in iter(lambda: input_stream.read(1024 * 1024), b""):
                output_stream.write(block)
            output_stream.flush()
            os.fsync(output_stream.fileno())

        validated = validate_package(temp)
        if expected is not None and _file_sha256(temp) != expected:
            raise MRBodyError("package bytes do not match expected SHA-256 authority")

        target = library / f"{validated.manifest['id']}.mrbody"
        os.replace(temp, target)
        return target
    finally:
        temp.unlink(missing_ok=True)
