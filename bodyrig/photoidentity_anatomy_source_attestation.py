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

from PIL import Image

from .photoidentity_anatomy_source_discovery import FORMAT as DISCOVERY_FORMAT
from .photoidentity_anatomy_source_discovery import VERSION as DISCOVERY_VERSION
from .photoidentity_evidence import (
    DETAIL_QUALITY_THRESHOLD,
    PhotoIdentityEvidenceError,
    build_observation_evidence,
    validate_bundle,
    write_bundle,
)

FORMAT = "bodyrig-photoidentity-anatomy-source-attestation"
VERSION = 1
POLICY_REVISION = "photoidentity-anatomy-source-attestation-v1"
ADAPTER = "human-source-anatomy-observability-attestation"
ADAPTER_REVISION = "1"
COMPOSITE_ADAPTER = "bodyrig-photoidentity-source-human-anatomy-composite"
COMPOSITE_REVISION = "1"
REF_RE = re.compile(r"^(anatomycand-[0-9a-f]{32}):(rear_body|torso_chest|waist_hips)$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
DOMAIN_REGION = {
    "body_rear": "rear_body",
    "torso_chest": "torso_chest",
    "waist_hips": "waist_hips",
}
DOMAIN_CAPABILITY = {
    "body_rear": "rear-body-view",
    "torso_chest": "torso-chest-detail",
    "waist_hips": "waist-hips-detail",
}
DOMAIN_MIN_SCENES = {"body_rear": 1, "torso_chest": 2, "waist_hips": 2}


class PhotoIdentityAnatomyAttestationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityAnatomyAttestationError(f"attested source file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityAnatomyAttestationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityAnatomyAttestationError(f"{label} must be a JSON object")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityAnatomyAttestationError(f"anatomy source attestation already exists: {path}")
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


def _finite_quality(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentityAnatomyAttestationError("anatomy candidate source quality is not numeric")
    quality = float(value)
    if not math.isfinite(quality) or not 0.0 <= quality <= 1.0:
        raise PhotoIdentityAnatomyAttestationError("anatomy candidate source quality is outside 0..1")
    return quality


def _load_discovery(sweep_root: Path) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    public_path = sweep_root / "anatomy-source-candidates.json"
    private_path = sweep_root / "private-anatomy-source-candidates" / "private-candidate-index.json"
    public = _read_json(public_path, label="Anatomy source discovery manifest")
    private = _read_json(private_path, label="Private anatomy source candidate index")
    if public.get("format") != DISCOVERY_FORMAT or public.get("version") != DISCOVERY_VERSION:
        raise PhotoIdentityAnatomyAttestationError("anatomy source discovery format/version is invalid")
    if public.get("source_paths_persisted") is not False:
        raise PhotoIdentityAnatomyAttestationError("public anatomy discovery leaked source paths")
    if public.get("machine_anatomy_identity_authority") is not False:
        raise PhotoIdentityAnatomyAttestationError("machine anatomy discovery crossed the human authority boundary")
    if public.get("machine_rear_orientation_authority") is not False:
        raise PhotoIdentityAnatomyAttestationError("machine anatomy discovery claimed rear orientation authority")
    if public.get("generic_guessing_permitted") is not False or public.get("production_activation") is not False:
        raise PhotoIdentityAnatomyAttestationError("anatomy discovery authority boundary is invalid")
    if private.get("format") != "bodyrig-photoidentity-private-anatomy-source-index" or private.get("version") != 1:
        raise PhotoIdentityAnatomyAttestationError("private anatomy source index format/version is invalid")
    if private.get("public_manifest_sha256") != _sha256_file(public_path):
        raise PhotoIdentityAnatomyAttestationError("private anatomy source index is not bound to current public discovery bytes")
    return public_path, public, private_path, private


def _candidate_maps(
    public: Mapping[str, Any], private: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    public_rows = public.get("candidates")
    private_rows = private.get("candidates")
    if not isinstance(public_rows, list) or not isinstance(private_rows, list):
        raise PhotoIdentityAnatomyAttestationError("anatomy candidate lists are invalid")
    public_map: dict[str, dict[str, Any]] = {}
    private_map: dict[str, dict[str, Any]] = {}
    for item in public_rows:
        if not isinstance(item, Mapping):
            raise PhotoIdentityAnatomyAttestationError("public anatomy candidate is invalid")
        candidate_id = str(item.get("candidate_id") or "")
        if not re.fullmatch(r"anatomycand-[0-9a-f]{32}", candidate_id) or candidate_id in public_map:
            raise PhotoIdentityAnatomyAttestationError("public anatomy candidate id is invalid/duplicate")
        public_map[candidate_id] = dict(item)
    for item in private_rows:
        if not isinstance(item, Mapping):
            raise PhotoIdentityAnatomyAttestationError("private anatomy candidate is invalid")
        candidate_id = str(item.get("candidate_id") or "")
        if candidate_id not in public_map or candidate_id in private_map:
            raise PhotoIdentityAnatomyAttestationError("private anatomy candidate id does not match public discovery")
        private_map[candidate_id] = dict(item)
    if set(public_map) != set(private_map):
        raise PhotoIdentityAnatomyAttestationError("public/private anatomy candidate sets differ")
    return public_map, private_map


def _parse_refs(values: Sequence[str], *, domain: str) -> list[tuple[str, str]]:
    expected_region = DOMAIN_REGION[domain]
    parsed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip().lower()
        match = REF_RE.fullmatch(text)
        if not match:
            raise PhotoIdentityAnatomyAttestationError(f"invalid {domain} candidate reference: {text or 'empty'}")
        candidate_id, region = match.groups()
        if region != expected_region:
            raise PhotoIdentityAnatomyAttestationError(f"{domain} reference points to wrong region type: {region}")
        if text in seen:
            raise PhotoIdentityAnatomyAttestationError(f"duplicate {domain} candidate reference: {text}")
        seen.add(text)
        parsed.append((candidate_id, region))
    return parsed


def _verify_selected_refs(
    *,
    sweep_root: Path,
    public_map: Mapping[str, Mapping[str, Any]],
    private_map: Mapping[str, Mapping[str, Any]],
    refs: Sequence[tuple[str, str]],
    domain: str,
) -> list[dict[str, Any]]:
    if not refs:
        raise PhotoIdentityAnatomyAttestationError(f"{domain} attestation requires selected source closeups")
    selected: list[dict[str, Any]] = []
    scenes: set[str] = set()
    media_hash_cache: dict[str, str] = {}
    private_root = (sweep_root / "private-anatomy-source-candidates").resolve()
    for candidate_id, region in refs:
        public = public_map.get(candidate_id)
        private = private_map.get(candidate_id)
        if not isinstance(public, Mapping) or not isinstance(private, Mapping):
            raise PhotoIdentityAnatomyAttestationError(f"selected anatomy candidate is missing: {candidate_id}")
        if public.get("scene_id") != private.get("scene_id") or public.get("source_media_sha256") != private.get("source_media_sha256"):
            raise PhotoIdentityAnatomyAttestationError("public/private anatomy candidate identity changed")
        regions = public.get("regions")
        private_images = private.get("region_images")
        if not isinstance(regions, Mapping) or not isinstance(private_images, Mapping):
            raise PhotoIdentityAnatomyAttestationError("selected anatomy candidate region binding is invalid")
        entry = regions.get(region)
        image_value = private_images.get(region)
        if not isinstance(entry, Mapping) or not isinstance(image_value, str):
            raise PhotoIdentityAnatomyAttestationError(f"selected anatomy region is unavailable: {candidate_id}:{region}")
        if entry.get("machine_asserts_anatomy_visible") is not False or entry.get("machine_asserts_rear_orientation") is not False:
            raise PhotoIdentityAnatomyAttestationError("anatomy candidate crossed the machine/human semantic boundary")
        quality = _finite_quality(entry.get("source_quality"))
        if entry.get("review_eligible") is not True or quality < DETAIL_QUALITY_THRESHOLD:
            raise PhotoIdentityAnatomyAttestationError(
                f"selected anatomy source is below photoidentity review threshold: {candidate_id}:{region} quality={quality:.4f}"
            )
        image = Path(image_value).expanduser().resolve()
        try:
            image.relative_to(private_root)
        except ValueError as exc:
            raise PhotoIdentityAnatomyAttestationError("selected anatomy closeup escaped private sweep root") from exc
        if _sha256_file(image) != str(entry.get("image_sha256") or ""):
            raise PhotoIdentityAnatomyAttestationError("selected anatomy closeup bytes no longer match discovery manifest")
        try:
            with Image.open(image) as opened:
                if opened.size != (1024, 1024):
                    raise PhotoIdentityAnatomyAttestationError("selected anatomy closeup is not canonical 1024x1024")
        except PhotoIdentityAnatomyAttestationError:
            raise
        except Exception as exc:
            raise PhotoIdentityAnatomyAttestationError("selected anatomy closeup is unreadable") from exc

        source_path = Path(str(private.get("source_path") or "")).expanduser().resolve()
        key = os.path.normcase(str(source_path))
        source_sha = media_hash_cache.get(key)
        if source_sha is None:
            source_sha = _sha256_file(source_path)
            media_hash_cache[key] = source_sha
        expected_source_sha = str(public.get("source_media_sha256") or "").lower()
        if not SHA_RE.fullmatch(expected_source_sha) or source_sha != expected_source_sha:
            raise PhotoIdentityAnatomyAttestationError("selected anatomy source media bytes no longer match discovery authority")
        scene = str(public.get("scene_id") or "").strip()
        if not scene:
            raise PhotoIdentityAnatomyAttestationError("selected anatomy source scene is missing")
        scenes.add(scene)
        selected.append(
            {
                "candidate_id": candidate_id,
                "region": region,
                "scene_id": scene,
                "source_media_sha256": source_sha,
                "image_sha256": str(entry["image_sha256"]),
                "source_quality": quality,
                "native_crop_width": int(entry["native_crop_width"]),
                "native_crop_height": int(entry["native_crop_height"]),
                "observation_view_hint": str(public.get("observation_view_hint") or "unknown"),
                "observation_face_visibility": float(public.get("observation_face_visibility", 0.0)),
            }
        )
    if len(scenes) < DOMAIN_MIN_SCENES[domain]:
        raise PhotoIdentityAnatomyAttestationError(
            f"{domain} requires at least {DOMAIN_MIN_SCENES[domain]} distinct source scene(s)"
        )
    return selected


def _claims(selected: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_scene: dict[str, float] = {}
    for item in selected:
        scene = str(item["scene_id"])
        quality = float(item["source_quality"])
        by_scene[scene] = min(by_scene.get(scene, quality), quality)
    return [
        {
            "scene_id": scene,
            "quality": round(quality, 4),
            "source_derived": True,
            "adapter": ADAPTER,
            "revision": ADAPTER_REVISION,
        }
        for scene, quality in sorted(by_scene.items())
    ]


def _validate_optional_nail_prior(sweep_root: Path) -> tuple[Path, Path] | None:
    observations = sweep_root / "nail-attested-evidence" / "photoidentity-observations.json"
    report = sweep_root / "nail-attested-evidence" / "photoidentity-evidence.json"
    receipt_path = sweep_root / "photoidentity-nail-source-attestation.json"
    present = [observations.exists(), report.exists(), receipt_path.exists()]
    if not any(present):
        return None
    if not all(present):
        raise PhotoIdentityAnatomyAttestationError("partial nail-attestation state exists; refusing ambiguous evidence composition")
    try:
        nail_report = validate_bundle(report, observations)
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityAnatomyAttestationError(f"nail-attested photoidentity evidence is invalid: {exc}") from exc
    receipt = _read_json(receipt_path, label="Nail source attestation receipt")
    if (
        receipt.get("format") != "bodyrig-photoidentity-nail-source-attestation"
        or receipt.get("version") != 1
        or receipt.get("adapter") != "human-source-nail-detail-attestation"
        or receipt.get("adapter_revision") != "1"
        or receipt.get("operator_supplied") is not True
        or receipt.get("source_grounded") is not True
        or receipt.get("generic_guessing_permitted") is not False
        or receipt.get("production_activation") is not False
    ):
        raise PhotoIdentityAnatomyAttestationError("nail source attestation receipt authority boundary is invalid")
    if receipt.get("enriched_observation_evidence_sha256") != _sha256_file(observations):
        raise PhotoIdentityAnatomyAttestationError("nail receipt no longer binds exact enriched observation evidence")
    if receipt.get("enriched_sufficiency_report_sha256") != _sha256_file(report):
        raise PhotoIdentityAnatomyAttestationError("nail receipt no longer binds exact enriched sufficiency evidence")
    if str(receipt.get("performer_id") or "") != str(nail_report["performer_id"]):
        raise PhotoIdentityAnatomyAttestationError("nail receipt performer binding changed")
    if str(receipt.get("bodyrig_revision") or "") != str(nail_report["bodyrig_revision"]):
        raise PhotoIdentityAnatomyAttestationError("nail receipt BodyRig revision binding changed")
    return observations, report


def _resolve_prior_bundle(sweep_root: Path) -> tuple[Path, Path, dict[str, Any], dict[str, Any], str]:
    base_observations = sweep_root / "human-parsing-evidence" / "photoidentity-observations.json"
    base_report = sweep_root / "human-parsing-evidence" / "photoidentity-evidence.json"
    try:
        base = validate_bundle(base_report, base_observations)
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityAnatomyAttestationError(f"base photoidentity evidence is invalid: {exc}") from exc
    optional = _validate_optional_nail_prior(sweep_root)
    observations_path, report_path = optional if optional is not None else (base_observations, base_report)
    try:
        report = validate_bundle(
            report_path,
            observations_path,
            expected_performer_id=str(base["performer_id"]),
            expected_bodyrig_revision=str(base["bodyrig_revision"]),
            expected_baseline_source_manifest_sha256=str(base["baseline_source_manifest_sha256"]),
        )
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityAnatomyAttestationError(f"selected prior photoidentity evidence is invalid: {exc}") from exc
    observations = _read_json(observations_path, label="Prior photoidentity observations")
    return observations_path, report_path, observations, report, "nail-attested" if optional is not None else "human-parsing"


def record_attestation(
    *,
    sweep_root: Path,
    rear_refs: Sequence[str],
    torso_refs: Sequence[str],
    waist_refs: Sequence[str],
    confirm_rear_view: bool,
    confirm_torso_chest_anatomy_visible: bool,
    confirm_waist_hips_anatomy_visible: bool,
    quality_note: str,
) -> dict[str, Any]:
    sweep_root = sweep_root.expanduser().resolve()
    if not sweep_root.is_dir():
        raise PhotoIdentityAnatomyAttestationError("photoidentity sweep root is missing")
    if not (confirm_rear_view and confirm_torso_chest_anatomy_visible and confirm_waist_hips_anatomy_visible):
        raise PhotoIdentityAnatomyAttestationError(
            "anatomy source attestation is atomic and requires explicit rear, torso/chest and waist/hips confirmation"
        )
    note = str(quality_note or "").strip()
    if len(note) < 20 or len(note) > 2000 or (note.startswith("<") and note.endswith(">")):
        raise PhotoIdentityAnatomyAttestationError("source-only anatomy attestation requires a real quality note")

    public_path, public, private_path, private = _load_discovery(sweep_root)
    public_map, private_map = _candidate_maps(public, private)
    base_observations_path = sweep_root / "human-parsing-evidence" / "photoidentity-observations.json"
    base_report_path = sweep_root / "human-parsing-evidence" / "photoidentity-evidence.json"
    try:
        base_report = validate_bundle(base_report_path, base_observations_path)
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityAnatomyAttestationError(f"base photoidentity evidence is invalid: {exc}") from exc
    if str(public.get("performer_id") or "") != str(base_report["performer_id"]):
        raise PhotoIdentityAnatomyAttestationError("anatomy discovery performer no longer matches base evidence")
    if str(public.get("bodyrig_revision") or "") != str(base_report["bodyrig_revision"]):
        raise PhotoIdentityAnatomyAttestationError("anatomy discovery revision no longer matches base evidence")
    if public.get("input_observation_evidence_sha256") != _sha256_file(base_observations_path):
        raise PhotoIdentityAnatomyAttestationError("anatomy discovery is not bound to current base observation evidence")
    if public.get("input_sufficiency_report_sha256") != _sha256_file(base_report_path):
        raise PhotoIdentityAnatomyAttestationError("anatomy discovery is not bound to current base sufficiency evidence")

    prior_observations_path, prior_report_path, prior_observations, prior_report, prior_stage = _resolve_prior_bundle(sweep_root)
    selected = {
        "body_rear": _verify_selected_refs(
            sweep_root=sweep_root,
            public_map=public_map,
            private_map=private_map,
            refs=_parse_refs(rear_refs, domain="body_rear"),
            domain="body_rear",
        ),
        "torso_chest": _verify_selected_refs(
            sweep_root=sweep_root,
            public_map=public_map,
            private_map=private_map,
            refs=_parse_refs(torso_refs, domain="torso_chest"),
            domain="torso_chest",
        ),
        "waist_hips": _verify_selected_refs(
            sweep_root=sweep_root,
            public_map=public_map,
            private_map=private_map,
            refs=_parse_refs(waist_refs, domain="waist_hips"),
            domain="waist_hips",
        ),
    }

    existing_analyzer = prior_observations.get("analyzer")
    existing_details = prior_observations.get("detail_evidence")
    if not isinstance(existing_analyzer, Mapping) or not isinstance(existing_details, Mapping):
        raise PhotoIdentityAnatomyAttestationError("prior photoidentity analyzer/detail authority is invalid")
    merged_details = {
        str(domain): [dict(item) for item in claims if isinstance(item, Mapping)]
        for domain, claims in existing_details.items()
        if isinstance(claims, list)
    }
    for domain, items in selected.items():
        merged_details[domain] = _claims(items)
    capabilities = sorted(
        {
            *[str(item) for item in existing_analyzer.get("capabilities", [])],
            *DOMAIN_CAPABILITY.values(),
        }
    )
    enriched = build_observation_evidence(
        performer_id=str(prior_observations["performer_id"]),
        bodyrig_revision=str(prior_observations["bodyrig_revision"]),
        baseline_source_manifest_sha256=str(prior_observations["baseline_source_manifest_sha256"]),
        analyzer_adapter=COMPOSITE_ADAPTER,
        analyzer_revision=COMPOSITE_REVISION,
        analyzer_capabilities=capabilities,
        candidate_scenes=int(prior_observations["candidate_scenes"]),
        source_files_scanned=int(prior_observations["source_files_scanned"]),
        scan_exhausted=bool(prior_observations["scan_exhausted"]),
        rows=list(prior_observations["rows"]),
        detail_evidence=merged_details,
    )
    observations_path, report_path, report = write_bundle(sweep_root / "anatomy-attested-evidence", enriched)
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "performer_id": str(report["performer_id"]),
        "bodyrig_revision": str(report["bodyrig_revision"]),
        "discovery_manifest_sha256": _sha256_file(public_path),
        "private_candidate_index_sha256": _sha256_file(private_path),
        "base_observation_evidence_sha256": _sha256_file(base_observations_path),
        "base_sufficiency_report_sha256": _sha256_file(base_report_path),
        "prior_stage": prior_stage,
        "prior_observation_evidence_sha256": _sha256_file(prior_observations_path),
        "prior_sufficiency_report_sha256": _sha256_file(prior_report_path),
        "adapter": ADAPTER,
        "adapter_revision": ADAPTER_REVISION,
        "attested_domains": ["body_rear", "torso_chest", "waist_hips"],
        "selected_body_rear": selected["body_rear"],
        "selected_torso_chest": selected["torso_chest"],
        "selected_waist_hips": selected["waist_hips"],
        "confirm_rear_view": True,
        "confirm_torso_chest_anatomy_visible": True,
        "confirm_waist_hips_anatomy_visible": True,
        "quality_note": note,
        "reviewed_utc": datetime.now(timezone.utc).isoformat(),
        "operator_supplied": True,
        "source_grounded": True,
        "generic_guessing_permitted": False,
        "production_activation": False,
        "enriched_observation_evidence_sha256": _sha256_file(observations_path),
        "enriched_sufficiency_report_sha256": _sha256_file(report_path),
    }
    receipt_path = sweep_root / "photoidentity-anatomy-source-attestation.json"
    _write_create_only(receipt_path, receipt)
    return {
        **receipt,
        "receipt": str(receipt_path),
        "enriched_observation_evidence": str(observations_path),
        "enriched_sufficiency_report": str(report_path),
        "report": report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record atomic human source-only rear/torso/waist observability attestation."
    )
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--rear-ref", action="append", default=[])
    parser.add_argument("--torso-ref", action="append", default=[])
    parser.add_argument("--waist-ref", action="append", default=[])
    parser.add_argument("--confirm-rear-view", action="store_true")
    parser.add_argument("--confirm-torso-chest-anatomy-visible", action="store_true")
    parser.add_argument("--confirm-waist-hips-anatomy-visible", action="store_true")
    parser.add_argument("--quality-note", required=True)
    args = parser.parse_args(argv)
    try:
        result = record_attestation(
            sweep_root=Path(args.sweep_root),
            rear_refs=args.rear_ref,
            torso_refs=args.torso_ref,
            waist_refs=args.waist_ref,
            confirm_rear_view=bool(args.confirm_rear_view),
            confirm_torso_chest_anatomy_visible=bool(args.confirm_torso_chest_anatomy_visible),
            confirm_waist_hips_anatomy_visible=bool(args.confirm_waist_hips_anatomy_visible),
            quality_note=args.quality_note,
        )
    except (OSError, PhotoIdentityAnatomyAttestationError) as exc:
        print(f"BodyRig photoidentity anatomy source attestation: FAIL: {exc}", file=sys.stderr)
        return 1
    report = result["report"]
    print(
        "BodyRig photoidentity anatomy source attestation: RECORDED | "
        f"rear={report['domains']['body_rear']['status']} | "
        f"torso={report['domains']['torso_chest']['status']} | "
        f"waist={report['domains']['waist_hips']['status']} | "
        f"source_sufficient={str(bool(report['source_evidence_sufficient'])).lower()}"
    )
    print(f"Receipt: {result['receipt']}")
    print(f"Updated sufficiency: {result['enriched_sufficiency_report']}")
    print("Production activation: FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
