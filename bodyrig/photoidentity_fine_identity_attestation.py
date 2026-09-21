from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

FORMAT = "bodyrig-photoidentity-fine-identity-attestation"
VERSION = 1
POLICY_REVISION = "photoidentity-fine-identity-photoidentical-v1"
PRIVATE_FORMAT = "bodyrig-photoidentity-private-fine-identity-review"
PRIVATE_VERSION = 1
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
DETAIL_QUALITY_THRESHOLD = 0.80
MARKER_INVENTORY_FORMAT = "bodyrig-photoidentity-distinctive-marker-inventory"
MARKER_INVENTORY_VERSION = 1
REQUIRED_MARKER_REVIEW_REGIONS = {
    "face_head",
    "chest_breast",
    "abdomen_waist",
    "back",
    "left_arm",
    "right_arm",
    "left_hand",
    "right_hand",
    "left_leg",
    "right_leg",
    "left_foot",
    "right_foot",
    "intimate_region",
}
DISTINCTIVE_MARKER_TYPES = {
    "scar",
    "mole",
    "birthmark",
    "tattoo",
    "freckle_cluster",
    "pigmentation",
    "piercing_mark",
    "other_visible_marker",
}

REQUIRED_DOMAINS = {
    "oral_teeth_detail": 2,
    "chest_breast_shape_detail": 2,
    "nipple_areola_detail": 2,
    "intimate_anatomy_detail": 2,
    "distinctive_markers_detail": 2,
}

CONFIRMATION_FIELDS = {
    "oral_teeth_detail": "confirm_oral_teeth_photoidentity",
    "chest_breast_shape_detail": "confirm_chest_breast_shape_photoidentity",
    "nipple_areola_detail": "confirm_nipple_areola_photoidentity",
    "intimate_anatomy_detail": "confirm_intimate_anatomy_photoidentity",
    "distinctive_markers_detail": "confirm_distinctive_markers_photoidentity",
}

PRIVATE_TOP_FIELDS = {
    "format",
    "version",
    "performer_id",
    "bodyrig_revision",
    "anatomy_observation_evidence_sha256",
    "anatomy_sufficiency_report_sha256",
    "marker_inventory_path",
    "marker_inventory_sha256",
    "entries",
}

PRIVATE_ENTRY_FIELDS = {
    "reference",
    "domain",
    "scene_id",
    "region",
    "source_ordinal",
    "source_media_path",
    "source_media_sha256",
    "review_image_path",
    "review_image_sha256",
    "source_quality",
}

PUBLIC_TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "performer_id",
    "bodyrig_revision",
    "anatomy_observation_evidence_sha256",
    "anatomy_sufficiency_report_sha256",
    "attested_domains",
    "selected_evidence",
    "marker_inventory_sha256",
    "reviewed_by",
    "quality_note",
    *CONFIRMATION_FIELDS.values(),
    "reviewed_utc",
    "operator_supplied",
    "source_grounded",
    "photoidentical_identity_detail_required",
    "generic_guessing_permitted",
    "reconstruction_permitted",
    "production_activation",
}

PUBLIC_ENTRY_FIELDS = {
    "reference",
    "domain",
    "scene_id",
    "region",
    "source_ordinal",
    "source_media_sha256",
    "review_image_sha256",
    "source_quality",
}


class PhotoIdentityFineIdentityAttestationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotoIdentityFineIdentityAttestationError(f"fine-identity evidence file is missing or symlinked: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: object, *, label: str) -> str:
    digest = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(digest):
        raise PhotoIdentityFineIdentityAttestationError(f"{label} is not a canonical SHA-256")
    return digest


def _quality(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentityFineIdentityAttestationError("fine-identity source quality is not numeric")
    quality = float(value)
    if not math.isfinite(quality) or not DETAIL_QUALITY_THRESHOLD <= quality <= 1.0:
        raise PhotoIdentityFineIdentityAttestationError(
            f"fine-identity source quality must be {DETAIL_QUALITY_THRESHOLD:.2f}..1.00"
        )
    return round(quality, 4)


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityFineIdentityAttestationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityFineIdentityAttestationError(f"{label} must be a JSON object")
    return value


def _validate_marker_inventory(path: Path, *, allowed_source_refs: set[str]) -> dict[str, Any]:
    value = _read_json(path, label="Private distinctive-marker inventory")
    required = {
        "format",
        "version",
        "reviewed_regions",
        "markers",
        "complete_body_marker_review",
        "generic_guessing_permitted",
    }
    if set(value) != required:
        raise PhotoIdentityFineIdentityAttestationError("distinctive-marker inventory fields must match v1 exactly")
    if (
        value.get("format") != MARKER_INVENTORY_FORMAT
        or value.get("version") != MARKER_INVENTORY_VERSION
        or value.get("complete_body_marker_review") is not True
        or value.get("generic_guessing_permitted") is not False
    ):
        raise PhotoIdentityFineIdentityAttestationError("distinctive-marker inventory authority boundary is invalid")
    reviewed_regions = value.get("reviewed_regions")
    if not isinstance(reviewed_regions, list) or set(str(item) for item in reviewed_regions) != REQUIRED_MARKER_REVIEW_REGIONS:
        raise PhotoIdentityFineIdentityAttestationError("distinctive-marker inventory lacks complete body-region review")
    markers = value.get("markers")
    if not isinstance(markers, list):
        raise PhotoIdentityFineIdentityAttestationError("distinctive-marker inventory markers must be a list")
    seen: set[str] = set()
    for marker in markers:
        if not isinstance(marker, Mapping) or set(marker) != {"marker_id", "kind", "region", "laterality", "source_references"}:
            raise PhotoIdentityFineIdentityAttestationError("distinctive-marker inventory marker fields are invalid")
        marker_id = str(marker.get("marker_id") or "").strip()
        kind = str(marker.get("kind") or "").strip()
        region = str(marker.get("region") or "").strip()
        laterality = str(marker.get("laterality") or "").strip()
        refs = marker.get("source_references")
        if not marker_id or marker_id in seen or kind not in DISTINCTIVE_MARKER_TYPES or not region or not laterality:
            raise PhotoIdentityFineIdentityAttestationError("distinctive-marker inventory marker identity is invalid")
        if not isinstance(refs, list) or not refs:
            raise PhotoIdentityFineIdentityAttestationError("distinctive marker lacks source references")
        normalized_refs = [str(item or "").strip() for item in refs]
        if any(not ref or ref not in allowed_source_refs for ref in normalized_refs):
            raise PhotoIdentityFineIdentityAttestationError("distinctive marker references evidence outside reviewed marker sources")
        seen.add(marker_id)
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityFineIdentityAttestationError(f"fine-identity attestation already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp.write_text(
            json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _canonical_private_manifest(path: Path) -> dict[str, Any]:
    manifest = _read_json(path, label="Private fine-identity review manifest")
    if set(manifest) != PRIVATE_TOP_FIELDS:
        raise PhotoIdentityFineIdentityAttestationError("private fine-identity review manifest fields must match v1 exactly")
    if manifest.get("format") != PRIVATE_FORMAT or manifest.get("version") != PRIVATE_VERSION:
        raise PhotoIdentityFineIdentityAttestationError("private fine-identity review manifest format/version mismatch")
    performer_id = str(manifest.get("performer_id") or "").strip()
    revision = str(manifest.get("bodyrig_revision") or "").strip().lower()
    if not performer_id or not re.fullmatch(r"^[0-9a-f]{40}$", revision):
        raise PhotoIdentityFineIdentityAttestationError("private fine-identity performer/revision identity is invalid")
    _sha(manifest.get("anatomy_observation_evidence_sha256"), label="anatomy observation evidence SHA-256")
    _sha(manifest.get("anatomy_sufficiency_report_sha256"), label="anatomy sufficiency report SHA-256")

    marker_path = Path(str(manifest.get("marker_inventory_path") or "")).expanduser().resolve()
    expected_marker_sha = _sha(manifest.get("marker_inventory_sha256"), label="marker inventory SHA-256")
    if _sha256_file(marker_path) != expected_marker_sha:
        raise PhotoIdentityFineIdentityAttestationError("private distinctive-marker inventory bytes changed")

    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise PhotoIdentityFineIdentityAttestationError("private fine-identity review manifest has no evidence entries")

    seen_refs: set[str] = set()
    scene_sets: dict[str, set[str]] = {domain: set() for domain in REQUIRED_DOMAINS}
    canonical: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, Mapping) or set(raw) != PRIVATE_ENTRY_FIELDS:
            raise PhotoIdentityFineIdentityAttestationError("private fine-identity evidence entry fields must match v1 exactly")
        reference = str(raw.get("reference") or "").strip()
        domain = str(raw.get("domain") or "").strip()
        scene_id = str(raw.get("scene_id") or "").strip()
        region = str(raw.get("region") or "").strip()
        source_ordinal = raw.get("source_ordinal")
        if not reference or reference in seen_refs:
            raise PhotoIdentityFineIdentityAttestationError("fine-identity evidence reference is empty or duplicated")
        if domain not in REQUIRED_DOMAINS:
            raise PhotoIdentityFineIdentityAttestationError(f"unsupported fine-identity domain: {domain or 'empty'}")
        if not scene_id or not region:
            raise PhotoIdentityFineIdentityAttestationError("fine-identity evidence scene/region is missing")
        if isinstance(source_ordinal, bool) or not isinstance(source_ordinal, int) or source_ordinal < 1:
            raise PhotoIdentityFineIdentityAttestationError("fine-identity evidence source ordinal is invalid")

        source_path = Path(str(raw.get("source_media_path") or "")).expanduser().resolve()
        review_path = Path(str(raw.get("review_image_path") or "")).expanduser().resolve()
        expected_source_sha = _sha(raw.get("source_media_sha256"), label="source media SHA-256")
        expected_review_sha = _sha(raw.get("review_image_sha256"), label="review image SHA-256")
        if _sha256_file(source_path) != expected_source_sha:
            raise PhotoIdentityFineIdentityAttestationError(f"source media bytes changed for fine-identity ref {reference}")
        if _sha256_file(review_path) != expected_review_sha:
            raise PhotoIdentityFineIdentityAttestationError(f"review image bytes changed for fine-identity ref {reference}")
        if expected_source_sha == expected_review_sha:
            raise PhotoIdentityFineIdentityAttestationError("source media and review image SHA unexpectedly match")

        quality = _quality(raw.get("source_quality"))
        seen_refs.add(reference)
        scene_sets[domain].add(scene_id)
        canonical.append(
            {
                "reference": reference,
                "domain": domain,
                "scene_id": scene_id,
                "region": region,
                "source_ordinal": source_ordinal,
                "source_media_sha256": expected_source_sha,
                "review_image_sha256": expected_review_sha,
                "source_quality": quality,
            }
        )

    for domain, minimum in REQUIRED_DOMAINS.items():
        count = len(scene_sets[domain])
        if count < minimum:
            raise PhotoIdentityFineIdentityAttestationError(
                f"{domain} requires at least {minimum} distinct source scenes; found {count}"
            )
    marker_refs = {item["reference"] for item in canonical if item["domain"] == "distinctive_markers_detail"}
    _validate_marker_inventory(marker_path, allowed_source_refs=marker_refs)
    canonical.sort(key=lambda item: (item["domain"], item["scene_id"], item["reference"]))
    return {**manifest, "_public_entries": canonical, "_marker_inventory_path": str(marker_path)}


def validate_attestation(
    value: Mapping[str, Any],
    *,
    expected_performer_id: str | None = None,
    expected_bodyrig_revision: str | None = None,
    expected_anatomy_observation_sha256: str | None = None,
    expected_anatomy_report_sha256: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != PUBLIC_TOP_FIELDS:
        raise PhotoIdentityFineIdentityAttestationError("fine-identity attestation fields must match v1 exactly")
    if (
        value.get("format") != FORMAT
        or value.get("version") != VERSION
        or value.get("policy_revision") != POLICY_REVISION
        or value.get("operator_supplied") is not True
        or value.get("source_grounded") is not True
        or value.get("photoidentical_identity_detail_required") is not True
        or value.get("generic_guessing_permitted") is not False
        or value.get("reconstruction_permitted") is not False
        or value.get("production_activation") is not False
    ):
        raise PhotoIdentityFineIdentityAttestationError("fine-identity attestation authority boundary is invalid")

    performer_id = str(value.get("performer_id") or "").strip()
    revision = str(value.get("bodyrig_revision") or "").strip().lower()
    if expected_performer_id is not None and performer_id != str(expected_performer_id):
        raise PhotoIdentityFineIdentityAttestationError("fine-identity attestation performer mismatch")
    if expected_bodyrig_revision is not None and revision != str(expected_bodyrig_revision).lower():
        raise PhotoIdentityFineIdentityAttestationError("fine-identity attestation BodyRig revision mismatch")

    anatomy_obs_sha = _sha(value.get("anatomy_observation_evidence_sha256"), label="anatomy observation evidence SHA-256")
    anatomy_report_sha = _sha(value.get("anatomy_sufficiency_report_sha256"), label="anatomy sufficiency report SHA-256")
    if expected_anatomy_observation_sha256 is not None and anatomy_obs_sha != expected_anatomy_observation_sha256:
        raise PhotoIdentityFineIdentityAttestationError("fine-identity attestation lost anatomy observation binding")
    if expected_anatomy_report_sha256 is not None and anatomy_report_sha != expected_anatomy_report_sha256:
        raise PhotoIdentityFineIdentityAttestationError("fine-identity attestation lost anatomy report binding")

    if set(value.get("attested_domains") or []) != set(REQUIRED_DOMAINS):
        raise PhotoIdentityFineIdentityAttestationError("fine-identity attestation domain set is incomplete")
    for field in CONFIRMATION_FIELDS.values():
        if value.get(field) is not True:
            raise PhotoIdentityFineIdentityAttestationError(f"fine-identity attestation lacks explicit confirmation: {field}")

    reviewed_by = str(value.get("reviewed_by") or "").strip()
    note = str(value.get("quality_note") or "").strip()
    if not reviewed_by or len(reviewed_by) > 256:
        raise PhotoIdentityFineIdentityAttestationError("fine-identity reviewer identity is invalid")
    if len(note) < 20 or len(note) > 4000 or (note.startswith("<") and note.endswith(">")):
        raise PhotoIdentityFineIdentityAttestationError("fine-identity attestation requires a real quality note")
    _sha(value.get("marker_inventory_sha256"), label="marker inventory SHA-256")

    selected = value.get("selected_evidence")
    if not isinstance(selected, list) or not selected:
        raise PhotoIdentityFineIdentityAttestationError("fine-identity attestation has no selected evidence")
    scenes: dict[str, set[str]] = {domain: set() for domain in REQUIRED_DOMAINS}
    refs: set[str] = set()
    for item in selected:
        if not isinstance(item, Mapping) or set(item) != PUBLIC_ENTRY_FIELDS:
            raise PhotoIdentityFineIdentityAttestationError("fine-identity selected evidence entry is invalid")
        reference = str(item.get("reference") or "").strip()
        domain = str(item.get("domain") or "").strip()
        scene = str(item.get("scene_id") or "").strip()
        region = str(item.get("region") or "").strip()
        source_ordinal = item.get("source_ordinal")
        if not reference or reference in refs or domain not in REQUIRED_DOMAINS or not scene or not region:
            raise PhotoIdentityFineIdentityAttestationError("fine-identity selected evidence identity is invalid")
        _sha(item.get("source_media_sha256"), label="fine-identity source media SHA-256")
        _sha(item.get("review_image_sha256"), label="fine-identity review image SHA-256")
        _quality(item.get("source_quality"))
        refs.add(reference)
        scenes[domain].add(scene)
    for domain, minimum in REQUIRED_DOMAINS.items():
        if len(scenes[domain]) < minimum:
            raise PhotoIdentityFineIdentityAttestationError(f"fine-identity attestation lacks source coverage for {domain}")
    return dict(value)


def read_attestation(path: Path, **kwargs: Any) -> dict[str, Any]:
    return validate_attestation(_read_json(path, label="Fine-identity attestation"), **kwargs)


def record_attestation(
    *,
    private_manifest: Path,
    anatomy_observations: Path,
    anatomy_report: Path,
    reviewed_by: str,
    quality_note: str,
    confirm_oral_teeth_photoidentity: bool,
    confirm_chest_breast_shape_photoidentity: bool,
    confirm_nipple_areola_photoidentity: bool,
    confirm_intimate_anatomy_photoidentity: bool,
    confirm_distinctive_markers_photoidentity: bool,
    output: Path,
) -> dict[str, Any]:
    manifest = _canonical_private_manifest(private_manifest.expanduser().resolve())
    anatomy_observations = anatomy_observations.expanduser().resolve()
    anatomy_report = anatomy_report.expanduser().resolve()
    anatomy_obs_sha = _sha256_file(anatomy_observations)
    anatomy_report_sha = _sha256_file(anatomy_report)
    if manifest["anatomy_observation_evidence_sha256"] != anatomy_obs_sha:
        raise PhotoIdentityFineIdentityAttestationError("private fine-identity review is not bound to current anatomy observations")
    if manifest["anatomy_sufficiency_report_sha256"] != anatomy_report_sha:
        raise PhotoIdentityFineIdentityAttestationError("private fine-identity review is not bound to current anatomy report")

    confirmations = {
        "confirm_oral_teeth_photoidentity": bool(confirm_oral_teeth_photoidentity),
        "confirm_chest_breast_shape_photoidentity": bool(confirm_chest_breast_shape_photoidentity),
        "confirm_nipple_areola_photoidentity": bool(confirm_nipple_areola_photoidentity),
        "confirm_intimate_anatomy_photoidentity": bool(confirm_intimate_anatomy_photoidentity),
        "confirm_distinctive_markers_photoidentity": bool(confirm_distinctive_markers_photoidentity),
    }
    missing = [field for field, passed in confirmations.items() if not passed]
    if missing:
        raise PhotoIdentityFineIdentityAttestationError(
            "photoidentical fine-identity review is atomic; missing confirmations: " + ", ".join(missing)
        )

    reviewer = str(reviewed_by or "").strip()
    note = str(quality_note or "").strip()
    if not reviewer or len(reviewer) > 256:
        raise PhotoIdentityFineIdentityAttestationError("fine-identity reviewer identity is invalid")
    if len(note) < 20 or len(note) > 4000 or (note.startswith("<") and note.endswith(">")):
        raise PhotoIdentityFineIdentityAttestationError("fine-identity review requires a real quality note")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "performer_id": str(manifest["performer_id"]),
        "bodyrig_revision": str(manifest["bodyrig_revision"]).lower(),
        "anatomy_observation_evidence_sha256": anatomy_obs_sha,
        "anatomy_sufficiency_report_sha256": anatomy_report_sha,
        "attested_domains": sorted(REQUIRED_DOMAINS),
        "selected_evidence": list(manifest["_public_entries"]),
        "marker_inventory_sha256": str(manifest["marker_inventory_sha256"]).lower(),
        "reviewed_by": reviewer,
        "quality_note": note,
        **confirmations,
        "reviewed_utc": datetime.now(timezone.utc).isoformat(),
        "operator_supplied": True,
        "source_grounded": True,
        "photoidentical_identity_detail_required": True,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    validated = validate_attestation(
        receipt,
        expected_performer_id=str(manifest["performer_id"]),
        expected_bodyrig_revision=str(manifest["bodyrig_revision"]),
        expected_anatomy_observation_sha256=anatomy_obs_sha,
        expected_anatomy_report_sha256=anatomy_report_sha,
    )
    _write_create_only(output.expanduser().resolve(), validated)
    return validated


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record source-grounded photoidentical fine-identity anatomy attestation.")
    parser.add_argument("--private-manifest", required=True)
    parser.add_argument("--anatomy-observations", required=True)
    parser.add_argument("--anatomy-report", required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--quality-note", required=True)
    parser.add_argument("--confirm-oral-teeth-photoidentity", action="store_true")
    parser.add_argument("--confirm-chest-breast-shape-photoidentity", action="store_true")
    parser.add_argument("--confirm-nipple-areola-photoidentity", action="store_true")
    parser.add_argument("--confirm-intimate-anatomy-photoidentity", action="store_true")
    parser.add_argument("--confirm-distinctive-markers-photoidentity", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = record_attestation(
            private_manifest=Path(args.private_manifest),
            anatomy_observations=Path(args.anatomy_observations),
            anatomy_report=Path(args.anatomy_report),
            reviewed_by=args.reviewed_by,
            quality_note=args.quality_note,
            confirm_oral_teeth_photoidentity=args.confirm_oral_teeth_photoidentity,
            confirm_chest_breast_shape_photoidentity=args.confirm_chest_breast_shape_photoidentity,
            confirm_nipple_areola_photoidentity=args.confirm_nipple_areola_photoidentity,
            confirm_intimate_anatomy_photoidentity=args.confirm_intimate_anatomy_photoidentity,
            confirm_distinctive_markers_photoidentity=args.confirm_distinctive_markers_photoidentity,
            output=Path(args.output),
        )
    except (OSError, PhotoIdentityFineIdentityAttestationError) as exc:
        print(f"BodyRig fine-identity photoidentity attestation: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "BodyRig fine-identity photoidentity attestation: RECORDED | "
        f"domains={len(result['attested_domains'])} | generic_guessing=false | reconstruction=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
