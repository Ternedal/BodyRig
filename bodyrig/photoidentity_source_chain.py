from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoidentity_authority import PhotoIdentityAuthorityError, validate_authoritative_bundle
from .photoidentity_evidence import DETAIL_QUALITY_THRESHOLD

POLICY_REVISION = "photoidentity-human-source-chain-v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PhotoIdentitySourceChainError(PhotoIdentityAuthorityError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentitySourceChainError(f"photoidentity source-chain file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentitySourceChainError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentitySourceChainError(f"{label} must be a JSON object")
    return value


def _canonical_sha(value: object, *, label: str) -> str:
    digest = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(digest):
        raise PhotoIdentitySourceChainError(f"{label} is not a canonical SHA-256")
    return digest


def _quality(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotoIdentitySourceChainError(f"{label} is not numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise PhotoIdentitySourceChainError(f"{label} is outside 0..1")
    if result < DETAIL_QUALITY_THRESHOLD:
        raise PhotoIdentitySourceChainError(
            f"{label} is below source authority threshold {DETAIL_QUALITY_THRESHOLD:.2f}"
        )
    return result


def _receipt_boundary(
    receipt: Mapping[str, Any],
    *,
    expected_format: str,
    label: str,
) -> None:
    if (
        receipt.get("format") != expected_format
        or receipt.get("version") != 1
        or receipt.get("operator_supplied") is not True
        or receipt.get("source_grounded") is not True
        or receipt.get("generic_guessing_permitted") is not False
        or receipt.get("production_activation") is not False
    ):
        raise PhotoIdentitySourceChainError(f"{label} authority boundary is invalid")
    note = str(receipt.get("quality_note") or "").strip()
    if len(note) < 12 or (note.startswith("<") and note.endswith(">")):
        raise PhotoIdentitySourceChainError(f"{label} lacks a real human source-review note")


def _selected_claims(
    selected: object,
    *,
    label: str,
    minimum_scenes: int,
    expected_regions: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(selected, list) or not selected:
        raise PhotoIdentitySourceChainError(f"{label} selected source list is missing")
    by_scene: dict[str, float] = {}
    regions: set[str] = set()
    for item in selected:
        if not isinstance(item, Mapping):
            raise PhotoIdentitySourceChainError(f"{label} selected source item is invalid")
        scene = str(item.get("scene_id") or "").strip()
        region = str(item.get("region") or "").strip()
        if not scene or not region:
            raise PhotoIdentitySourceChainError(f"{label} selected source identity is invalid")
        source_sha = _canonical_sha(item.get("source_media_sha256"), label=f"{label} source-media SHA")
        image_sha = _canonical_sha(item.get("image_sha256"), label=f"{label} review-image SHA")
        if source_sha == image_sha:
            raise PhotoIdentitySourceChainError(f"{label} source-media and review-image SHA unexpectedly match")
        quality = _quality(item.get("source_quality"), label=f"{label} source quality")
        by_scene[scene] = min(by_scene.get(scene, quality), quality)
        regions.add(region)
    if len(by_scene) < minimum_scenes:
        raise PhotoIdentitySourceChainError(
            f"{label} requires at least {minimum_scenes} distinct source scene(s)"
        )
    if expected_regions is not None and regions != expected_regions:
        raise PhotoIdentitySourceChainError(
            f"{label} source coverage is incomplete: expected {sorted(expected_regions)}, got {sorted(regions)}"
        )
    return [
        {
            "scene_id": scene,
            "quality": round(quality, 4),
        }
        for scene, quality in sorted(by_scene.items())
    ]


def _assert_claims_match(
    observations: Mapping[str, Any],
    *,
    domain: str,
    expected: Sequence[Mapping[str, Any]],
    adapter: str,
    revision: str = "1",
) -> None:
    details = observations.get("detail_evidence")
    if not isinstance(details, Mapping):
        raise PhotoIdentitySourceChainError("final photoidentity detail evidence is invalid")
    raw = details.get(domain)
    if not isinstance(raw, list):
        raise PhotoIdentitySourceChainError(f"final photoidentity evidence lacks {domain} claims")
    actual: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise PhotoIdentitySourceChainError(f"final {domain} claim is invalid")
        if item.get("source_derived") is not True:
            raise PhotoIdentitySourceChainError(f"final {domain} claim is not source-derived")
        if str(item.get("adapter") or "") != adapter or str(item.get("revision") or "") != revision:
            raise PhotoIdentitySourceChainError(f"final {domain} claim adapter/revision changed")
        actual.append(
            {
                "scene_id": str(item.get("scene_id") or ""),
                "quality": round(float(item.get("quality", -1.0)), 4),
            }
        )
    if actual != list(expected):
        raise PhotoIdentitySourceChainError(f"final {domain} claims do not match human source receipt")


def validate_registration_source_chain(
    report_path: str | Path,
    observation_path: str | Path | None = None,
    *,
    expected_performer_id: str | None = None,
    expected_bodyrig_revision: str | None = None,
    expected_baseline_source_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    report_file = Path(report_path).expanduser().resolve()
    observations_file = (
        Path(observation_path).expanduser().resolve()
        if observation_path is not None
        else report_file.with_name("photoidentity-observations.json")
    )
    if report_file.name != "photoidentity-evidence.json" or observations_file.name != "photoidentity-observations.json":
        raise PhotoIdentitySourceChainError("registration requires canonical photoidentity bundle filenames")
    if report_file.parent != observations_file.parent or report_file.parent.name != "anatomy-attested-evidence":
        raise PhotoIdentitySourceChainError(
            "registration requires the final canonical anatomy-attested-evidence bundle"
        )
    sweep_root = report_file.parent.parent

    report = validate_authoritative_bundle(
        report_file,
        observations_file,
        require_sufficient=True,
        expected_performer_id=expected_performer_id,
        expected_bodyrig_revision=expected_bodyrig_revision,
        expected_baseline_source_manifest_sha256=expected_baseline_source_manifest_sha256,
    )
    observations = _read_json(observations_file, label="Final photoidentity observations")

    nail_receipt_path = sweep_root / "photoidentity-nail-source-attestation.json"
    anatomy_receipt_path = sweep_root / "photoidentity-anatomy-source-attestation.json"
    nail_receipt = _read_json(nail_receipt_path, label="Nail source attestation receipt")
    anatomy_receipt = _read_json(anatomy_receipt_path, label="Anatomy source attestation receipt")
    _receipt_boundary(
        nail_receipt,
        expected_format="bodyrig-photoidentity-nail-source-attestation",
        label="Nail source attestation",
    )
    _receipt_boundary(
        anatomy_receipt,
        expected_format="bodyrig-photoidentity-anatomy-source-attestation",
        label="Anatomy source attestation",
    )
    if nail_receipt.get("adapter") != "human-source-nail-detail-attestation" or nail_receipt.get("adapter_revision") != "1":
        raise PhotoIdentitySourceChainError("nail source attestation adapter authority changed")
    if (
        anatomy_receipt.get("adapter") != "human-source-anatomy-observability-attestation"
        or anatomy_receipt.get("adapter_revision") != "1"
    ):
        raise PhotoIdentitySourceChainError("anatomy source attestation adapter authority changed")
    if set(nail_receipt.get("attested_domains") or []) != {"fingernails_detail", "toenails_detail"}:
        raise PhotoIdentitySourceChainError("registration requires both fingernail and toenail human source attestation")
    if set(anatomy_receipt.get("attested_domains") or []) != {"body_rear", "torso_chest", "waist_hips"}:
        raise PhotoIdentitySourceChainError("registration requires complete rear/torso/waist human source attestation")
    if (
        anatomy_receipt.get("confirm_rear_view") is not True
        or anatomy_receipt.get("confirm_torso_chest_anatomy_visible") is not True
        or anatomy_receipt.get("confirm_waist_hips_anatomy_visible") is not True
    ):
        raise PhotoIdentitySourceChainError("anatomy receipt lacks explicit human semantic confirmations")

    nail_observations = sweep_root / "nail-attested-evidence" / "photoidentity-observations.json"
    nail_report = sweep_root / "nail-attested-evidence" / "photoidentity-evidence.json"
    validate_authoritative_bundle(
        nail_report,
        nail_observations,
        require_sufficient=False,
        expected_performer_id=str(report["performer_id"]),
        expected_bodyrig_revision=str(report["bodyrig_revision"]),
        expected_baseline_source_manifest_sha256=str(report["baseline_source_manifest_sha256"]),
    )
    if nail_receipt.get("enriched_observation_evidence_sha256") != _sha256(nail_observations):
        raise PhotoIdentitySourceChainError("nail receipt no longer binds exact nail observation evidence")
    if nail_receipt.get("enriched_sufficiency_report_sha256") != _sha256(nail_report):
        raise PhotoIdentitySourceChainError("nail receipt no longer binds exact nail sufficiency report")
    if anatomy_receipt.get("prior_stage") != "nail-attested":
        raise PhotoIdentitySourceChainError("anatomy authority must be composed after nail source attestation")
    if anatomy_receipt.get("prior_observation_evidence_sha256") != _sha256(nail_observations):
        raise PhotoIdentitySourceChainError("anatomy receipt prior observation binding does not match nail authority")
    if anatomy_receipt.get("prior_sufficiency_report_sha256") != _sha256(nail_report):
        raise PhotoIdentitySourceChainError("anatomy receipt prior report binding does not match nail authority")
    if anatomy_receipt.get("enriched_observation_evidence_sha256") != _sha256(observations_file):
        raise PhotoIdentitySourceChainError("anatomy receipt no longer binds exact final observation evidence")
    if anatomy_receipt.get("enriched_sufficiency_report_sha256") != _sha256(report_file):
        raise PhotoIdentitySourceChainError("anatomy receipt no longer binds exact final sufficiency report")

    common = (
        str(report["performer_id"]),
        str(report["bodyrig_revision"]),
    )
    for receipt, label in ((nail_receipt, "nail"), (anatomy_receipt, "anatomy")):
        if (str(receipt.get("performer_id") or ""), str(receipt.get("bodyrig_revision") or "")) != common:
            raise PhotoIdentitySourceChainError(f"{label} receipt performer/revision authority changed")

    fingernails = _selected_claims(
        nail_receipt.get("selected_fingernails"),
        label="Fingernail attestation",
        minimum_scenes=2,
        expected_regions={"left_fingernails", "right_fingernails"},
    )
    toenails = _selected_claims(
        nail_receipt.get("selected_toenails"),
        label="Toenail attestation",
        minimum_scenes=2,
        expected_regions={"left_toenails", "right_toenails"},
    )
    rear = _selected_claims(
        anatomy_receipt.get("selected_body_rear"),
        label="Rear-body attestation",
        minimum_scenes=1,
        expected_regions={"rear_body"},
    )
    torso = _selected_claims(
        anatomy_receipt.get("selected_torso_chest"),
        label="Torso/chest attestation",
        minimum_scenes=2,
        expected_regions={"torso_chest"},
    )
    waist = _selected_claims(
        anatomy_receipt.get("selected_waist_hips"),
        label="Waist/hips attestation",
        minimum_scenes=2,
        expected_regions={"waist_hips"},
    )
    _assert_claims_match(
        observations,
        domain="fingernails_detail",
        expected=fingernails,
        adapter="human-source-nail-detail-attestation",
    )
    _assert_claims_match(
        observations,
        domain="toenails_detail",
        expected=toenails,
        adapter="human-source-nail-detail-attestation",
    )
    _assert_claims_match(
        observations,
        domain="body_rear",
        expected=rear,
        adapter="human-source-anatomy-observability-attestation",
    )
    _assert_claims_match(
        observations,
        domain="torso_chest",
        expected=torso,
        adapter="human-source-anatomy-observability-attestation",
    )
    _assert_claims_match(
        observations,
        domain="waist_hips",
        expected=waist,
        adapter="human-source-anatomy-observability-attestation",
    )
    return {
        "report": report,
        "policy_revision": POLICY_REVISION,
        "sweep_root": str(sweep_root),
        "nail_attestation": str(nail_receipt_path),
        "nail_attestation_sha256": _sha256(nail_receipt_path),
        "anatomy_attestation": str(anatomy_receipt_path),
        "anatomy_attestation_sha256": _sha256(anatomy_receipt_path),
    }
