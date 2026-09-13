from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.sith_pbr_material import PNG_SIGNATURE, PbrMaterialError, _read_glb, _write_glb
from .fidelity_ab import FidelityAbError, _avatar_fingerprints, compare_packages
from .hands_feet_nails_detail_texture import (
    MAX_CHANNEL_DELTA_LEVELS,
    METHOD,
    MIN_REGION_CHANGED_PIXELS,
    MIN_REGION_MASK_PIXELS,
    REGION_METRIC_FIELDS,
    HandsFeetNailsDetailTextureError,
    apply_source_details,
)
from .hands_feet_nails_landmark_evidence import (
    HandsFeetNailsLandmarkEvidenceError,
    evidence_path as landmark_evidence_path,
    validate_landmark_evidence,
)
from .hands_feet_nails_source_capture import (
    REQUIRED_REGIONS,
    HandsFeetNailsSourceCaptureError,
    capture_dir,
    read_source_capture,
)
from .hands_feet_nails_uv_domain_evidence import (
    HandsFeetNailsUvDomainEvidenceError,
    validate_uv_domain_evidence,
)
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-hands-feet-nails-detail-candidate"
VERSION = 1
POLICY_REVISION = "bodyrig-hands-feet-nails-detail-candidate-v1"
EMBEDDED_FORMAT = "bodyrig-hands-feet-nails-detail-application"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_RE = re.compile(r"^body-r[0-9]{4}$")
CAPTURE_RE = re.compile(r"^hfncap-[0-9a-f]{32}$")
CANDIDATE_RE = re.compile(r"^hfncand-[0-9a-f]{32}$")

TOP_FIELDS = {
    "format", "version", "policy_revision", "candidate_id", "person_id", "body_revision",
    "capture_id", "body_id", "bodyrig_revision", "method", "source_package_sha256",
    "candidate_package_sha256", "source_avatar_sha256", "candidate_avatar_sha256",
    "source_capture_sha256", "landmark_evidence_sha256", "uv_evidence_sha256",
    "source_basecolor_sha256", "candidate_basecolor_sha256", "max_channel_delta_levels",
    "changed_pixel_count", "changed_pixel_fraction", "regions", "geometry_surface_sha256",
    "skinned_surface_sha256", "rig_sha256", "uv_material_mapping_sha256",
    "clean_appearance_ab", "source_grounded", "generative", "package_application_authority",
    "geometry_modified", "texture_modified", "human_review_required", "production_activation",
}
EMBEDDED_FIELDS = {
    "format", "version", "policyRevision", "candidateId", "personId", "bodyRevision",
    "captureId", "bodyrigRevision", "method", "sourcePackageSha256", "sourceCaptureSha256",
    "landmarkEvidenceSha256", "uvEvidenceSha256", "sourceBaseColorSha256",
    "candidateBaseColorSha256", "maxChannelDeltaLevels", "regions", "geometrySurfaceSha256",
    "skinnedSurfaceSha256", "rigSha256", "uvMaterialMappingSha256", "sourceGrounded",
    "generative", "packageApplicationAuthority", "geometryModified", "textureModified",
    "humanReviewRequired", "productionActivation",
}


class HandsFeetNailsDetailCandidateError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise HandsFeetNailsDetailCandidateError(f"required HFN detail input is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise HandsFeetNailsDetailCandidateError(f"{label} is not a canonical SHA-256")
    return text


def _revision(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise HandsFeetNailsDetailCandidateError("HFN detail BodyRig revision is not canonical")
    return text


def _identity(person_id: str, body_revision: str, capture_id: str) -> tuple[str, str, str]:
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    capture = str(capture_id or "").strip().lower()
    if not PERSON_RE.fullmatch(person) or not BODY_RE.fullmatch(body) or not CAPTURE_RE.fullmatch(capture):
        raise HandsFeetNailsDetailCandidateError("HFN detail identity is not canonical")
    return person, body, capture


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _candidate_id(
    *,
    person_id: str,
    body_revision: str,
    capture_id: str,
    bodyrig_revision: str,
    source_package_sha256: str,
    uv_evidence_sha256: str,
) -> str:
    payload = {
        "person_id": person_id,
        "body_revision": body_revision,
        "capture_id": capture_id,
        "bodyrig_revision": bodyrig_revision,
        "source_package_sha256": source_package_sha256,
        "uv_evidence_sha256": uv_evidence_sha256,
        "method": METHOD,
    }
    return "hfncand-" + hashlib.sha256(_canonical_json(payload)).hexdigest()[:32]


def candidate_paths(
    root: str | os.PathLike[str],
    person_id: str,
    body_revision: str,
    capture_id: str,
    candidate_id: str,
) -> tuple[Path, Path]:
    person, body, capture = _identity(person_id, body_revision, capture_id)
    candidate = str(candidate_id or "").strip().lower()
    if not CANDIDATE_RE.fullmatch(candidate):
        raise HandsFeetNailsDetailCandidateError("HFN detail candidate id is not canonical")
    base = (
        Path(root).expanduser().resolve()
        / "hands-feet-nails-detail-candidates"
        / person
        / body
        / capture
        / candidate
    )
    return base.with_suffix(".mrbody"), base.with_suffix(".json")


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsDetailCandidateError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise HandsFeetNailsDetailCandidateError(f"{label} must be a JSON object")
    return value


def _load_authorities(
    root: Path,
    *,
    person_id: str,
    body_revision: str,
    capture_id: str,
    uv_evidence_file: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str, str]:
    try:
        source = read_source_capture(
            root,
            person_id,
            body_revision=body_revision,
            capture_id=capture_id,
        )
    except HandsFeetNailsSourceCaptureError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    source_manifest = capture_dir(root, person_id, body_revision, capture_id) / "source-capture.json"
    source_capture_sha = _sha256_file(source_manifest)

    uv_raw = _read_json(uv_evidence_file, label="HFN UV-domain evidence")
    try:
        uv = validate_uv_domain_evidence(uv_raw)
    except HandsFeetNailsUvDomainEvidenceError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    if (uv["person_id"], uv["body_revision"], uv["capture_id"]) != (person_id, body_revision, capture_id):
        raise HandsFeetNailsDetailCandidateError(
            "HFN UV-domain evidence belongs to a different Person/body/capture"
        )
    uv_sha = _sha256_file(uv_evidence_file)

    landmark_path = landmark_evidence_path(
        root,
        person_id,
        body_revision,
        capture_id,
        uv["landmark_evidence_bodyrig_revision"],
    )
    landmark_raw = _read_json(landmark_path, label="HFN landmark evidence")
    try:
        landmark = validate_landmark_evidence(landmark_raw)
    except HandsFeetNailsLandmarkEvidenceError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    landmark_sha = _sha256_file(landmark_path)
    if landmark_sha != uv["landmark_evidence_sha256"]:
        raise HandsFeetNailsDetailCandidateError(
            "HFN UV-domain evidence no longer matches exact landmark evidence bytes"
        )
    if landmark.get("all_regions_application_ready") is not True:
        raise HandsFeetNailsDetailCandidateError(
            "HFN detail application fails closed until all landmark regions are ready"
        )
    if landmark.get("source_capture_sha256") != source_capture_sha:
        raise HandsFeetNailsDetailCandidateError(
            "HFN landmark evidence no longer matches exact source-capture manifest"
        )
    if (landmark["person_id"], landmark["body_revision"], landmark["capture_id"]) != (
        person_id,
        body_revision,
        capture_id,
    ):
        raise HandsFeetNailsDetailCandidateError("HFN landmark evidence identity changed")
    for region in REQUIRED_REGIONS:
        if landmark["regions"][region]["closeup_image_sha256"] != source["regions"][region]["image_sha256"]:
            raise HandsFeetNailsDetailCandidateError(
                f"{region} landmark evidence no longer matches exact source closeup bytes"
            )
    return source, landmark, uv, source_capture_sha, landmark_sha, uv_sha


def _read_package(path: Path) -> tuple[bytes, str, str]:
    try:
        validated = validate_package(path)
        with zipfile.ZipFile(path, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HandsFeetNailsDetailCandidateError("HFN source package is invalid") from exc
    return avatar, str(validated.manifest["id"]), _sha256_file(path)


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise HandsFeetNailsDetailCandidateError(f"HFN detail requires canonical glTF {name}")
    return value


def _buffer_view_bytes(
    document: Mapping[str, Any],
    binary: bytes,
    index: Any,
    *,
    label: str,
) -> bytes:
    if isinstance(index, bool) or not isinstance(index, int):
        raise HandsFeetNailsDetailCandidateError(f"{label} bufferView index is invalid")
    views = _array(document, "bufferViews")
    if not 0 <= index < len(views) or not isinstance(views[index], dict):
        raise HandsFeetNailsDetailCandidateError(f"{label} bufferView is missing")
    view = views[index]
    if view.get("buffer", 0) != 0:
        raise HandsFeetNailsDetailCandidateError(f"{label} must use embedded buffer 0")
    offset = view.get("byteOffset", 0)
    length = view.get("byteLength")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (offset, length)):
        raise HandsFeetNailsDetailCandidateError(f"{label} bufferView bounds are invalid")
    if offset + length > len(binary):
        raise HandsFeetNailsDetailCandidateError(f"{label} bufferView exceeds GLB binary bytes")
    return binary[offset : offset + length]


def _active_basecolor(
    document: Mapping[str, Any],
    binary: bytes,
    *,
    reject_existing_application: bool,
) -> tuple[bytes, dict[str, Any], list[Any], dict[str, Any], dict[str, Any]]:
    images = _array(document, "images")
    textures = _array(document, "textures")
    materials = _array(document, "materials")
    views = _array(document, "bufferViews")
    if not images or not isinstance(images[0], dict):
        raise HandsFeetNailsDetailCandidateError("HFN detail requires embedded base-color image 0")
    if not textures or not isinstance(textures[0], dict) or textures[0].get("source") != 0:
        raise HandsFeetNailsDetailCandidateError("HFN detail requires texture 0 to reference image 0")
    if not materials or not isinstance(materials[0], dict):
        raise HandsFeetNailsDetailCandidateError("HFN detail requires canonical body material 0")
    pbr = materials[0].get("pbrMetallicRoughness")
    if not isinstance(pbr, dict) or pbr.get("baseColorTexture") != {"index": 0}:
        raise HandsFeetNailsDetailCandidateError("HFN detail requires canonical body baseColorTexture 0")
    image = images[0]
    raw = _buffer_view_bytes(document, binary, image.get("bufferView"), label="active base color")
    if not raw.startswith(PNG_SIGNATURE):
        raise HandsFeetNailsDetailCandidateError("HFN active base color is not PNG")
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise HandsFeetNailsDetailCandidateError("HFN detail requires BodyRig VRM metadata")
    if reject_existing_application and "handsFeetNailsDetailApplication" in bodyrig:
        raise HandsFeetNailsDetailCandidateError("HFN detail is already applied to this avatar")
    appearance = bodyrig.get("appearanceTransfer")
    if not isinstance(appearance, dict):
        raise HandsFeetNailsDetailCandidateError("HFN detail requires promoted appearanceTransfer authority")
    if _sha(appearance.get("activeBaseColorSha256"), label="active base-color SHA-256") != _sha256_bytes(raw):
        raise HandsFeetNailsDetailCandidateError(
            "active base-color bytes no longer match appearanceTransfer authority"
        )
    return raw, image, views, bodyrig, appearance


def _embedded_receipt(
    *,
    candidate_id: str,
    person_id: str,
    body_revision: str,
    capture_id: str,
    bodyrig_revision: str,
    source_package_sha256: str,
    source_capture_sha256: str,
    landmark_evidence_sha256: str,
    uv_evidence_sha256: str,
    source_basecolor_sha256: str,
    candidate_basecolor_sha256: str,
    regions: Mapping[str, Any],
    fingerprints: Mapping[str, Any],
) -> dict[str, Any]:
    value = {
        "format": EMBEDDED_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "candidateId": candidate_id,
        "personId": person_id,
        "bodyRevision": body_revision,
        "captureId": capture_id,
        "bodyrigRevision": bodyrig_revision,
        "method": METHOD,
        "sourcePackageSha256": source_package_sha256,
        "sourceCaptureSha256": source_capture_sha256,
        "landmarkEvidenceSha256": landmark_evidence_sha256,
        "uvEvidenceSha256": uv_evidence_sha256,
        "sourceBaseColorSha256": source_basecolor_sha256,
        "candidateBaseColorSha256": candidate_basecolor_sha256,
        "maxChannelDeltaLevels": MAX_CHANNEL_DELTA_LEVELS,
        "regions": {key: dict(item) for key, item in regions.items()},
        "geometrySurfaceSha256": fingerprints["geometry_surface_sha256"],
        "skinnedSurfaceSha256": fingerprints["skinned_surface_sha256"],
        "rigSha256": fingerprints["rig_sha256"],
        "uvMaterialMappingSha256": fingerprints["uv_material_mapping_sha256"],
        "sourceGrounded": True,
        "generative": False,
        "packageApplicationAuthority": True,
        "geometryModified": False,
        "textureModified": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    if set(value) != EMBEDDED_FIELDS:
        raise HandsFeetNailsDetailCandidateError("internal HFN embedded receipt fields are not canonical")
    return value


def _embedded_receipt_matches(actual: Any, expected: Mapping[str, Any]) -> bool:
    if not isinstance(actual, Mapping) or set(actual) != EMBEDDED_FIELDS:
        return False
    version = actual.get("version")
    if isinstance(version, bool) or version != VERSION:
        return False
    for field in ("sourceGrounded", "packageApplicationAuthority", "textureModified", "humanReviewRequired"):
        if actual.get(field) is not True:
            return False
    for field in ("generative", "geometryModified", "productionActivation"):
        if actual.get(field) is not False:
            return False
    return dict(actual) == dict(expected)


def _append_basecolor(
    document: dict[str, Any],
    binary: bytes,
    *,
    candidate_png: bytes,
    embedded: Mapping[str, Any],
) -> bytes:
    _source, image, views, bodyrig, appearance = _active_basecolor(
        document,
        binary,
        reject_existing_application=True,
    )
    mutable = bytearray(binary)
    while len(mutable) % 4:
        mutable.append(0)
    offset = len(mutable)
    mutable.extend(candidate_png)
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(candidate_png)})
    image["bufferView"] = len(views) - 1
    image["mimeType"] = "image/png"
    image["name"] = "BodyRigHandsFeetNailsDetailBaseColor"
    appearance["activeBaseColorSha256"] = _sha256_bytes(candidate_png)
    bodyrig["handsFeetNailsDetailApplication"] = dict(embedded)
    buffers = _array(document, "buffers")
    if len(buffers) != 1 or not isinstance(buffers[0], dict):
        raise HandsFeetNailsDetailCandidateError("HFN GLB buffer contract is invalid")
    buffers[0]["byteLength"] = len(mutable)
    try:
        return _write_glb(document, bytes(mutable))
    except PbrMaterialError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc


def _rewrite_package(source: Path, destination: Path, *, avatar_vrm: bytes) -> None:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            order = [item.filename for item in archive.infolist()]
            payload = {name: archive.read(name) for name in order}
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HandsFeetNailsDetailCandidateError("could not read validated HFN source package") from exc
    payload["avatar.vrm"] = avatar_vrm
    checksum_names = set(order) - {"manifest.json", "checksums.json"}
    payload["checksums.json"] = json.dumps(
        {name: _sha256_bytes(payload[name]) for name in checksum_names},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in order:
                archive.writestr(name, payload[name])
    except FileExistsError as exc:
        raise HandsFeetNailsDetailCandidateError(
            f"refusing to overwrite existing HFN detail candidate: {destination}"
        ) from exc
    except OSError as exc:
        raise HandsFeetNailsDetailCandidateError("could not write HFN detail candidate package") from exc


def validate_candidate_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise HandsFeetNailsDetailCandidateError("HFN detail candidate receipt fields are not canonical")
    version = value.get("version")
    if (
        value.get("format") != FORMAT
        or isinstance(version, bool)
        or version != VERSION
        or value.get("policy_revision") != POLICY_REVISION
        or value.get("method") != METHOD
    ):
        raise HandsFeetNailsDetailCandidateError(
            "HFN detail candidate format/version/policy/method mismatch"
        )
    candidate_id = str(value.get("candidate_id") or "").lower()
    person, body, capture = _identity(
        str(value.get("person_id") or ""),
        str(value.get("body_revision") or ""),
        str(value.get("capture_id") or ""),
    )
    if not CANDIDATE_RE.fullmatch(candidate_id):
        raise HandsFeetNailsDetailCandidateError("HFN detail candidate id is invalid")
    revision = _revision(value.get("bodyrig_revision"))
    body_id = str(value.get("body_id") or "")
    if not body_id:
        raise HandsFeetNailsDetailCandidateError("HFN detail candidate body id is missing")
    for field in (
        "source_package_sha256", "candidate_package_sha256", "source_avatar_sha256",
        "candidate_avatar_sha256", "source_capture_sha256", "landmark_evidence_sha256",
        "uv_evidence_sha256", "source_basecolor_sha256", "candidate_basecolor_sha256",
        "geometry_surface_sha256", "skinned_surface_sha256", "rig_sha256",
        "uv_material_mapping_sha256",
    ):
        _sha(value.get(field), label=field.replace("_", " "))
    changed = value.get("changed_pixel_count")
    fraction = value.get("changed_pixel_fraction")
    if value.get("max_channel_delta_levels") != MAX_CHANNEL_DELTA_LEVELS:
        raise HandsFeetNailsDetailCandidateError("HFN detail channel-delta cap changed")
    if isinstance(changed, bool) or not isinstance(changed, int) or changed < 1:
        raise HandsFeetNailsDetailCandidateError("HFN detail changed-pixel count is invalid")
    if (
        isinstance(fraction, bool)
        or not isinstance(fraction, (int, float))
        or not 0.0 < float(fraction) <= 1.0
    ):
        raise HandsFeetNailsDetailCandidateError("HFN detail changed-pixel fraction is invalid")
    regions = value.get("regions")
    if not isinstance(regions, Mapping) or set(regions) != set(REQUIRED_REGIONS):
        raise HandsFeetNailsDetailCandidateError("HFN detail region set is invalid")
    region_changed = 0
    normalized_regions: dict[str, dict[str, Any]] = {}
    for region in REQUIRED_REGIONS:
        item = regions.get(region)
        if not isinstance(item, Mapping) or set(item) != REGION_METRIC_FIELDS:
            raise HandsFeetNailsDetailCandidateError(f"{region} HFN detail metrics are invalid")
        _sha(item.get("source_image_sha256"), label=f"{region} source image SHA-256")
        _sha(item.get("uv_set_sha256"), label=f"{region} UV-set SHA-256")
        mask_count = item.get("mask_pixel_count")
        changed_count = item.get("changed_pixel_count")
        max_delta = item.get("max_observed_channel_delta_levels")
        if (
            isinstance(mask_count, bool)
            or not isinstance(mask_count, int)
            or mask_count < MIN_REGION_MASK_PIXELS
            or isinstance(changed_count, bool)
            or not isinstance(changed_count, int)
            or changed_count < MIN_REGION_CHANGED_PIXELS
            or changed_count > mask_count
            or isinstance(max_delta, bool)
            or not isinstance(max_delta, int)
            or not 1 <= max_delta <= MAX_CHANNEL_DELTA_LEVELS
        ):
            raise HandsFeetNailsDetailCandidateError(f"{region} HFN detail metrics are outside bounds")
        region_changed += changed_count
        normalized_regions[region] = dict(item)
    if region_changed != changed:
        raise HandsFeetNailsDetailCandidateError("HFN detail changed-pixel receipt is inconsistent")
    if (
        value.get("clean_appearance_ab") is not True
        or value.get("source_grounded") is not True
        or value.get("generative") is not False
        or value.get("package_application_authority") is not True
        or value.get("geometry_modified") is not False
        or value.get("texture_modified") is not True
        or value.get("human_review_required") is not True
        or value.get("production_activation") is not False
    ):
        raise HandsFeetNailsDetailCandidateError(
            "HFN detail candidate crossed its application/review/production boundary"
        )
    if value["source_package_sha256"] == value["candidate_package_sha256"]:
        raise HandsFeetNailsDetailCandidateError("HFN detail candidate did not change package bytes")
    if value["source_basecolor_sha256"] == value["candidate_basecolor_sha256"]:
        raise HandsFeetNailsDetailCandidateError(
            "HFN detail candidate did not change active base-color bytes"
        )
    return {
        **dict(value),
        "candidate_id": candidate_id,
        "person_id": person,
        "body_revision": body,
        "capture_id": capture,
        "bodyrig_revision": revision,
        "body_id": body_id,
        "regions": normalized_regions,
    }


def build_detail_candidate(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    capture_id: str,
    uv_evidence_path: str | os.PathLike[str],
    package_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person, body, capture = _identity(person_id, body_revision, capture_id)
    revision = _revision(bodyrig_revision)
    uv_path = Path(uv_evidence_path).expanduser().resolve()
    source_package = Path(package_path).expanduser().resolve()
    source, _landmark, uv, source_capture_sha, landmark_sha, uv_sha = _load_authorities(
        root_path,
        person_id=person,
        body_revision=body,
        capture_id=capture,
        uv_evidence_file=uv_path,
    )
    source_avatar, body_id, source_package_sha = _read_package(source_package)
    if uv["body_id"] != body_id or uv["package_sha256"] != source_package_sha:
        raise HandsFeetNailsDetailCandidateError(
            "HFN UV-domain evidence belongs to different body/package bytes"
        )
    try:
        document, binary = _read_glb(source_avatar)
    except PbrMaterialError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    source_basecolor, _image, _views, _bodyrig, _appearance = _active_basecolor(
        document,
        binary,
        reject_existing_application=True,
    )
    source_basecolor_sha = _sha256_bytes(source_basecolor)
    try:
        before_fp = _avatar_fingerprints(source_avatar)
    except FidelityAbError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    try:
        candidate_png, region_metrics, changed_pixels, changed_fraction = apply_source_details(
            document,
            binary,
            basecolor_png=source_basecolor,
            uv_evidence=uv,
            source_capture=source,
            source_root=root_path,
        )
    except HandsFeetNailsDetailTextureError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    candidate_basecolor_sha = _sha256_bytes(candidate_png)
    if candidate_basecolor_sha == source_basecolor_sha:
        raise HandsFeetNailsDetailCandidateError(
            "HFN source detail produced unchanged base-color bytes"
        )
    candidate_id = _candidate_id(
        person_id=person,
        body_revision=body,
        capture_id=capture,
        bodyrig_revision=revision,
        source_package_sha256=source_package_sha,
        uv_evidence_sha256=uv_sha,
    )
    package_out, receipt_out = candidate_paths(root_path, person, body, capture, candidate_id)
    if package_out.exists() or receipt_out.exists():
        raise HandsFeetNailsDetailCandidateError(
            "refusing to overwrite existing HFN detail candidate authority"
        )
    embedded = _embedded_receipt(
        candidate_id=candidate_id,
        person_id=person,
        body_revision=body,
        capture_id=capture,
        bodyrig_revision=revision,
        source_package_sha256=source_package_sha,
        source_capture_sha256=source_capture_sha,
        landmark_evidence_sha256=landmark_sha,
        uv_evidence_sha256=uv_sha,
        source_basecolor_sha256=source_basecolor_sha,
        candidate_basecolor_sha256=candidate_basecolor_sha,
        regions=region_metrics,
        fingerprints=before_fp,
    )
    candidate_avatar = _append_basecolor(
        document,
        binary,
        candidate_png=candidate_png,
        embedded=embedded,
    )
    try:
        after_fp = _avatar_fingerprints(candidate_avatar)
    except FidelityAbError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    for field in (
        "triangle_count", "geometry_surface_sha256", "skinned_surface_sha256",
        "rig_sha256", "uv_material_mapping_sha256",
    ):
        if after_fp[field] != before_fp[field]:
            raise HandsFeetNailsDetailCandidateError(
                f"HFN detail changed protected anatomy/rig authority: {field}"
            )
    if after_fp["appearance_sha256"] == before_fp["appearance_sha256"]:
        raise HandsFeetNailsDetailCandidateError("HFN detail did not change appearance fingerprint")

    package_created = False
    receipt_created = False
    try:
        _rewrite_package(source_package, package_out, avatar_vrm=candidate_avatar)
        package_created = True
        try:
            validated = validate_package(package_out)
            ab = compare_packages(source_package, package_out)
        except (MRBodyError, FidelityAbError) as exc:
            raise HandsFeetNailsDetailCandidateError(
                f"HFN detail candidate package validation failed: {exc}"
            ) from exc
        if str(validated.manifest["id"]) != body_id:
            raise HandsFeetNailsDetailCandidateError("HFN detail candidate changed canonical body id")
        if ab["invariants"].get("clean_appearance_ab") is not True:
            raise HandsFeetNailsDetailCandidateError(
                "HFN detail candidate is not a clean appearance-only A/B"
            )
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "policy_revision": POLICY_REVISION,
            "candidate_id": candidate_id,
            "person_id": person,
            "body_revision": body,
            "capture_id": capture,
            "body_id": body_id,
            "bodyrig_revision": revision,
            "method": METHOD,
            "source_package_sha256": source_package_sha,
            "candidate_package_sha256": _sha256_file(package_out),
            "source_avatar_sha256": _sha256_bytes(source_avatar),
            "candidate_avatar_sha256": _sha256_bytes(candidate_avatar),
            "source_capture_sha256": source_capture_sha,
            "landmark_evidence_sha256": landmark_sha,
            "uv_evidence_sha256": uv_sha,
            "source_basecolor_sha256": source_basecolor_sha,
            "candidate_basecolor_sha256": candidate_basecolor_sha,
            "max_channel_delta_levels": MAX_CHANNEL_DELTA_LEVELS,
            "changed_pixel_count": changed_pixels,
            "changed_pixel_fraction": round(changed_fraction, 8),
            "regions": region_metrics,
            "geometry_surface_sha256": before_fp["geometry_surface_sha256"],
            "skinned_surface_sha256": before_fp["skinned_surface_sha256"],
            "rig_sha256": before_fp["rig_sha256"],
            "uv_material_mapping_sha256": before_fp["uv_material_mapping_sha256"],
            "clean_appearance_ab": True,
            "source_grounded": True,
            "generative": False,
            "package_application_authority": True,
            "geometry_modified": False,
            "texture_modified": True,
            "human_review_required": True,
            "production_activation": False,
        }
        validated_receipt = validate_candidate_receipt(receipt)
        receipt_out.parent.mkdir(parents=True, exist_ok=True)
        with receipt_out.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps(
                    validated_receipt,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                ) + "\n"
            )
        receipt_created = True
        return {
            **validated_receipt,
            "package_path": str(package_out),
            "receipt_path": str(receipt_out),
        }
    except Exception:
        if receipt_created:
            receipt_out.unlink(missing_ok=True)
        if package_created:
            package_out.unlink(missing_ok=True)
        raise


def read_detail_candidate(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    capture_id: str,
    candidate_id: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person, body, capture = _identity(person_id, body_revision, capture_id)
    candidate = str(candidate_id or "").strip().lower()
    package_path, receipt_path = candidate_paths(
        root_path,
        person,
        body,
        capture,
        candidate,
    )
    if not package_path.is_file() or not receipt_path.is_file():
        raise HandsFeetNailsDetailCandidateError("HFN detail candidate package/receipt is missing")
    receipt = validate_candidate_receipt(
        _read_json(receipt_path, label="HFN detail candidate receipt")
    )
    if (
        receipt["person_id"], receipt["body_revision"], receipt["capture_id"], receipt["candidate_id"]
    ) != (person, body, capture, candidate):
        raise HandsFeetNailsDetailCandidateError("HFN detail candidate path identity mismatch")
    if _sha256_file(package_path) != receipt["candidate_package_sha256"]:
        raise HandsFeetNailsDetailCandidateError("HFN detail candidate package bytes changed")
    avatar, body_id, _package_sha = _read_package(package_path)
    if body_id != receipt["body_id"] or _sha256_bytes(avatar) != receipt["candidate_avatar_sha256"]:
        raise HandsFeetNailsDetailCandidateError(
            "HFN detail candidate avatar/body identity changed"
        )
    try:
        document, binary = _read_glb(avatar)
    except PbrMaterialError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    basecolor, _image, _views, bodyrig, _appearance = _active_basecolor(
        document,
        binary,
        reject_existing_application=False,
    )
    if _sha256_bytes(basecolor) != receipt["candidate_basecolor_sha256"]:
        raise HandsFeetNailsDetailCandidateError(
            "HFN detail candidate active base-color bytes changed"
        )
    try:
        fingerprints = _avatar_fingerprints(avatar)
    except FidelityAbError as exc:
        raise HandsFeetNailsDetailCandidateError(str(exc)) from exc
    for field in (
        "geometry_surface_sha256", "skinned_surface_sha256", "rig_sha256",
        "uv_material_mapping_sha256",
    ):
        if fingerprints[field] != receipt[field]:
            raise HandsFeetNailsDetailCandidateError(
                f"HFN detail candidate protected fingerprint changed: {field}"
            )
    expected_embedded = _embedded_receipt(
        candidate_id=receipt["candidate_id"],
        person_id=receipt["person_id"],
        body_revision=receipt["body_revision"],
        capture_id=receipt["capture_id"],
        bodyrig_revision=receipt["bodyrig_revision"],
        source_package_sha256=receipt["source_package_sha256"],
        source_capture_sha256=receipt["source_capture_sha256"],
        landmark_evidence_sha256=receipt["landmark_evidence_sha256"],
        uv_evidence_sha256=receipt["uv_evidence_sha256"],
        source_basecolor_sha256=receipt["source_basecolor_sha256"],
        candidate_basecolor_sha256=receipt["candidate_basecolor_sha256"],
        regions=receipt["regions"],
        fingerprints={
            "geometry_surface_sha256": receipt["geometry_surface_sha256"],
            "skinned_surface_sha256": receipt["skinned_surface_sha256"],
            "rig_sha256": receipt["rig_sha256"],
            "uv_material_mapping_sha256": receipt["uv_material_mapping_sha256"],
        },
    )
    if not _embedded_receipt_matches(
        bodyrig.get("handsFeetNailsDetailApplication"),
        expected_embedded,
    ):
        raise HandsFeetNailsDetailCandidateError(
            "embedded HFN detail authority is stale or tampered"
        )
    return {
        **receipt,
        "package_path": str(package_path),
        "receipt_path": str(receipt_path),
    }
