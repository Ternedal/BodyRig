from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb
from .fidelity_ab import (
    FidelityAbError,
    _accessor_rows,
    _avatar_fingerprints,
    _buffer_view_bytes,
)
from .high_fidelity_package_audit import (
    HighFidelityPackageAuditError,
    _audit_eye_payload,
    _audit_face_payload,
    _audit_hair_payload,
    _audit_hfn_payload,
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
INPUT_FIELDS = {
    "format",
    "version",
    "canonical_body_id",
    "operator_bodyrig_revision",
    "requirement_bodyrig_revision",
    "performer_id",
    "fine_identity_authority_sha256",
    "fine_identity_attestation_sha256",
    "private_manifest_sha256",
    "source_package_sha256",
    "source_avatar_sha256",
    "source_avatar_path",
    "marker_inventory_sha256",
    "marker_inventory_path",
    "domains",
    "source_grounded",
    "generic_guessing_permitted",
    "generative_identity_synthesis",
    "human_review_required",
    "package_application_authority",
    "production_activation",
}
INPUT_EVIDENCE_FIELDS = {
    "reference",
    "scene_id",
    "region",
    "source_ordinal",
    "source_media_sha256",
    "review_image_sha256",
    "source_quality",
    "staged_review_image",
}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

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



def _json_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise PhotoIdentityFineIdentityReconstructionError(
            f"protected payload requires glTF {name} array"
        )
    return value


def _accessor_payload(
    document: Mapping[str, Any],
    binary: bytes,
    index: int,
) -> dict[str, Any]:
    try:
        descriptor, rows = _accessor_rows(document, binary, index)
    except FidelityAbError as exc:
        raise PhotoIdentityFineIdentityReconstructionError(str(exc)) from exc
    return {"descriptor": descriptor, "rows": rows}


def _mesh_payload(
    document: Mapping[str, Any],
    binary: bytes,
    index: int,
) -> dict[str, Any]:
    meshes = _array(document, "meshes")
    if not 0 <= index < len(meshes) or not isinstance(meshes[index], Mapping):
        raise PhotoIdentityFineIdentityReconstructionError(
            "protected mesh index is invalid"
        )
    mesh = meshes[index]
    primitives = mesh.get("primitives")
    if not isinstance(primitives, list):
        raise PhotoIdentityFineIdentityReconstructionError(
            "protected mesh primitives are invalid"
        )
    canonical_primitives: list[dict[str, Any]] = []
    for primitive in primitives:
        if not isinstance(primitive, Mapping):
            raise PhotoIdentityFineIdentityReconstructionError(
                "protected mesh primitive is invalid"
            )
        attributes = primitive.get("attributes")
        if not isinstance(attributes, Mapping):
            raise PhotoIdentityFineIdentityReconstructionError(
                "protected mesh attributes are invalid"
            )
        canonical: dict[str, Any] = {
            "mode": primitive.get("mode", 4),
            "material": primitive.get("material"),
            "extras": primitive.get("extras"),
            "attributes": {
                str(semantic): _accessor_payload(document, binary, int(accessor))
                for semantic, accessor in sorted(attributes.items())
                if isinstance(accessor, int) and not isinstance(accessor, bool)
            },
        }
        indices = primitive.get("indices")
        if isinstance(indices, int) and not isinstance(indices, bool):
            canonical["indices"] = _accessor_payload(document, binary, indices)
        targets = primitive.get("targets")
        if isinstance(targets, list):
            canonical["targets"] = [
                {
                    str(semantic): _accessor_payload(document, binary, int(accessor))
                    for semantic, accessor in sorted(target.items())
                    if isinstance(accessor, int) and not isinstance(accessor, bool)
                }
                for target in targets
                if isinstance(target, Mapping)
            ]
        canonical_primitives.append(canonical)
    return {
        "name": mesh.get("name"),
        "weights": mesh.get("weights"),
        "extras": mesh.get("extras"),
        "primitives": canonical_primitives,
    }


def _texture_indices(value: Any) -> set[int]:
    found: set[int] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "index" and isinstance(item, int) and not isinstance(item, bool):
                found.add(item)
            else:
                found.update(_texture_indices(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_texture_indices(item))
    return found


def _image_payload(
    document: Mapping[str, Any],
    binary: bytes,
    index: int,
) -> dict[str, Any]:
    images = _array(document, "images")
    if not 0 <= index < len(images) or not isinstance(images[index], Mapping):
        raise PhotoIdentityFineIdentityReconstructionError(
            "protected image index is invalid"
        )
    image = dict(images[index])
    payload_sha = None
    if "bufferView" in image:
        try:
            payload = _buffer_view_bytes(document, binary, image["bufferView"])
        except FidelityAbError as exc:
            raise PhotoIdentityFineIdentityReconstructionError(str(exc)) from exc
        payload_sha = hashlib.sha256(payload).hexdigest()
    return {"image": image, "payload_sha256": payload_sha}


def _material_payload(
    document: Mapping[str, Any],
    binary: bytes,
    index: int,
) -> dict[str, Any]:
    materials = _array(document, "materials")
    textures = _array(document, "textures")
    samplers = document.get("samplers")
    sampler_list = samplers if isinstance(samplers, list) else []
    if not 0 <= index < len(materials) or not isinstance(materials[index], Mapping):
        raise PhotoIdentityFineIdentityReconstructionError(
            "protected material index is invalid"
        )
    material = dict(materials[index])
    bound: list[dict[str, Any]] = []
    for texture_index in sorted(_texture_indices(material)):
        if not 0 <= texture_index < len(textures) or not isinstance(textures[texture_index], Mapping):
            raise PhotoIdentityFineIdentityReconstructionError(
                "protected material texture index is invalid"
            )
        texture = dict(textures[texture_index])
        source = texture.get("source")
        sampler = texture.get("sampler")
        bound.append(
            {
                "index": texture_index,
                "texture": texture,
                "sampler": (
                    sampler_list[sampler]
                    if isinstance(sampler, int)
                    and not isinstance(sampler, bool)
                    and 0 <= sampler < len(sampler_list)
                    else None
                ),
                "image": (
                    _image_payload(document, binary, source)
                    if isinstance(source, int) and not isinstance(source, bool)
                    else None
                ),
            }
        )
    return {"material": material, "textures": bound}


def _protected_payload_fingerprints(vrm: bytes) -> dict[str, str]:
    try:
        document, binary = _read_glb(vrm)
    except PbrMaterialError as exc:
        raise PhotoIdentityFineIdentityReconstructionError(str(exc)) from exc
    bodyrig = _bodyrig_metadata(vrm)
    try:
        hair = _audit_hair_payload(document, bodyrig)
        eyes = _audit_eye_payload(document, bodyrig)
        face = _audit_face_payload(document, bodyrig)
        hfn = _audit_hfn_payload(document, binary, bodyrig)
    except HighFidelityPackageAuditError as exc:
        raise PhotoIdentityFineIdentityReconstructionError(
            f"protected payload audit failed: {exc}"
        ) from exc
    if hfn is None:
        raise PhotoIdentityFineIdentityReconstructionError(
            "terminal fine-identity source lacks protected HFN payload"
        )

    hair_value = {
        "mesh": _mesh_payload(document, binary, int(hair["mesh"])),
        "material": _material_payload(document, binary, int(hair["material"])),
    }
    eyes_value = {
        "mesh": _mesh_payload(document, binary, int(eyes["mesh"])),
        "materials": [
            _material_payload(document, binary, int(eyes["surface_material"])),
            _material_payload(document, binary, int(eyes["cornea_material"])),
        ],
    }
    face_value: dict[str, Any] = {
        "mesh": _mesh_payload(document, binary, int(face["mesh"])),
        "materials": [
            _material_payload(document, binary, int(index))
            for index in sorted(face["materials"].values())
        ],
    }
    source_dental = face.get("source_dental")
    if isinstance(source_dental, Mapping):
        face_value["source_dental"] = {
            "mesh": _mesh_payload(document, binary, int(source_dental["mesh"])),
            "materials": [
                _material_payload(document, binary, int(index))
                for index in sorted(source_dental["materials"].values())
            ],
            "roles": list(source_dental["roles"]),
            "source_references": list(source_dental["source_references"]),
        }

    return {
        "hair": _json_sha(hair_value),
        "eyes": _json_sha(eyes_value),
        "face_secondary": _json_sha(face_value),
        "hfn_base_color": str(hfn["base_color_sha256"]),
    }


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



def _canonical_sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise PhotoIdentityFineIdentityReconstructionError(
            f"{label} is not a canonical SHA-256"
        )
    return text


def validate_input_manifest(
    value: Mapping[str, Any],
    *,
    workspace_root: Path,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != INPUT_FIELDS:
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity reconstruction input fields must match v1 exactly"
        )
    if value.get("format") != INPUT_FORMAT or value.get("version") != INPUT_VERSION:
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity reconstruction input format/version mismatch"
        )
    for field, expected in (
        ("source_grounded", True),
        ("generic_guessing_permitted", False),
        ("generative_identity_synthesis", False),
        ("human_review_required", True),
        ("package_application_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected:
            raise PhotoIdentityFineIdentityReconstructionError(
                f"fine-identity reconstruction input authority mismatch: {field}"
            )

    operator_revision = _canonical_revision(value.get("operator_bodyrig_revision"))
    requirement_revision = _canonical_revision(value.get("requirement_bodyrig_revision"))
    for field in (
        "fine_identity_authority_sha256",
        "fine_identity_attestation_sha256",
        "private_manifest_sha256",
        "source_package_sha256",
        "source_avatar_sha256",
        "marker_inventory_sha256",
    ):
        _canonical_sha(value.get(field), label=field)

    root = workspace_root.expanduser().resolve()
    source_avatar_path = (root / "input" / "source-avatar.vrm").resolve()
    marker_path = (root / "input" / "distinctive-marker-inventory.json").resolve()
    if Path(str(value.get("source_avatar_path") or "")).expanduser().resolve() != source_avatar_path:
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity input source avatar path escaped canonical workspace"
        )
    if Path(str(value.get("marker_inventory_path") or "")).expanduser().resolve() != marker_path:
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity input marker inventory path escaped canonical workspace"
        )
    if _sha256_file(source_avatar_path) != value["source_avatar_sha256"]:
        raise PhotoIdentityFineIdentityReconstructionError(
            "staged source avatar no longer matches input authority"
        )
    if _sha256_file(marker_path) != value["marker_inventory_sha256"]:
        raise PhotoIdentityFineIdentityReconstructionError(
            "staged marker inventory no longer matches input authority"
        )

    domains = value.get("domains")
    if not isinstance(domains, Mapping) or set(domains) != set(APPLICATION_DOMAINS):
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity reconstruction input domain set is incomplete"
        )
    source_references: dict[str, list[str]] = {}
    canonical_domains: dict[str, list[dict[str, Any]]] = {}
    for domain in APPLICATION_DOMAINS:
        entries = domains.get(domain)
        if not isinstance(entries, list) or len(entries) < 2:
            raise PhotoIdentityFineIdentityReconstructionError(
                f"{domain} input requires at least two evidence items"
            )
        refs: list[str] = []
        scenes: set[str] = set()
        canonical_entries: list[dict[str, Any]] = []
        domain_root = (root / "input" / domain).resolve()
        for entry in entries:
            if not isinstance(entry, Mapping) or set(entry) != INPUT_EVIDENCE_FIELDS:
                raise PhotoIdentityFineIdentityReconstructionError(
                    f"{domain} input evidence fields are not canonical"
                )
            reference = str(entry.get("reference") or "").strip()
            scene = str(entry.get("scene_id") or "").strip()
            if not reference or reference in refs or not scene:
                raise PhotoIdentityFineIdentityReconstructionError(
                    f"{domain} input evidence identity is invalid"
                )
            staged_path = Path(str(entry.get("staged_review_image") or "")).expanduser().resolve()
            if staged_path.parent != domain_root:
                raise PhotoIdentityFineIdentityReconstructionError(
                    f"{domain} staged review image escaped canonical workspace"
                )
            expected = _canonical_sha(
                entry.get("review_image_sha256"),
                label=f"{domain} review image SHA-256",
            )
            _canonical_sha(
                entry.get("source_media_sha256"),
                label=f"{domain} source media SHA-256",
            )
            if _sha256_file(staged_path) != expected:
                raise PhotoIdentityFineIdentityReconstructionError(
                    f"{domain} staged review image hash drifted: {reference}"
                )
            source_ordinal = entry.get("source_ordinal")
            quality = entry.get("source_quality")
            if isinstance(source_ordinal, bool) or not isinstance(source_ordinal, int) or source_ordinal < 0:
                raise PhotoIdentityFineIdentityReconstructionError(
                    f"{domain} source ordinal is invalid"
                )
            if isinstance(quality, bool) or not isinstance(quality, (int, float)):
                raise PhotoIdentityFineIdentityReconstructionError(
                    f"{domain} source quality is invalid"
                )
            refs.append(reference)
            scenes.add(scene)
            canonical_entries.append(dict(entry))
        if len(scenes) < 2:
            raise PhotoIdentityFineIdentityReconstructionError(
                f"{domain} input requires at least two distinct source scenes"
            )
        source_references[domain] = refs
        canonical_domains[domain] = canonical_entries

    return {
        **dict(value),
        "operator_bodyrig_revision": operator_revision,
        "requirement_bodyrig_revision": requirement_revision,
        "domains": canonical_domains,
        "source_references": source_references,
    }


def read_reconstruction_workspace(
    *,
    workspace: Path,
    config_path: Path,
) -> dict[str, Any]:
    root = workspace.expanduser().resolve()
    input_manifest_path = root / "fine-identity-reconstruction-input.json"
    result_path = root / "adapter-output" / "fine-identity-reconstruction.json"
    candidate_vrm_path = root / "adapter-output" / "fine-identity-candidate.vrm"
    config_raw = _read_json(
        config_path.expanduser().resolve(),
        label="Fine-identity adapter config",
    )
    try:
        config = validate_adapter_config(config_raw)
    except PhotoIdentityFineIdentityAdapterError as exc:
        raise PhotoIdentityFineIdentityReconstructionError(str(exc)) from exc
    prepared = validate_input_manifest(
        _read_json(input_manifest_path, label="Fine-identity reconstruction input"),
        workspace_root=root,
    )
    result = validate_adapter_result(
        result_path=result_path,
        candidate_vrm_path=candidate_vrm_path,
        input_manifest_path=input_manifest_path,
        config=config,
        prepared=prepared,
    )
    return {
        **result,
        "workspace": str(root),
        "input_manifest_path": str(input_manifest_path),
        "candidate_vrm_path": str(candidate_vrm_path),
        "result_path": str(result_path),
        "prepared": prepared,
        "config": config,
    }


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

    source_protected = _protected_payload_fingerprints(source_avatar)
    candidate_protected = _protected_payload_fingerprints(candidate_vrm)
    if candidate_protected != source_protected:
        changed = sorted(
            key
            for key in source_protected
            if candidate_protected.get(key) != source_protected.get(key)
        )
        raise PhotoIdentityFineIdentityReconstructionError(
            "fine-identity reconstruction changed protected promoted payloads: "
            + ", ".join(changed)
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
