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

from .photoidentity_evidence import (
    DETAIL_QUALITY_THRESHOLD,
    PhotoIdentityEvidenceError,
    build_observation_evidence,
    validate_bundle,
    write_bundle,
)
from .photoidentity_nail_source_discovery import FORMAT as DISCOVERY_FORMAT
from .photoidentity_nail_source_discovery import VERSION as DISCOVERY_VERSION

FORMAT = "bodyrig-photoidentity-nail-source-attestation"
VERSION = 1
POLICY_REVISION = "photoidentity-nail-source-attestation-v1"
ADAPTER = "human-source-nail-detail-attestation"
ADAPTER_REVISION = "1"
COMPOSITE_ADAPTER = "bodyrig-photoidentity-coarse-openpose-schp-human-nails-composite"
COMPOSITE_REVISION = "1"
REF_RE = re.compile(r"^(nailcand-[0-9a-f]{32}):(left_fingernails|right_fingernails|left_toenails|right_toenails)$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PhotoIdentityNailAttestationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityNailAttestationError(f"attested source file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityNailAttestationError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityNailAttestationError(f"{label} must be a JSON object")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityNailAttestationError(f"nail source attestation already exists: {path}")
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
        raise PhotoIdentityNailAttestationError("nail candidate source quality is not numeric")
    quality = float(value)
    if not math.isfinite(quality) or not 0.0 <= quality <= 1.0:
        raise PhotoIdentityNailAttestationError("nail candidate source quality is outside 0..1")
    return quality


def _load_discovery(sweep_root: Path) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    public_path = sweep_root / "nail-source-candidates.json"
    private_path = sweep_root / "private-nail-source-candidates" / "private-candidate-index.json"
    public = _read_json(public_path, label="Nail source discovery manifest")
    private = _read_json(private_path, label="Private nail source candidate index")
    if public.get("format") != DISCOVERY_FORMAT or public.get("version") != DISCOVERY_VERSION:
        raise PhotoIdentityNailAttestationError("nail source discovery format/version is invalid")
    if public.get("source_paths_persisted") is not False:
        raise PhotoIdentityNailAttestationError("public nail discovery leaked source paths")
    if public.get("machine_nail_identity_authority") is not False:
        raise PhotoIdentityNailAttestationError("machine nail discovery crossed the human authority boundary")
    if public.get("generic_guessing_permitted") is not False or public.get("production_activation") is not False:
        raise PhotoIdentityNailAttestationError("nail discovery authority boundary is invalid")
    if private.get("format") != "bodyrig-photoidentity-private-nail-source-index" or private.get("version") != 1:
        raise PhotoIdentityNailAttestationError("private nail source index format/version is invalid")
    if private.get("public_manifest_sha256") != _sha256_file(public_path):
        raise PhotoIdentityNailAttestationError("private nail source index is not bound to current public discovery bytes")
    return public_path, public, private_path, private


def _candidate_maps(
    public: Mapping[str, Any],
    private: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    public_rows = public.get("candidates")
    private_rows = private.get("candidates")
    if not isinstance(public_rows, list) or not isinstance(private_rows, list):
        raise PhotoIdentityNailAttestationError("nail candidate lists are invalid")
    public_map: dict[str, dict[str, Any]] = {}
    private_map: dict[str, dict[str, Any]] = {}
    for item in public_rows:
        if not isinstance(item, Mapping):
            raise PhotoIdentityNailAttestationError("public nail candidate is invalid")
        candidate_id = str(item.get("candidate_id") or "")
        if not re.fullmatch(r"nailcand-[0-9a-f]{32}", candidate_id) or candidate_id in public_map:
            raise PhotoIdentityNailAttestationError("public nail candidate id is invalid/duplicate")
        public_map[candidate_id] = dict(item)
    for item in private_rows:
        if not isinstance(item, Mapping):
            raise PhotoIdentityNailAttestationError("private nail candidate is invalid")
        candidate_id = str(item.get("candidate_id") or "")
        if candidate_id not in public_map or candidate_id in private_map:
            raise PhotoIdentityNailAttestationError("private nail candidate id does not match public discovery")
        private_map[candidate_id] = dict(item)
    if set(public_map) != set(private_map):
        raise PhotoIdentityNailAttestationError("public/private nail candidate sets differ")
    return public_map, private_map


def _parse_refs(values: Sequence[str], *, domain: str) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    seen: set[str] = set()
    expected_suffix = "fingernails" if domain == "fingernails_detail" else "toenails"
    for raw in values:
        text = str(raw or "").strip().lower()
        match = REF_RE.fullmatch(text)
        if not match:
            raise PhotoIdentityNailAttestationError(f"invalid {domain} candidate reference: {text or 'empty'}")
        candidate_id, region = match.groups()
        if not region.endswith(expected_suffix):
            raise PhotoIdentityNailAttestationError(f"{domain} reference points to wrong region type: {region}")
        if text in seen:
            raise PhotoIdentityNailAttestationError(f"duplicate {domain} candidate reference: {text}")
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
        raise PhotoIdentityNailAttestationError(f"{domain} attestation requires selected source closeups")
    selected: list[dict[str, Any]] = []
    media_hash_cache: dict[str, str] = {}
    expected_sides = {"left", "right"}
    sides: set[str] = set()
    scenes: set[str] = set()
    private_root = (sweep_root / "private-nail-source-candidates").resolve()
    for candidate_id, region in refs:
        public = public_map.get(candidate_id)
        private = private_map.get(candidate_id)
        if not isinstance(public, Mapping) or not isinstance(private, Mapping):
            raise PhotoIdentityNailAttestationError(f"selected nail candidate is missing: {candidate_id}")
        if public.get("scene_id") != private.get("scene_id") or public.get("source_media_sha256") != private.get("source_media_sha256"):
            raise PhotoIdentityNailAttestationError("public/private nail candidate identity changed")
        regions = public.get("regions")
        private_images = private.get("region_images")
        if not isinstance(regions, Mapping) or not isinstance(private_images, Mapping):
            raise PhotoIdentityNailAttestationError("selected nail candidate region binding is invalid")
        entry = regions.get(region)
        image_value = private_images.get(region)
        if not isinstance(entry, Mapping) or not isinstance(image_value, str):
            raise PhotoIdentityNailAttestationError(f"selected nail region is unavailable: {candidate_id}:{region}")
        quality = _finite_quality(entry.get("source_quality"))
        if entry.get("review_eligible") is not True or quality < DETAIL_QUALITY_THRESHOLD:
            raise PhotoIdentityNailAttestationError(
                f"selected nail source is below photoidentity review threshold: {candidate_id}:{region} quality={quality:.4f}"
            )
        image = Path(image_value).expanduser().resolve()
        try:
            image.relative_to(private_root)
        except ValueError as exc:
            raise PhotoIdentityNailAttestationError("selected nail closeup escaped private sweep root") from exc
        if _sha256_file(image) != str(entry.get("image_sha256") or ""):
            raise PhotoIdentityNailAttestationError("selected nail closeup bytes no longer match discovery manifest")
        try:
            with Image.open(image) as opened:
                if opened.size != (1024, 1024):
                    raise PhotoIdentityNailAttestationError("selected nail closeup is not canonical 1024x1024")
        except PhotoIdentityNailAttestationError:
            raise
        except Exception as exc:
            raise PhotoIdentityNailAttestationError("selected nail closeup is unreadable") from exc

        source_path = Path(str(private.get("source_path") or "")).expanduser().resolve()
        key = os.path.normcase(str(source_path))
        source_sha = media_hash_cache.get(key)
        if source_sha is None:
            source_sha = _sha256_file(source_path)
            media_hash_cache[key] = source_sha
        expected_source_sha = str(public.get("source_media_sha256") or "").lower()
        if not SHA_RE.fullmatch(expected_source_sha) or source_sha != expected_source_sha:
            raise PhotoIdentityNailAttestationError("selected nail source media bytes no longer match discovery authority")

        scene = str(public.get("scene_id") or "").strip()
        if not scene:
            raise PhotoIdentityNailAttestationError("selected nail source scene is missing")
        scenes.add(scene)
        sides.add("left" if region.startswith("left_") else "right")
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
            }
        )
    if len(scenes) < 2:
        raise PhotoIdentityNailAttestationError(f"{domain} requires at least two distinct source scenes")
    if sides != expected_sides:
        raise PhotoIdentityNailAttestationError(f"{domain} requires both left and right source coverage")
    return selected


def _claims(selected: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_scene: dict[str, float] = {}
    for item in selected:
        scene = str(item["scene_id"])
        quality = float(item["source_quality"])
        # If several sides are attested in one scene, the scene claim is only as
        # strong as the weakest selected source crop from that scene.
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


def record_attestation(
    *,
    sweep_root: Path,
    fingernail_refs: Sequence[str],
    toenail_refs: Sequence[str],
    confirm_fingernails: bool,
    confirm_toenails: bool,
    quality_note: str,
) -> dict[str, Any]:
    sweep_root = sweep_root.expanduser().resolve()
    if not sweep_root.is_dir():
        raise PhotoIdentityNailAttestationError("photoidentity sweep root is missing")
    if not confirm_fingernails and not confirm_toenails:
        raise PhotoIdentityNailAttestationError("source-only nail attestation requires at least one explicit confirmation")
    note = str(quality_note or "").strip()
    if len(note) < 12 or len(note) > 2000 or (note.startswith("<") and note.endswith(">")):
        raise PhotoIdentityNailAttestationError("source-only nail attestation requires a real quality note")

    public_path, public, private_path, private = _load_discovery(sweep_root)
    public_map, private_map = _candidate_maps(public, private)
    prior_observations_path = sweep_root / "human-parsing-evidence" / "photoidentity-observations.json"
    prior_report_path = sweep_root / "human-parsing-evidence" / "photoidentity-evidence.json"
    try:
        prior_report = validate_bundle(prior_report_path, prior_observations_path)
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityNailAttestationError(f"prior photoidentity evidence is invalid: {exc}") from exc
    prior_observations = _read_json(prior_observations_path, label="Prior photoidentity observations")
    if str(public.get("performer_id") or "") != str(prior_report["performer_id"]):
        raise PhotoIdentityNailAttestationError("nail discovery performer no longer matches prior evidence")
    if str(public.get("bodyrig_revision") or "") != str(prior_report["bodyrig_revision"]):
        raise PhotoIdentityNailAttestationError("nail discovery revision no longer matches prior evidence")
    if public.get("input_observation_evidence_sha256") != _sha256_file(prior_observations_path):
        raise PhotoIdentityNailAttestationError("nail discovery is not bound to current prior observation evidence")
    if public.get("input_sufficiency_report_sha256") != _sha256_file(prior_report_path):
        raise PhotoIdentityNailAttestationError("nail discovery is not bound to current prior sufficiency evidence")

    selected_fingernails: list[dict[str, Any]] = []
    selected_toenails: list[dict[str, Any]] = []
    new_details: dict[str, list[dict[str, Any]]] = {}
    new_capabilities: set[str] = set()
    if confirm_fingernails:
        selected_fingernails = _verify_selected_refs(
            sweep_root=sweep_root,
            public_map=public_map,
            private_map=private_map,
            refs=_parse_refs(fingernail_refs, domain="fingernails_detail"),
            domain="fingernails_detail",
        )
        new_details["fingernails_detail"] = _claims(selected_fingernails)
        new_capabilities.add("fingernails-detail")
    elif fingernail_refs:
        raise PhotoIdentityNailAttestationError("fingernail refs were supplied without explicit fingernail confirmation")

    if confirm_toenails:
        selected_toenails = _verify_selected_refs(
            sweep_root=sweep_root,
            public_map=public_map,
            private_map=private_map,
            refs=_parse_refs(toenail_refs, domain="toenails_detail"),
            domain="toenails_detail",
        )
        new_details["toenails_detail"] = _claims(selected_toenails)
        new_capabilities.add("toenails-detail")
    elif toenail_refs:
        raise PhotoIdentityNailAttestationError("toenail refs were supplied without explicit toenail confirmation")

    existing_analyzer = prior_observations.get("analyzer")
    existing_details = prior_observations.get("detail_evidence")
    if not isinstance(existing_analyzer, Mapping) or not isinstance(existing_details, Mapping):
        raise PhotoIdentityNailAttestationError("prior photoidentity analyzer/detail authority is invalid")
    merged_details = {
        str(domain): [dict(item) for item in claims if isinstance(item, Mapping)]
        for domain, claims in existing_details.items()
        if isinstance(claims, list)
    }
    merged_details.update(new_details)
    capabilities = sorted(
        {
            *[str(item) for item in existing_analyzer.get("capabilities", [])],
            *new_capabilities,
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
    observations_path, report_path, report = write_bundle(sweep_root / "nail-attested-evidence", enriched)
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "performer_id": str(report["performer_id"]),
        "bodyrig_revision": str(report["bodyrig_revision"]),
        "discovery_manifest_sha256": _sha256_file(public_path),
        "private_candidate_index_sha256": _sha256_file(private_path),
        "prior_observation_evidence_sha256": _sha256_file(prior_observations_path),
        "prior_sufficiency_report_sha256": _sha256_file(prior_report_path),
        "adapter": ADAPTER,
        "adapter_revision": ADAPTER_REVISION,
        "attested_domains": sorted(new_details),
        "selected_fingernails": selected_fingernails,
        "selected_toenails": selected_toenails,
        "quality_note": note,
        "reviewed_utc": datetime.now(timezone.utc).isoformat(),
        "operator_supplied": True,
        "source_grounded": True,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": bool(report["reconstruction_permitted"]),
        "human_review_render_permitted": bool(report["human_review_render_permitted"]),
        "production_activation": False,
        "enriched_observation_evidence_sha256": _sha256_file(observations_path),
        "enriched_sufficiency_report_sha256": _sha256_file(report_path),
    }
    receipt_path = sweep_root / "photoidentity-nail-source-attestation.json"
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
        description="Record explicit human source-only nail detail attestation and enrich photoidentity sufficiency evidence."
    )
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--fingernail-ref", action="append", default=[])
    parser.add_argument("--toenail-ref", action="append", default=[])
    parser.add_argument("--confirm-fingernails", action="store_true")
    parser.add_argument("--confirm-toenails", action="store_true")
    parser.add_argument("--quality-note", required=True)
    args = parser.parse_args(argv)
    try:
        result = record_attestation(
            sweep_root=Path(args.sweep_root),
            fingernail_refs=args.fingernail_ref,
            toenail_refs=args.toenail_ref,
            confirm_fingernails=bool(args.confirm_fingernails),
            confirm_toenails=bool(args.confirm_toenails),
            quality_note=args.quality_note,
        )
    except (OSError, PhotoIdentityNailAttestationError) as exc:
        print(f"BodyRig photoidentity nail source attestation: FAIL: {exc}", file=sys.stderr)
        return 1
    report = result["report"]
    print(
        "BodyRig photoidentity nail source attestation: RECORDED | "
        f"domains={','.join(result['attested_domains'])} | "
        f"source_sufficient={str(bool(report['source_evidence_sufficient'])).lower()}"
    )
    print(f"Receipt: {result['receipt']}")
    print(f"Updated sufficiency: {result['enriched_sufficiency_report']}")
    print("Production activation: FALSE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
