from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb
from .fidelity_ab import FidelityAbError, _avatar_fingerprints
from .high_fidelity_package_audit import (
    HighFidelityPackageAuditError,
    audit_high_fidelity_package,
)
from .package import MRBodyError, validate_package
from .photoidentity_fine_identity_adapter import (
    APPLICATION_DOMAINS,
    PhotoIdentityFineIdentityAdapterError,
    _bound_command,
    _revision as _canonical_revision,
    load_application_source_evidence,
    validate_adapter_config,
)

INPUT_FORMAT = "bodyrig-photoidentity-fine-identity-reconstruction-input"
INPUT_VERSION = 1
RESULT_FORMAT = "bodyrig-photoidentity-fine-identity-reconstruction-result"
RESULT_VERSION = 1
RESULT_FIELDS = {
    "format",
    "version",
    "adapter",
    "adapter_revision",
    "operator_bodyrig_revision",
    "requirement_bodyrig_revision",
    "performer_id",
    "input_manifest_sha256",
    "fine_identity_authority_sha256",
    "fine_identity_attestation_sha256",
    "source_package_sha256",
    "source_avatar_sha256",
    "candidate_vrm_sha256",
    "source_references",
    "marker_inventory_sha256",
    "source_grounded",
    "generative_identity_synthesis",
    "rig_preserved",
    "authority_metadata_preserved",
    "geometry_modified",
    "appearance_modified",
    "human_review_required",
    "package_application_authority",
    "production_activation",
}


class PhotoIdentityFineIdentityReconstructionError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotoIdentityFineIdentityReconstructionError(
            f"required fine-identity reconstruction file is missing or symlinked: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityFineIdentityReconstructionError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityFineIdentityReconstructionError(f"{label} must be a JSON object")
    return value


def _package_avatar(path: Path) -> tuple[bytes, str]:
    try:
        validated = validate_package(path)
        with zipfile.ZipFile(path, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise PhotoIdentityFineIdentityReconstructionError(
            "source HFN package is invalid or lacks avatar.vrm"
        ) from exc
    return avatar, str(validated.manifest["id"])


def _bodyrig_metadata(vrm: bytes) -> dict[str, Any]:
    try:
        document, _binary = _read_glb(vrm)
    except PbrMaterialError as exc:
        raise PhotoIdentityFineIdentityReconstructionError(str(exc)) from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    if not isinstance(bodyrig, Mapping):
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity avatar lacks canonical BodyRig metadata"
        )
    return dict(bodyrig)


def _source_authority(source_package: Path) -> tuple[dict[str, Any], bytes, str]:
    try:
        audit = audit_high_fidelity_package(source_package)
    except HighFidelityPackageAuditError as exc:
        raise PhotoIdentityFineIdentityReconstructionError(str(exc)) from exc
    components = audit.get("components")
    fine = audit.get("fine_identity")
    requirement = fine.get("requirement") if isinstance(fine, Mapping) else None
    if (
        audit.get("fine_identity_required") is not True
        or audit.get("fine_identity_ready") is not False
        or audit.get("high_fidelity_ready") is not False
        or audit.get("top_level_blockers") != ["fine_identity"]
        or not isinstance(components, Mapping)
        or not components
        or any(value != "complete" for value in components.values())
        or not isinstance(requirement, Mapping)
        or (isinstance(fine, Mapping) and fine.get("application") is not None)
    ):
        raise PhotoIdentityFineIdentityReconstructionError(
            "source HFN package is not the exact component-complete/fine-identity-pending state"
        )
    avatar, body_id = _package_avatar(source_package)
    return dict(requirement), avatar, body_id


def prepare_input_workspace(
    *,
    source_package_path: Path,
    private_manifest_path: Path,
    attestation_path: Path,
    output_dir: Path,
    operator_bodyrig_revision: str,
) -> dict[str, Any]:
    source_package = source_package_path.expanduser().resolve()
    root = output_dir.expanduser().resolve()
    if root.exists():
        raise PhotoIdentityFineIdentityReconstructionError(
            f"fine-identity reconstruction workspace already exists: {root}"
        )

    requirement, source_avatar, body_id = _source_authority(source_package)
    requirement_revision = str(requirement["bodyrigRevision"])
    try:
        attestation, manifest, grouped = load_application_source_evidence(
            private_manifest_path=private_manifest_path.expanduser().resolve(),
            attestation_path=attestation_path.expanduser().resolve(),
            bodyrig_revision=requirement_revision,
        )
    except PhotoIdentityFineIdentityAdapterError as exc:
        raise PhotoIdentityFineIdentityReconstructionError(str(exc)) from exc

    attestation_path = attestation_path.expanduser().resolve()
    attestation_sha = _sha256_file(attestation_path)
    if attestation_sha != requirement["fineIdentityAttestationSha256"]:
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity attestation bytes do not match the source package requirement"
        )

    input_dir = root / "input"
    adapter_output = root / "adapter-output"
    root.mkdir(parents=True, exist_ok=False)
    input_dir.mkdir()
    adapter_output.mkdir()
    try:
        source_avatar_path = input_dir / "source-avatar.vrm"
        source_avatar_path.write_bytes(source_avatar)
        if _sha256_file(source_avatar_path) != _sha256_bytes(source_avatar):
            raise PhotoIdentityFineIdentityReconstructionError(
                "staged source avatar hash mismatch"
            )

        staged_by_domain: dict[str, list[dict[str, Any]]] = {}
        source_references: dict[str, list[str]] = {}
        ordinal = 0
        for domain in APPLICATION_DOMAINS:
            staged_by_domain[domain] = []
            source_references[domain] = []
            domain_dir = input_dir / domain
            domain_dir.mkdir()
            for entry in sorted(
                grouped[domain],
                key=lambda item: (
                    str(item["scene_id"]),
                    int(item["source_ordinal"]),
                    str(item["reference"]),
                ),
            ):
                ordinal += 1
                source = Path(str(entry["review_image_path"])).expanduser().resolve()
                expected = str(entry["review_image_sha256"]).lower()
                suffix = source.suffix.lower()
                if not suffix or len(suffix) > 10:
                    suffix = ".bin"
                destination = domain_dir / f"{ordinal:03d}-{expected[:16]}{suffix}"
                shutil.copyfile(source, destination)
                if _sha256_file(destination) != expected:
                    raise PhotoIdentityFineIdentityReconstructionError(
                        f"staged review image hash mismatch: {entry['reference']}"
                    )
                staged = {
                    "reference": str(entry["reference"]),
                    "scene_id": str(entry["scene_id"]),
                    "region": str(entry["region"]),
                    "source_ordinal": int(entry["source_ordinal"]),
                    "source_media_sha256": str(entry["source_media_sha256"]).lower(),
                    "review_image_sha256": expected,
                    "source_quality": entry["source_quality"],
                    "staged_review_image": str(destination),
                }
                staged_by_domain[domain].append(staged)
                source_references[domain].append(str(entry["reference"]))

        marker_source = Path(str(manifest["marker_inventory_path"])).expanduser().resolve()
        marker_destination = input_dir / "distinctive-marker-inventory.json"
        shutil.copyfile(marker_source, marker_destination)
        marker_sha = _sha256_file(marker_destination)
        if marker_sha != str(attestation["marker_inventory_sha256"]).lower():
            raise PhotoIdentityFineIdentityReconstructionError(
                "staged distinctive-marker inventory hash mismatch"
            )

        value = {
            "format": INPUT_FORMAT,
            "version": INPUT_VERSION,
            "canonical_body_id": body_id,
            "operator_bodyrig_revision": _canonical_revision(operator_bodyrig_revision),
            "requirement_bodyrig_revision": requirement_revision,
            "performer_id": str(attestation["performer_id"]),
            "fine_identity_authority_sha256": requirement["fineIdentityAuthoritySha256"],
            "fine_identity_attestation_sha256": attestation_sha,
            "private_manifest_sha256": _sha256_file(private_manifest_path.expanduser().resolve()),
            "source_package_sha256": _sha256_file(source_package),
            "source_avatar_sha256": _sha256_bytes(source_avatar),
            "source_avatar_path": str(source_avatar_path),
            "marker_inventory_sha256": marker_sha,
            "marker_inventory_path": str(marker_destination),
            "domains": staged_by_domain,
            "source_grounded": True,
            "generic_guessing_permitted": False,
            "generative_identity_synthesis": False,
            "human_review_required": True,
            "package_application_authority": False,
            "production_activation": False,
        }
        input_manifest = root / "fine-identity-reconstruction-input.json"
        input_manifest.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            **value,
            "input_manifest_path": str(input_manifest),
            "adapter_output_dir": str(adapter_output),
            "source_references": source_references,
        }
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def validate_adapter_result(
    *,
    result_path: Path,
    candidate_vrm_path: Path,
    input_manifest_path: Path,
    config: Mapping[str, Any],
    prepared: Mapping[str, Any],
) -> dict[str, Any]:
    result = _read_json(result_path, label="Fine-identity reconstruction result")
    if set(result) != RESULT_FIELDS:
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity reconstruction result fields must match v1 exactly"
        )
    if result.get("format") != RESULT_FORMAT or result.get("version") != RESULT_VERSION:
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity reconstruction result format/version mismatch"
        )

    candidate_vrm = candidate_vrm_path.read_bytes()
    source_avatar = Path(str(prepared["source_avatar_path"])).read_bytes()
    expected = {
        "adapter": str(config["adapter"]),
        "adapter_revision": str(config["revision"]),
        "operator_bodyrig_revision": str(prepared["operator_bodyrig_revision"]),
        "requirement_bodyrig_revision": str(prepared["requirement_bodyrig_revision"]),
        "performer_id": str(prepared["performer_id"]),
        "input_manifest_sha256": _sha256_file(input_manifest_path),
        "fine_identity_authority_sha256": str(prepared["fine_identity_authority_sha256"]),
        "fine_identity_attestation_sha256": str(prepared["fine_identity_attestation_sha256"]),
        "source_package_sha256": str(prepared["source_package_sha256"]),
        "source_avatar_sha256": str(prepared["source_avatar_sha256"]),
        "candidate_vrm_sha256": _sha256_file(candidate_vrm_path),
        "source_references": dict(prepared["source_references"]),
        "marker_inventory_sha256": str(prepared["marker_inventory_sha256"]),
        "source_grounded": True,
        "generative_identity_synthesis": False,
        "rig_preserved": True,
        "authority_metadata_preserved": True,
        "geometry_modified": True,
        "appearance_modified": True,
        "human_review_required": True,
        "package_application_authority": False,
        "production_activation": False,
    }
    for field, expected_value in expected.items():
        if result.get(field) != expected_value:
            raise PhotoIdentityFineIdentityReconstructionError(
                f"fine-identity reconstruction result mismatch: {field}"
            )

    try:
        source_fp = _avatar_fingerprints(source_avatar)
        candidate_fp = _avatar_fingerprints(candidate_vrm)
    except FidelityAbError as exc:
        raise PhotoIdentityFineIdentityReconstructionError(
            f"fine-identity candidate fingerprint validation failed: {exc}"
        ) from exc
    if source_fp["rig_sha256"] != candidate_fp["rig_sha256"]:
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity reconstruction changed canonical rig authority"
        )
    if source_fp["geometry_surface_sha256"] == candidate_fp["geometry_surface_sha256"]:
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity reconstruction did not change required geometry"
        )
    if source_fp["appearance_global_sha256"] == candidate_fp["appearance_global_sha256"]:
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity reconstruction did not change required appearance"
        )

    source_bodyrig = _bodyrig_metadata(source_avatar)
    candidate_bodyrig = _bodyrig_metadata(candidate_vrm)
    if candidate_bodyrig.get("fineIdentityApplication") is not None:
        raise PhotoIdentityFineIdentityReconstructionError(
            "adapter candidate may not self-grant fineIdentityApplication authority"
        )
    if candidate_bodyrig != source_bodyrig:
        raise PhotoIdentityFineIdentityReconstructionError(
            "adapter candidate changed existing BodyRig authority metadata"
        )
    return dict(result)


def run_reconstruction(
    *,
    source_package_path: Path,
    private_manifest_path: Path,
    attestation_path: Path,
    config_path: Path,
    output_dir: Path,
    operator_bodyrig_revision: str,
) -> dict[str, Any]:
    config_raw = _read_json(
        config_path.expanduser().resolve(),
        label="Fine-identity adapter config",
    )
    try:
        config = validate_adapter_config(config_raw)
    except PhotoIdentityFineIdentityAdapterError as exc:
        raise PhotoIdentityFineIdentityReconstructionError(str(exc)) from exc

    prepared = prepare_input_workspace(
        source_package_path=source_package_path,
        private_manifest_path=private_manifest_path,
        attestation_path=attestation_path,
        output_dir=output_dir,
        operator_bodyrig_revision=operator_bodyrig_revision,
    )
    root = output_dir.expanduser().resolve()
    input_manifest = Path(str(prepared["input_manifest_path"]))
    adapter_output = Path(str(prepared["adapter_output_dir"]))
    command = _bound_command(config["command"], input_manifest, adapter_output)
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=int(config["timeout_seconds"]),
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-4000:]
            raise PhotoIdentityFineIdentityReconstructionError(
                f"fine-identity reconstruction adapter failed ({completed.returncode}): {detail}"
            )
        result_path = adapter_output / "fine-identity-reconstruction.json"
        candidate_vrm_path = adapter_output / "fine-identity-candidate.vrm"
        result = validate_adapter_result(
            result_path=result_path,
            candidate_vrm_path=candidate_vrm_path,
            input_manifest_path=input_manifest,
            config=config,
            prepared=prepared,
        )
        return {
            **result,
            "workspace": str(root),
            "input_manifest_path": str(input_manifest),
            "candidate_vrm_path": str(candidate_vrm_path),
            "result_path": str(result_path),
        }
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
