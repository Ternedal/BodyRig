from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .person_profiles import PersonProfileError, load_profile
from .person_voice_source import PersonVoiceSourceError, source_files_for_body

FORMAT = "bodyrig-hands-feet-nails-source-capture"
VERSION = 1
POLICY_REVISION = "bodyrig-hands-feet-nails-source-capture-v1"
REQUIRED_REGIONS = ("left_hand", "right_hand", "left_foot", "right_foot")
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_REVISION_RE = re.compile(r"^body-r[0-9]{4}$")
BODYRIG_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
CAPTURE_ID_RE = re.compile(r"^hfncap-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "capture_id",
    "person_id",
    "body_revision",
    "bodyrig_revision",
    "source_manifest_sha256",
    "ffmpeg_version",
    "regions",
    "source_grounded",
    "comparison_only",
    "human_review_required",
    "production_activation",
}
REGION_FIELDS = {
    "scene_id",
    "source_name",
    "source_media_sha256",
    "timestamp_ms",
    "crop_norm",
    "image",
    "image_sha256",
    "width",
    "height",
}


class HandsFeetNailsSourceCaptureError(RuntimeError):
    pass


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _png_dimensions(path: Path) -> tuple[int, int]:
    try:
        raw = path.read_bytes()[:24]
    except OSError as exc:
        raise HandsFeetNailsSourceCaptureError(f"source closeup is unreadable: {path}") from exc
    if len(raw) < 24 or raw[:8] != PNG_SIGNATURE or raw[12:16] != b"IHDR":
        raise HandsFeetNailsSourceCaptureError(f"source closeup is not a canonical PNG: {path}")
    width, height = struct.unpack(">II", raw[16:24])
    if width != 1024 or height != 1024:
        raise HandsFeetNailsSourceCaptureError(
            f"source closeup must be exactly 1024x1024, got {width}x{height}: {path.name}"
        )
    return width, height


def _canonical_identity(person_id: str, body_revision: str, bodyrig_revision: str) -> tuple[str, str, str]:
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    revision = str(bodyrig_revision or "").strip().lower()
    if not PERSON_RE.fullmatch(person):
        raise HandsFeetNailsSourceCaptureError("person id is not canonical")
    if not BODY_REVISION_RE.fullmatch(body):
        raise HandsFeetNailsSourceCaptureError("body revision is not canonical")
    if not BODYRIG_REVISION_RE.fullmatch(revision):
        raise HandsFeetNailsSourceCaptureError("BodyRig revision is not canonical")
    return person, body, revision


def _normalized_crop(value: Any, *, region: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise HandsFeetNailsSourceCaptureError(f"{region} crop_norm must contain x,y,width,height")
    try:
        x, y, width, height = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise HandsFeetNailsSourceCaptureError(f"{region} crop_norm contains a non-numeric value") from exc
    if not all(value == value and abs(value) != float("inf") for value in (x, y, width, height)):
        raise HandsFeetNailsSourceCaptureError(f"{region} crop_norm must contain finite values")
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise HandsFeetNailsSourceCaptureError(f"{region} crop_norm must stay inside normalized frame bounds")
    if width < 0.04 or height < 0.04:
        raise HandsFeetNailsSourceCaptureError(f"{region} crop_norm is implausibly small for identity review")
    return [round(x, 8), round(y, 8), round(width, 8), round(height, 8)]


def _normalize_selections(selections: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(selections, Mapping) or set(selections) != set(REQUIRED_REGIONS):
        raise HandsFeetNailsSourceCaptureError(
            "source capture requires exactly left_hand, right_hand, left_foot and right_foot selections"
        )
    normalized: dict[str, dict[str, Any]] = {}
    for region in REQUIRED_REGIONS:
        raw = selections.get(region)
        if not isinstance(raw, Mapping) or set(raw) != {"scene_id", "timestamp_ms", "crop_norm"}:
            raise HandsFeetNailsSourceCaptureError(f"{region} selection fields are not canonical")
        scene_id = str(raw.get("scene_id") or "").strip()
        if not scene_id or len(scene_id) > 256:
            raise HandsFeetNailsSourceCaptureError(f"{region} scene id is invalid")
        timestamp = raw.get("timestamp_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0 or timestamp > 86_400_000:
            raise HandsFeetNailsSourceCaptureError(f"{region} timestamp_ms is invalid")
        normalized[region] = {
            "scene_id": scene_id,
            "timestamp_ms": timestamp,
            "crop_norm": _normalized_crop(raw.get("crop_norm"), region=region),
        }
    return normalized


def _capture_id(
    *,
    person_id: str,
    body_revision: str,
    bodyrig_revision: str,
    source_manifest_sha256: str,
    selections: Mapping[str, Any],
) -> str:
    payload = {
        "person_id": person_id,
        "body_revision": body_revision,
        "bodyrig_revision": bodyrig_revision,
        "source_manifest_sha256": source_manifest_sha256,
        "selections": selections,
    }
    return "hfncap-" + hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()[:32]


def capture_dir(root: str | os.PathLike[str], person_id: str, body_revision: str, capture_id: str) -> Path:
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    capture = str(capture_id or "").strip().lower()
    if not PERSON_RE.fullmatch(person) or not BODY_REVISION_RE.fullmatch(body) or not CAPTURE_ID_RE.fullmatch(capture):
        raise HandsFeetNailsSourceCaptureError("source capture path identity is invalid")
    return Path(root).expanduser().resolve() / "hands-feet-nails-source-captures" / person / body / capture


def _ffmpeg_filter(crop: Sequence[float]) -> str:
    x, y, width, height = crop
    return (
        f"crop=iw*{width:.8f}:ih*{height:.8f}:iw*{x:.8f}:ih*{y:.8f},"
        "scale=1024:1024:force_original_aspect_ratio=decrease,"
        "pad=1024:1024:(ow-iw)/2:(oh-ih)/2"
    )


def _run_version(ffmpeg_exe: str, runner: Callable[..., Any]) -> str:
    try:
        completed = runner(
            [ffmpeg_exe, "-version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HandsFeetNailsSourceCaptureError("ffmpeg is unavailable for source-grounded detail extraction") from exc
    line = str(getattr(completed, "stdout", "") or "").splitlines()
    version = line[0].strip() if line else ""
    if not version.lower().startswith("ffmpeg version ") or len(version) > 512:
        raise HandsFeetNailsSourceCaptureError("ffmpeg version output is invalid")
    return version


def _extract(
    *,
    ffmpeg_exe: str,
    media: Path,
    timestamp_ms: int,
    crop: Sequence[float],
    output: Path,
    runner: Callable[..., Any],
) -> None:
    seconds = f"{timestamp_ms / 1000.0:.3f}"
    command = [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        seconds,
        "-i",
        str(media),
        "-frames:v",
        "1",
        "-vf",
        _ffmpeg_filter(crop),
        "-compression_level",
        "4",
        "-n",
        str(output),
    ]
    try:
        runner(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HandsFeetNailsSourceCaptureError(f"ffmpeg failed to extract source detail from {media.name}") from exc
    if not output.is_file():
        raise HandsFeetNailsSourceCaptureError("ffmpeg reported success without writing a source closeup")
    _png_dimensions(output)


def _source_authority(root: Path, person_id: str, body_revision: str) -> dict[str, Any]:
    try:
        profile = load_profile(root, person_id)
        source = source_files_for_body(root, profile, body_revision=body_revision)
    except (PersonProfileError, PersonVoiceSourceError) as exc:
        raise HandsFeetNailsSourceCaptureError(str(exc)) from exc
    manifest_sha = str(source.get("manifest_sha256") or "").strip().lower()
    if not SHA256_RE.fullmatch(manifest_sha):
        raise HandsFeetNailsSourceCaptureError("body source manifest SHA-256 is invalid")
    files = source.get("source_files")
    if not isinstance(files, list) or not files:
        raise HandsFeetNailsSourceCaptureError("body source contains no exact media files")
    by_scene: dict[str, dict[str, str]] = {}
    for item in files:
        if not isinstance(item, Mapping):
            raise HandsFeetNailsSourceCaptureError("body source media entry is invalid")
        scene_id = str(item.get("scene_id") or "")
        if not scene_id or scene_id in by_scene:
            raise HandsFeetNailsSourceCaptureError("body source scene ids are empty or ambiguous")
        sha = str(item.get("sha256") or "").lower()
        if not SHA256_RE.fullmatch(sha):
            raise HandsFeetNailsSourceCaptureError("body source media SHA-256 is invalid")
        by_scene[scene_id] = {
            "scene_id": scene_id,
            "name": str(item.get("name") or ""),
            "sha256": sha,
            "path": str(item.get("path") or ""),
        }
    return {"manifest_sha256": manifest_sha, "by_scene": by_scene}


def prepare_source_capture(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    bodyrig_revision: str,
    selections: Mapping[str, Any],
    ffmpeg_exe: str = "ffmpeg",
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person, body, revision = _canonical_identity(person_id, body_revision, bodyrig_revision)
    normalized = _normalize_selections(selections)
    source = _source_authority(root_path, person, body)
    for region, selection in normalized.items():
        if selection["scene_id"] not in source["by_scene"]:
            raise HandsFeetNailsSourceCaptureError(f"{region} references a scene outside the exact body source set")

    capture_id = _capture_id(
        person_id=person,
        body_revision=body,
        bodyrig_revision=revision,
        source_manifest_sha256=source["manifest_sha256"],
        selections=normalized,
    )
    target = capture_dir(root_path, person, body, capture_id)
    if target.exists():
        return read_source_capture(root_path, person, body_revision=body, capture_id=capture_id)

    version = _run_version(ffmpeg_exe, runner)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    stage.mkdir(parents=False, exist_ok=False)
    try:
        regions: dict[str, dict[str, Any]] = {}
        for region in REQUIRED_REGIONS:
            selection = normalized[region]
            media = source["by_scene"][selection["scene_id"]]
            media_path = Path(media["path"]).expanduser().resolve()
            filename = region.replace("_", "-") + ".png"
            output = stage / filename
            _extract(
                ffmpeg_exe=ffmpeg_exe,
                media=media_path,
                timestamp_ms=selection["timestamp_ms"],
                crop=selection["crop_norm"],
                output=output,
                runner=runner,
            )
            width, height = _png_dimensions(output)
            regions[region] = {
                "scene_id": media["scene_id"],
                "source_name": media["name"],
                "source_media_sha256": media["sha256"],
                "timestamp_ms": selection["timestamp_ms"],
                "crop_norm": list(selection["crop_norm"]),
                "image": filename,
                "image_sha256": _sha256_file(output),
                "width": width,
                "height": height,
            }

        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "capture_id": capture_id,
            "person_id": person,
            "body_revision": body,
            "bodyrig_revision": revision,
            "source_manifest_sha256": source["manifest_sha256"],
            "ffmpeg_version": version,
            "regions": regions,
            "source_grounded": True,
            "comparison_only": True,
            "human_review_required": True,
            "production_activation": False,
        }
        manifest = stage / "source-capture.json"
        manifest.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        try:
            os.replace(stage, target)
        except FileExistsError:
            shutil.rmtree(stage, ignore_errors=True)
        verified = read_source_capture(root_path, person, body_revision=body, capture_id=capture_id)
        return verified
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def read_source_capture(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    capture_id: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    capture = str(capture_id or "").strip().lower()
    path = capture_dir(root_path, person, body, capture) / "source-capture.json"
    if not path.is_file():
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture is unreadable") from exc
    if not isinstance(value, dict) or set(value) != TOP_FIELDS:
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture format/version/policy mismatch")
    revision = str(value.get("bodyrig_revision") or "").lower()
    _canonical_identity(person, body, revision)
    if value.get("capture_id") != capture or value.get("person_id") != person or value.get("body_revision") != body:
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture identity mismatch")
    source = _source_authority(root_path, person, body)
    if value.get("source_manifest_sha256") != source["manifest_sha256"]:
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture no longer matches the body source manifest")
    if not str(value.get("ffmpeg_version") or "").lower().startswith("ffmpeg version "):
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture has invalid ffmpeg provenance")
    if value.get("source_grounded") is not True or value.get("comparison_only") is not True:
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture crossed its comparison-only authority boundary")
    if value.get("human_review_required") is not True or value.get("production_activation") is not False:
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture human/production boundary is invalid")

    regions = value.get("regions")
    if not isinstance(regions, dict) or set(regions) != set(REQUIRED_REGIONS):
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture region set is invalid")
    normalized_for_id: dict[str, dict[str, Any]] = {}
    capture_root = path.parent.resolve()
    for region in REQUIRED_REGIONS:
        item = regions.get(region)
        if not isinstance(item, dict) or set(item) != REGION_FIELDS:
            raise HandsFeetNailsSourceCaptureError(f"{region} source capture fields are invalid")
        scene_id = str(item.get("scene_id") or "")
        media = source["by_scene"].get(scene_id)
        if media is None:
            raise HandsFeetNailsSourceCaptureError(f"{region} source scene no longer belongs to the body source set")
        if item.get("source_name") != media["name"] or item.get("source_media_sha256") != media["sha256"]:
            raise HandsFeetNailsSourceCaptureError(f"{region} source media no longer matches exact body source bytes")
        timestamp = item.get("timestamp_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
            raise HandsFeetNailsSourceCaptureError(f"{region} source timestamp is invalid")
        crop = _normalized_crop(item.get("crop_norm"), region=region)
        image_name = str(item.get("image") or "")
        if Path(image_name).name != image_name or image_name != region.replace("_", "-") + ".png":
            raise HandsFeetNailsSourceCaptureError(f"{region} source image path is not canonical")
        image_path = (capture_root / image_name).resolve()
        try:
            image_path.relative_to(capture_root)
        except ValueError as exc:
            raise HandsFeetNailsSourceCaptureError(f"{region} source image escaped capture root") from exc
        width, height = _png_dimensions(image_path)
        actual_sha = _sha256_file(image_path)
        if item.get("image_sha256") != actual_sha or item.get("width") != width or item.get("height") != height:
            raise HandsFeetNailsSourceCaptureError(f"{region} source closeup bytes no longer match capture authority")
        normalized_for_id[region] = {"scene_id": scene_id, "timestamp_ms": timestamp, "crop_norm": crop}

    expected_id = _capture_id(
        person_id=person,
        body_revision=body,
        bodyrig_revision=revision,
        source_manifest_sha256=source["manifest_sha256"],
        selections=normalized_for_id,
    )
    if expected_id != capture:
        raise HandsFeetNailsSourceCaptureError("hands/feet/nails source capture id no longer matches exact selections")
    return value
