from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .hands_feet_nails_source_capture import (
    HandsFeetNailsSourceCaptureError,
    _extract,
    _png_dimensions,
    _run_version,
    _sha256_file,
    _source_authority,
)

FORMAT = "bodyrig-wardrobe-source-capture"
VERSION = 1
POLICY_REVISION = "bodyrig-wardrobe-source-capture-v1"
REQUIRED_VIEWS = ("front", "left_side", "right_side", "back")
SLOTS = {"one_piece", "upper", "lower", "outerwear", "footwear", "headwear"}
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_REVISION_RE = re.compile(r"^body-r[0-9]{4}$")
BODYRIG_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
CAPTURE_ID_RE = re.compile(r"^wardcap-[0-9a-f]{32}$")
GARMENT_ID_RE = re.compile(r"^garment-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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
    "views",
    "garments",
    "footwear_present",
    "source_grounded",
    "comparison_only",
    "human_review_required",
    "production_activation",
}
VIEW_FIELDS = {
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
GARMENT_FIELDS = {"garment_id", "slot", "layer", "description", "source_views"}


class WardrobeSourceCaptureError(RuntimeError):
    pass


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _identity(person_id: str, body_revision: str, bodyrig_revision: str) -> tuple[str, str, str]:
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    revision = str(bodyrig_revision or "").strip().lower()
    if not PERSON_RE.fullmatch(person):
        raise WardrobeSourceCaptureError("person id is not canonical")
    if not BODY_REVISION_RE.fullmatch(body):
        raise WardrobeSourceCaptureError("body revision is not canonical")
    if not BODYRIG_REVISION_RE.fullmatch(revision):
        raise WardrobeSourceCaptureError("BodyRig revision is not canonical")
    return person, body, revision


def _crop(value: Any, *, view: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise WardrobeSourceCaptureError(f"{view} crop_norm must contain x,y,width,height")
    try:
        x, y, width, height = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise WardrobeSourceCaptureError(f"{view} crop_norm contains a non-numeric value") from exc
    if not all(item == item and abs(item) != float("inf") for item in (x, y, width, height)):
        raise WardrobeSourceCaptureError(f"{view} crop_norm must contain finite values")
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise WardrobeSourceCaptureError(f"{view} crop_norm must stay inside normalized frame bounds")
    if width < 0.18 or height < 0.35:
        raise WardrobeSourceCaptureError(f"{view} crop is too small for full-presentation wardrobe review")
    return [round(x, 8), round(y, 8), round(width, 8), round(height, 8)]


def _normalize_views(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping) or set(value) != set(REQUIRED_VIEWS):
        raise WardrobeSourceCaptureError("wardrobe capture requires exactly front, left_side, right_side and back source views")
    result: dict[str, dict[str, Any]] = {}
    for view in REQUIRED_VIEWS:
        raw = value.get(view)
        if not isinstance(raw, Mapping) or set(raw) != {"scene_id", "timestamp_ms", "crop_norm"}:
            raise WardrobeSourceCaptureError(f"{view} source selection fields are not canonical")
        scene_id = str(raw.get("scene_id") or "").strip()
        timestamp = raw.get("timestamp_ms")
        if not scene_id or len(scene_id) > 256:
            raise WardrobeSourceCaptureError(f"{view} scene id is invalid")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0 or timestamp > 86_400_000:
            raise WardrobeSourceCaptureError(f"{view} timestamp_ms is invalid")
        result[view] = {
            "scene_id": scene_id,
            "timestamp_ms": timestamp,
            "crop_norm": _crop(raw.get("crop_norm"), view=view),
        }
    return result


def _normalize_garments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise WardrobeSourceCaptureError("wardrobe inventory must contain 1-12 source-visible garments")
    normalized: list[dict[str, Any]] = []
    seen_identity: set[tuple[str, int]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping) or set(item) != {"slot", "layer", "description", "source_views"}:
            raise WardrobeSourceCaptureError(f"garment {index + 1} fields are not canonical")
        slot = str(item.get("slot") or "").strip().lower()
        layer = item.get("layer")
        description = str(item.get("description") or "").strip()
        source_views = item.get("source_views")
        if slot not in SLOTS:
            raise WardrobeSourceCaptureError(f"garment {index + 1} slot is unsupported")
        if isinstance(layer, bool) or not isinstance(layer, int) or not 0 <= layer <= 15:
            raise WardrobeSourceCaptureError(f"garment {index + 1} layer is invalid")
        if not description or len(description) > 200 or re.fullmatch(r"<[^>]+>", description):
            raise WardrobeSourceCaptureError(f"garment {index + 1} requires a real source-visible description")
        if not isinstance(source_views, list) or not source_views:
            raise WardrobeSourceCaptureError(f"garment {index + 1} must cite at least one source view")
        views = [str(view) for view in source_views]
        if len(set(views)) != len(views) or any(view not in REQUIRED_VIEWS for view in views):
            raise WardrobeSourceCaptureError(f"garment {index + 1} source view set is invalid")
        identity = (slot, layer)
        if identity in seen_identity:
            raise WardrobeSourceCaptureError("wardrobe inventory contains an ambiguous slot/layer pair")
        seen_identity.add(identity)
        core = {"slot": slot, "layer": layer, "description": description, "source_views": views}
        garment_id = "garment-" + hashlib.sha256(_canonical_json_bytes(core)).hexdigest()[:32]
        normalized.append({"garment_id": garment_id, **core})
    if not any(item["slot"] in {"one_piece", "upper", "lower", "outerwear"} for item in normalized):
        raise WardrobeSourceCaptureError("wardrobe inventory has no primary source-visible garment")
    normalized.sort(key=lambda item: (int(item["layer"]), str(item["slot"]), str(item["garment_id"])))
    return normalized


def _capture_id(*, person_id: str, body_revision: str, bodyrig_revision: str, source_manifest_sha256: str, views: Mapping[str, Any], garments: list[dict[str, Any]]) -> str:
    payload = {
        "person_id": person_id,
        "body_revision": body_revision,
        "bodyrig_revision": bodyrig_revision,
        "source_manifest_sha256": source_manifest_sha256,
        "views": views,
        "garments": garments,
    }
    return "wardcap-" + hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()[:32]


def capture_dir(root: str | os.PathLike[str], person_id: str, body_revision: str, capture_id: str) -> Path:
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    capture = str(capture_id or "").strip().lower()
    if not PERSON_RE.fullmatch(person) or not BODY_REVISION_RE.fullmatch(body) or not CAPTURE_ID_RE.fullmatch(capture):
        raise WardrobeSourceCaptureError("wardrobe source capture path identity is invalid")
    return Path(root).expanduser().resolve() / "wardrobe-source-captures" / person / body / capture


def prepare_source_capture(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    bodyrig_revision: str,
    views: Mapping[str, Any],
    garments: Any,
    ffmpeg_exe: str = "ffmpeg",
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person, body, revision = _identity(person_id, body_revision, bodyrig_revision)
    normalized_views = _normalize_views(views)
    normalized_garments = _normalize_garments(garments)
    try:
        source = _source_authority(root_path, person, body)
    except HandsFeetNailsSourceCaptureError as exc:
        raise WardrobeSourceCaptureError(str(exc)) from exc
    for view, selection in normalized_views.items():
        if selection["scene_id"] not in source["by_scene"]:
            raise WardrobeSourceCaptureError(f"{view} references a scene outside the exact body source set")
    capture_id = _capture_id(
        person_id=person,
        body_revision=body,
        bodyrig_revision=revision,
        source_manifest_sha256=source["manifest_sha256"],
        views=normalized_views,
        garments=normalized_garments,
    )
    target = capture_dir(root_path, person, body, capture_id)
    if target.exists():
        return read_source_capture(root_path, person, body_revision=body, capture_id=capture_id)
    try:
        ffmpeg_version = _run_version(ffmpeg_exe, runner)
    except HandsFeetNailsSourceCaptureError as exc:
        raise WardrobeSourceCaptureError(str(exc)) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    stage.mkdir(parents=False, exist_ok=False)
    try:
        captured: dict[str, dict[str, Any]] = {}
        for view in REQUIRED_VIEWS:
            selection = normalized_views[view]
            media = source["by_scene"][selection["scene_id"]]
            media_path = Path(media["path"]).expanduser().resolve()
            filename = view.replace("_", "-") + ".png"
            output = stage / filename
            try:
                _extract(
                    ffmpeg_exe=ffmpeg_exe,
                    media=media_path,
                    timestamp_ms=selection["timestamp_ms"],
                    crop=selection["crop_norm"],
                    output=output,
                    runner=runner,
                )
                width, height = _png_dimensions(output)
            except HandsFeetNailsSourceCaptureError as exc:
                raise WardrobeSourceCaptureError(str(exc)) from exc
            captured[view] = {
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
            "ffmpeg_version": ffmpeg_version,
            "views": captured,
            "garments": normalized_garments,
            "footwear_present": any(item["slot"] == "footwear" for item in normalized_garments),
            "source_grounded": True,
            "comparison_only": True,
            "human_review_required": True,
            "production_activation": False,
        }
        (stage / "source-capture.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        try:
            os.replace(stage, target)
        except FileExistsError:
            shutil.rmtree(stage, ignore_errors=True)
        return read_source_capture(root_path, person, body_revision=body, capture_id=capture_id)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def read_source_capture(root: str | os.PathLike[str], person_id: str, *, body_revision: str, capture_id: str) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    capture = str(capture_id or "").strip().lower()
    target = capture_dir(root_path, person, body, capture)
    manifest = target / "source-capture.json"
    if not manifest.is_file():
        raise WardrobeSourceCaptureError("wardrobe source capture receipt is missing")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WardrobeSourceCaptureError("wardrobe source capture receipt is unreadable") from exc
    if not isinstance(value, dict) or set(value) != TOP_FIELDS:
        raise WardrobeSourceCaptureError("wardrobe source capture fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise WardrobeSourceCaptureError("wardrobe source capture format/version/policy mismatch")
    if value.get("capture_id") != capture or value.get("person_id") != person or value.get("body_revision") != body:
        raise WardrobeSourceCaptureError("wardrobe source capture identity/path mismatch")
    revision = str(value.get("bodyrig_revision") or "").lower()
    if not BODYRIG_REVISION_RE.fullmatch(revision):
        raise WardrobeSourceCaptureError("wardrobe source capture BodyRig revision is invalid")
    try:
        source = _source_authority(root_path, person, body)
    except HandsFeetNailsSourceCaptureError as exc:
        raise WardrobeSourceCaptureError(f"wardrobe source lineage failed: {exc}") from exc
    if value.get("source_manifest_sha256") != source["manifest_sha256"]:
        raise WardrobeSourceCaptureError("wardrobe source manifest no longer matches exact body source")
    raw_views = value.get("views")
    if not isinstance(raw_views, Mapping) or set(raw_views) != set(REQUIRED_VIEWS):
        raise WardrobeSourceCaptureError("wardrobe source view set is not canonical")
    normalized_selections: dict[str, dict[str, Any]] = {}
    for view in REQUIRED_VIEWS:
        item = raw_views[view]
        if not isinstance(item, Mapping) or set(item) != VIEW_FIELDS:
            raise WardrobeSourceCaptureError(f"{view} wardrobe source view fields are invalid")
        scene_id = str(item.get("scene_id") or "")
        media = source["by_scene"].get(scene_id)
        if media is None:
            raise WardrobeSourceCaptureError(f"{view} source scene is no longer in exact body source set")
        if item.get("source_name") != media["name"] or item.get("source_media_sha256") != media["sha256"]:
            raise WardrobeSourceCaptureError(f"{view} source media identity/hash changed")
        if item.get("width") != 1024 or item.get("height") != 1024:
            raise WardrobeSourceCaptureError(f"{view} source image dimensions are invalid")
        image_name = view.replace("_", "-") + ".png"
        if item.get("image") != image_name:
            raise WardrobeSourceCaptureError(f"{view} source image filename is invalid")
        image = target / image_name
        try:
            _png_dimensions(image)
        except HandsFeetNailsSourceCaptureError as exc:
            raise WardrobeSourceCaptureError(str(exc)) from exc
        actual_sha = _sha256_file(image)
        if item.get("image_sha256") != actual_sha:
            raise WardrobeSourceCaptureError(f"{view} source image bytes changed")
        timestamp = item.get("timestamp_ms")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise WardrobeSourceCaptureError(f"{view} timestamp is invalid")
        normalized_selections[view] = {
            "scene_id": scene_id,
            "timestamp_ms": timestamp,
            "crop_norm": _crop(item.get("crop_norm"), view=view),
        }
    raw_garments = value.get("garments")
    if not isinstance(raw_garments, list):
        raise WardrobeSourceCaptureError("wardrobe garment inventory is invalid")
    normalized_garments = _normalize_garments(
        [
            {
                "slot": item.get("slot"),
                "layer": item.get("layer"),
                "description": item.get("description"),
                "source_views": item.get("source_views"),
            }
            if isinstance(item, Mapping)
            else item
            for item in raw_garments
        ]
    )
    if raw_garments != normalized_garments:
        raise WardrobeSourceCaptureError("wardrobe garment inventory is not canonical")
    if value.get("footwear_present") is not any(item["slot"] == "footwear" for item in normalized_garments):
        raise WardrobeSourceCaptureError("wardrobe footwear presence is inconsistent")
    expected_capture = _capture_id(
        person_id=person,
        body_revision=body,
        bodyrig_revision=revision,
        source_manifest_sha256=str(value["source_manifest_sha256"]),
        views=normalized_selections,
        garments=normalized_garments,
    )
    if expected_capture != capture:
        raise WardrobeSourceCaptureError("wardrobe source capture id no longer matches exact selections/inventory")
    if value.get("source_grounded") is not True or value.get("comparison_only") is not True or value.get("human_review_required") is not True or value.get("production_activation") is not False:
        raise WardrobeSourceCaptureError("wardrobe source capture crossed the review-only boundary")
    return value
