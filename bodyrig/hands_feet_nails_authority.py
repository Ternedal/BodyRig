from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .hands_feet_nails_source_capture import (
    REQUIRED_REGIONS,
    HandsFeetNailsSourceCaptureError,
    capture_dir,
    read_source_capture,
)

FORMAT = "bodyrig-hands-feet-nails-authority"
VERSION = 1
POLICY_REVISION = "bodyrig-hands-feet-nails-authority-v1"
RENDER_FORMAT = "bodyrig-hands-feet-nails-render-set"
RENDER_VERSION = 1
RENDER_SEMANTICS = "human-review-diagnostic-not-physical-pass"
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
PERSON_REVISION_RE = re.compile(r"^person-r[0-9]{4}$")
BODY_REVISION_RE = re.compile(r"^body-r[0-9]{4}$")
BODY_ID_RE = re.compile(r"^body-[0-9a-f]{32}$")
VOICE_REVISION_RE = re.compile(r"^voice-r[0-9]{4}$")
VOICE_ID_RE = re.compile(r"^voice-[0-9a-f]{32}$")
PERSONALITY_REVISION_RE = re.compile(r"^personality-r[0-9]{4}$")
AUDITION_ID_RE = re.compile(r"^audition-[0-9a-f]{32}$")
BODYRIG_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
REVIEW_ID_RE = re.compile(r"^hfnreview-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHECKLIST_FIELDS = {
    "hand_geometry_review_passed",
    "finger_geometry_review_passed",
    "foot_geometry_review_passed",
    "toe_geometry_review_passed",
    "skin_detail_review_passed",
    "fingernails_review_passed",
    "toenails_review_passed",
    "left_right_source_render_consistency_passed",
}
TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "review_id",
    "person_id",
    "person_revision",
    "assembly_fingerprint",
    "body_revision",
    "body_id",
    "body_package_sha256",
    "bodyrig_revision",
    "source_capture_id",
    "source_capture_sha256",
    "source_manifest_sha256",
    "source_region_sha256",
    "render_manifest_sha256",
    "render_region_sha256",
    "reviewed_utc",
    "checklist",
    "quality_note",
    "state",
    "source_grounded",
    "operator_supplied",
    "hand_geometry_review_passed",
    "finger_geometry_review_passed",
    "foot_geometry_review_passed",
    "toe_geometry_review_passed",
    "skin_detail_review_passed",
    "fingernails_review_passed",
    "toenails_review_passed",
    "left_right_source_render_consistency_passed",
    "production_activation",
}
RENDER_FIELDS = {"format", "version", "body_id", "package_sha256", "semantics", "snapshots"}
RENDER_ENTRY_FIELDS = {"view", "file", "sha256", "width", "height"}


class HandsFeetNailsAuthorityError(RuntimeError):
    pass


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise HandsFeetNailsAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _png_dimensions(path: Path) -> tuple[int, int]:
    try:
        raw = path.read_bytes()[:24]
    except OSError as exc:
        raise HandsFeetNailsAuthorityError(f"render detail image is unreadable: {path}") from exc
    if len(raw) < 24 or raw[:8] != PNG_SIGNATURE or raw[12:16] != b"IHDR":
        raise HandsFeetNailsAuthorityError(f"render detail image is not PNG: {path}")
    width, height = struct.unpack(">II", raw[16:24])
    if width != 1024 or height != 1024:
        raise HandsFeetNailsAuthorityError(
            f"render detail image must be exactly 1024x1024, got {width}x{height}: {path.name}"
        )
    return width, height


def _assembly_identity(receipt: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(receipt, Mapping) or receipt.get("format") != "bodyrig-person-assembly-receipt" or receipt.get("version") != 2:
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority requires a current audition-bound Person assembly")
    person_id = str(receipt.get("person_id") or "").strip().lower()
    person_revision = str(receipt.get("person_revision") or "").strip().lower()
    assembly_fingerprint = _sha(receipt.get("assembly_fingerprint"), "assembly fingerprint")
    body = receipt.get("body")
    voice = receipt.get("voice")
    personality = receipt.get("personality")
    audition = receipt.get("audition")
    if not isinstance(body, Mapping) or not isinstance(voice, Mapping) or not isinstance(personality, Mapping) or not isinstance(audition, Mapping):
        raise HandsFeetNailsAuthorityError("Person assembly is missing body/voice/personality/audition bindings")

    body_revision = str(body.get("revision_id") or "").strip().lower()
    body_id = str(body.get("body_id") or "").strip().lower()
    voice_revision = str(voice.get("revision_id") or "").strip().lower()
    voice_id = str(voice.get("voice_id") or "").strip().lower()
    voice_package = str(voice.get("voice_package") or "").strip()
    personality_revision = str(personality.get("revision_id") or "").strip().lower()
    default_language = str(personality.get("default_language") or "").strip()
    audition_id = str(audition.get("audition_id") or "").strip().lower()

    if not PERSON_RE.fullmatch(person_id) or not PERSON_REVISION_RE.fullmatch(person_revision):
        raise HandsFeetNailsAuthorityError("Person assembly identity is not canonical")
    if not BODY_REVISION_RE.fullmatch(body_revision) or not BODY_ID_RE.fullmatch(body_id):
        raise HandsFeetNailsAuthorityError("Person assembly body identity is not canonical")
    if not VOICE_REVISION_RE.fullmatch(voice_revision) or not VOICE_ID_RE.fullmatch(voice_id) or not voice_package:
        raise HandsFeetNailsAuthorityError("Person assembly VoiceRig identity is not canonical")
    if not PERSONALITY_REVISION_RE.fullmatch(personality_revision) or not default_language:
        raise HandsFeetNailsAuthorityError("Person assembly personality identity is not canonical")
    if not AUDITION_ID_RE.fullmatch(audition_id):
        raise HandsFeetNailsAuthorityError("Person assembly audition identity is not canonical")

    _sha(body.get("package_sha256"), "registered assembly body package SHA-256")
    _sha(voice.get("package_sha256"), "VoiceRig package SHA-256")
    _sha(personality.get("instructions_sha256"), "personality instructions SHA-256")
    _sha(personality.get("style_notes_sha256"), "personality style-notes SHA-256")
    _sha(audition.get("receipt_sha256"), "audition receipt SHA-256")
    return {
        "person_id": person_id,
        "person_revision": person_revision,
        "assembly_fingerprint": assembly_fingerprint,
        "body_revision": body_revision,
        "body_id": body_id,
    }


def _release_identity(status: Mapping[str, Any], assembly: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(status, Mapping):
        raise HandsFeetNailsAuthorityError("body release status is missing")
    if status.get("format") != "bodyrig-person-release-status" or status.get("version") != 1:
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority requires canonical Person body-release status v1")
    person_id = str(status.get("person_id") or "").strip().lower()
    body_revision = str(status.get("body_revision") or "").strip().lower()
    body_id = str(status.get("body_id") or "").strip().lower()
    package_sha = _sha(status.get("package_sha256"), "exact body release package SHA-256")
    if person_id != assembly["person_id"]:
        raise HandsFeetNailsAuthorityError("body release belongs to a different Person")
    if body_revision != assembly["body_revision"]:
        raise HandsFeetNailsAuthorityError("body release belongs to a different body revision")
    if body_id != assembly["body_id"]:
        raise HandsFeetNailsAuthorityError("body release body id no longer matches the Person assembly")
    return {"package_sha256": package_sha}


def _safe_entry_path(root: Path, filename: Any, *, label: str) -> Path:
    name = str(filename or "")
    if not name or Path(name).name != name or "/" in name or "\\" in name:
        raise HandsFeetNailsAuthorityError(f"{label} filename is not a safe leaf")
    path = (root / name).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise HandsFeetNailsAuthorityError(f"{label} escaped render root") from exc
    if not path.is_file():
        raise HandsFeetNailsAuthorityError(f"{label} is missing: {name}")
    return path


def validate_render_manifest(
    manifest_path: str | os.PathLike[str],
    *,
    body_id: str,
    package_sha256: str,
) -> dict[str, Any]:
    path = Path(manifest_path).expanduser().resolve()
    if not path.is_file():
        raise HandsFeetNailsAuthorityError("hands/feet/nails render manifest is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsAuthorityError("hands/feet/nails render manifest is unreadable") from exc
    if not isinstance(value, dict) or set(value) != RENDER_FIELDS:
        raise HandsFeetNailsAuthorityError("hands/feet/nails render manifest fields are not canonical")
    if value.get("format") != RENDER_FORMAT or value.get("version") != RENDER_VERSION:
        raise HandsFeetNailsAuthorityError("hands/feet/nails render manifest format/version mismatch")
    if value.get("semantics") != RENDER_SEMANTICS:
        raise HandsFeetNailsAuthorityError("hands/feet/nails render manifest semantics crossed the human-review-only boundary")
    if str(value.get("body_id") or "") != body_id:
        raise HandsFeetNailsAuthorityError("hands/feet/nails render body id does not match exact Person body")
    if _sha(value.get("package_sha256"), "render package SHA-256") != package_sha256:
        raise HandsFeetNailsAuthorityError("hands/feet/nails render bytes were captured from a different body package")
    snapshots = value.get("snapshots")
    if not isinstance(snapshots, list) or [item.get("view") for item in snapshots if isinstance(item, Mapping)] != list(REQUIRED_REGIONS):
        raise HandsFeetNailsAuthorityError("hands/feet/nails render manifest does not contain the four canonical detail views")
    hashes: dict[str, str] = {}
    root = path.parent.resolve()
    for expected_region, item in zip(REQUIRED_REGIONS, snapshots, strict=True):
        if not isinstance(item, Mapping) or set(item) != RENDER_ENTRY_FIELDS:
            raise HandsFeetNailsAuthorityError(f"{expected_region} render entry fields are invalid")
        if item.get("view") != expected_region:
            raise HandsFeetNailsAuthorityError("hands/feet/nails render view order is not canonical")
        image = _safe_entry_path(root, item.get("file"), label=f"{expected_region} render image")
        width, height = _png_dimensions(image)
        actual_sha = _sha256_file(image)
        if item.get("width") != width or item.get("height") != height or item.get("sha256") != actual_sha:
            raise HandsFeetNailsAuthorityError(f"{expected_region} render bytes no longer match render manifest")
        hashes[expected_region] = actual_sha
    return {"manifest": value, "manifest_path": path, "manifest_sha256": _sha256_file(path), "region_sha256": hashes}


def _review_id(
    *,
    person_id: str,
    person_revision: str,
    assembly_fingerprint: str,
    body_package_sha256: str,
    bodyrig_revision: str,
    source_capture_sha256: str,
    render_manifest_sha256: str,
) -> str:
    payload = {
        "person_id": person_id,
        "person_revision": person_revision,
        "assembly_fingerprint": assembly_fingerprint,
        "body_package_sha256": body_package_sha256,
        "bodyrig_revision": bodyrig_revision,
        "source_capture_sha256": source_capture_sha256,
        "render_manifest_sha256": render_manifest_sha256,
    }
    return "hfnreview-" + hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()[:32]


def authority_dir(root: str | os.PathLike[str], person_id: str, person_revision: str, review_id: str) -> Path:
    person = str(person_id or "").strip().lower()
    revision = str(person_revision or "").strip().lower()
    review = str(review_id or "").strip().lower()
    if not PERSON_RE.fullmatch(person) or not PERSON_REVISION_RE.fullmatch(revision) or not REVIEW_ID_RE.fullmatch(review):
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority path identity is invalid")
    return Path(root).expanduser().resolve() / "hands-feet-nails-authorities" / person / revision / review


def validate_authority_structure(
    value: Mapping[str, Any],
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority format/version/policy mismatch")
    assembly = _assembly_identity(assembly_receipt)
    release = _release_identity(body_release_status, assembly)
    exact = {
        "person_id": assembly["person_id"],
        "person_revision": assembly["person_revision"],
        "assembly_fingerprint": assembly["assembly_fingerprint"],
        "body_revision": assembly["body_revision"],
        "body_id": assembly["body_id"],
        "body_package_sha256": release["package_sha256"],
    }
    for field, expected in exact.items():
        if str(value.get(field) or "").lower() != expected:
            raise HandsFeetNailsAuthorityError(f"hands/feet/nails authority no longer matches exact {field}")
    review_id = str(value.get("review_id") or "").lower()
    bodyrig_revision = str(value.get("bodyrig_revision") or "").lower()
    source_capture_id = str(value.get("source_capture_id") or "").lower()
    if not REVIEW_ID_RE.fullmatch(review_id) or not BODYRIG_REVISION_RE.fullmatch(bodyrig_revision):
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority revision/review id is invalid")
    if not re.fullmatch(r"^hfncap-[0-9a-f]{32}$", source_capture_id):
        raise HandsFeetNailsAuthorityError("hands/feet/nails source capture id is invalid")
    source_capture_sha = _sha(value.get("source_capture_sha256"), "source capture SHA-256")
    _sha(value.get("source_manifest_sha256"), "source manifest SHA-256")
    render_manifest_sha = _sha(value.get("render_manifest_sha256"), "render manifest SHA-256")
    source_regions = value.get("source_region_sha256")
    render_regions = value.get("render_region_sha256")
    if not isinstance(source_regions, Mapping) or set(source_regions) != set(REQUIRED_REGIONS):
        raise HandsFeetNailsAuthorityError("hands/feet/nails source region hash set is invalid")
    if not isinstance(render_regions, Mapping) or set(render_regions) != set(REQUIRED_REGIONS):
        raise HandsFeetNailsAuthorityError("hands/feet/nails render region hash set is invalid")
    for region in REQUIRED_REGIONS:
        _sha(source_regions.get(region), f"{region} source image SHA-256")
        _sha(render_regions.get(region), f"{region} render image SHA-256")
    checklist = value.get("checklist")
    if not isinstance(checklist, Mapping) or set(checklist) != CHECKLIST_FIELDS:
        raise HandsFeetNailsAuthorityError("hands/feet/nails review checklist fields are not canonical")
    if any(checklist.get(field) is not True for field in CHECKLIST_FIELDS):
        raise HandsFeetNailsAuthorityError("hands/feet/nails review checklist is not fully passed")
    note = str(value.get("quality_note") or "").strip()
    if not note or re.fullmatch(r"<[^>]+>", note) or len(note) > 4000:
        raise HandsFeetNailsAuthorityError("hands/feet/nails review requires a real non-placeholder quality note")
    if value.get("state") != "complete" or value.get("source_grounded") is not True or value.get("operator_supplied") is not True:
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority is not a complete operator-supplied source review")
    for field in CHECKLIST_FIELDS:
        if value.get(field) is not True:
            raise HandsFeetNailsAuthorityError(f"hands/feet/nails authority did not pass {field}")
    if value.get("production_activation") is not False:
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority cannot independently activate production")
    expected_review_id = _review_id(
        person_id=assembly["person_id"],
        person_revision=assembly["person_revision"],
        assembly_fingerprint=assembly["assembly_fingerprint"],
        body_package_sha256=release["package_sha256"],
        bodyrig_revision=bodyrig_revision,
        source_capture_sha256=source_capture_sha,
        render_manifest_sha256=render_manifest_sha,
    )
    if review_id != expected_review_id:
        raise HandsFeetNailsAuthorityError("hands/feet/nails review id no longer matches exact evidence identity")
    return dict(value)


def write_authority(
    root: str | os.PathLike[str],
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
    source_capture_id: str,
    render_manifest_path: str | os.PathLike[str],
    bodyrig_revision: str,
    checklist: Mapping[str, Any],
    quality_note: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    assembly = _assembly_identity(assembly_receipt)
    release = _release_identity(body_release_status, assembly)
    revision = str(bodyrig_revision or "").strip().lower()
    if not BODYRIG_REVISION_RE.fullmatch(revision):
        raise HandsFeetNailsAuthorityError("BodyRig review revision is not canonical")
    normalized_checklist = dict(checklist)
    if set(normalized_checklist) != CHECKLIST_FIELDS or any(normalized_checklist.get(field) is not True for field in CHECKLIST_FIELDS):
        raise HandsFeetNailsAuthorityError("hands/feet/nails review requires explicit PASS for every checklist field")
    note = str(quality_note or "").strip()
    if not note or re.fullmatch(r"<[^>]+>", note) or len(note) > 4000:
        raise HandsFeetNailsAuthorityError("hands/feet/nails review requires a real non-placeholder quality note")
    try:
        source = read_source_capture(
            root_path,
            assembly["person_id"],
            body_revision=assembly["body_revision"],
            capture_id=source_capture_id,
        )
    except HandsFeetNailsSourceCaptureError as exc:
        raise HandsFeetNailsAuthorityError(f"source capture authority failed: {exc}") from exc
    if str(source.get("bodyrig_revision") or "").lower() != revision:
        raise HandsFeetNailsAuthorityError("source capture and human review must use the same exact BodyRig revision")
    source_manifest_path = capture_dir(
        root_path,
        assembly["person_id"],
        assembly["body_revision"],
        str(source["capture_id"]),
    ) / "source-capture.json"
    source_capture_sha = _sha256_file(source_manifest_path)
    render = validate_render_manifest(
        render_manifest_path,
        body_id=assembly["body_id"],
        package_sha256=release["package_sha256"],
    )
    review_id = _review_id(
        person_id=assembly["person_id"],
        person_revision=assembly["person_revision"],
        assembly_fingerprint=assembly["assembly_fingerprint"],
        body_package_sha256=release["package_sha256"],
        bodyrig_revision=revision,
        source_capture_sha256=source_capture_sha,
        render_manifest_sha256=render["manifest_sha256"],
    )
    target = authority_dir(root_path, assembly["person_id"], assembly["person_revision"], review_id)
    if target.exists():
        raise HandsFeetNailsAuthorityError("refusing to overwrite existing hands/feet/nails authority")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    stage.mkdir(parents=False, exist_ok=False)
    try:
        source_out = stage / "source"
        render_out = stage / "render"
        source_out.mkdir()
        render_out.mkdir()
        source_capture_root = source_manifest_path.parent
        for name in ["source-capture.json", *[region.replace("_", "-") + ".png" for region in REQUIRED_REGIONS]]:
            source_file = source_capture_root / name
            shutil.copyfile(source_file, source_out / name)
        render_manifest = Path(render["manifest_path"])
        shutil.copyfile(render_manifest, render_out / "hands-feet-nails-render-set.json")
        for item in render["manifest"]["snapshots"]:
            shutil.copyfile(render_manifest.parent / str(item["file"]), render_out / str(item["file"]))

        source_region_sha = {region: str(source["regions"][region]["image_sha256"]) for region in REQUIRED_REGIONS}
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "review_id": review_id,
            "person_id": assembly["person_id"],
            "person_revision": assembly["person_revision"],
            "assembly_fingerprint": assembly["assembly_fingerprint"],
            "body_revision": assembly["body_revision"],
            "body_id": assembly["body_id"],
            "body_package_sha256": release["package_sha256"],
            "bodyrig_revision": revision,
            "source_capture_id": str(source["capture_id"]),
            "source_capture_sha256": source_capture_sha,
            "source_manifest_sha256": str(source["source_manifest_sha256"]),
            "source_region_sha256": source_region_sha,
            "render_manifest_sha256": render["manifest_sha256"],
            "render_region_sha256": dict(render["region_sha256"]),
            "reviewed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "checklist": {field: True for field in sorted(CHECKLIST_FIELDS)},
            "quality_note": note,
            "state": "complete",
            "source_grounded": True,
            "operator_supplied": True,
            **{field: True for field in sorted(CHECKLIST_FIELDS)},
            "production_activation": False,
        }
        (stage / "authority.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        validate_authority_structure(
            receipt,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
        )
        os.replace(stage, target)
        return read_authority(
            root_path,
            assembly_receipt=assembly_receipt,
            body_release_status=body_release_status,
            review_id=review_id,
        )
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def read_authority(
    root: str | os.PathLike[str],
    *,
    assembly_receipt: Mapping[str, Any],
    body_release_status: Mapping[str, Any],
    review_id: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    assembly = _assembly_identity(assembly_receipt)
    target = authority_dir(root_path, assembly["person_id"], assembly["person_revision"], review_id)
    path = target / "authority.json"
    if not path.is_file():
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority is unreadable") from exc
    value = validate_authority_structure(
        value,
        assembly_receipt=assembly_receipt,
        body_release_status=body_release_status,
    )
    if value["review_id"] != review_id:
        raise HandsFeetNailsAuthorityError("hands/feet/nails authority path/review id mismatch")
    try:
        source = read_source_capture(
            root_path,
            assembly["person_id"],
            body_revision=assembly["body_revision"],
            capture_id=str(value["source_capture_id"]),
        )
    except HandsFeetNailsSourceCaptureError as exc:
        raise HandsFeetNailsAuthorityError(f"source capture authority failed during readback: {exc}") from exc
    if str(source.get("source_manifest_sha256") or "").lower() != str(value["source_manifest_sha256"]).lower():
        raise HandsFeetNailsAuthorityError("reviewed source manifest lineage no longer matches the canonical source capture")
    canonical_source_manifest = capture_dir(
        root_path,
        assembly["person_id"],
        assembly["body_revision"],
        str(value["source_capture_id"]),
    ) / "source-capture.json"
    if _sha256_file(canonical_source_manifest) != value["source_capture_sha256"]:
        raise HandsFeetNailsAuthorityError("source capture manifest bytes changed after human review")
    frozen_source = target / "source"
    if _sha256_file(frozen_source / "source-capture.json") != value["source_capture_sha256"]:
        raise HandsFeetNailsAuthorityError("frozen source capture manifest no longer matches reviewed bytes")
    for region in REQUIRED_REGIONS:
        filename = region.replace("_", "-") + ".png"
        expected = str(value["source_region_sha256"][region])
        if _sha256_file(frozen_source / filename) != expected or _sha256_file(canonical_source_manifest.parent / filename) != expected:
            raise HandsFeetNailsAuthorityError(f"{region} source closeup bytes changed after human review")
        if str(source["regions"][region]["image_sha256"]) != expected:
            raise HandsFeetNailsAuthorityError(f"{region} source capture receipt no longer matches reviewed bytes")

    render = validate_render_manifest(
        target / "render" / "hands-feet-nails-render-set.json",
        body_id=assembly["body_id"],
        package_sha256=str(value["body_package_sha256"]),
    )
    if render["manifest_sha256"] != value["render_manifest_sha256"] or render["region_sha256"] != dict(value["render_region_sha256"]):
        raise HandsFeetNailsAuthorityError("frozen hands/feet/nails render evidence no longer matches reviewed bytes")
    return value
