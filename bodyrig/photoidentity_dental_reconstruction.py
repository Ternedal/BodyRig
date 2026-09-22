from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb
from .photoidentity_fine_identity_attestation import (
    PRIVATE_ENTRY_FIELDS,
    PRIVATE_FORMAT,
    PRIVATE_TOP_FIELDS,
    PRIVATE_VERSION,
    PUBLIC_ENTRY_FIELDS,
    PhotoIdentityFineIdentityAttestationError,
    read_attestation,
)

CONFIG_FORMAT = "bodyrig-photoidentity-dental-reconstruction-adapter-config"
CONFIG_VERSION = 1
INPUT_FORMAT = "bodyrig-photoidentity-dental-reconstruction-input"
INPUT_VERSION = 1
RESULT_FORMAT = "bodyrig-photoidentity-dental-reconstruction-result"
RESULT_VERSION = 1
DOMAIN = "oral_teeth_detail"
NODE_NAME = "BodyRigSourceDentalIdentity"
MESH_NAME = "BodyRigSourceDentalIdentityMesh"
MOUTH_MATERIAL = "BodyRigSourceMouthInterior"
DENTAL_MATERIAL = "BodyRigSourceDentalSurface"
DENTAL_IMAGE = "BodyRigSourceDentalTexture"
REQUIRED_ROLES = ("mouth_interior", "upper_teeth", "lower_teeth")
ADAPTER_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

CONFIG_FIELDS = {
    "format",
    "version",
    "adapter",
    "revision",
    "command",
    "capabilities",
    "timeout_seconds",
}
CAPABILITY_FIELDS = {
    "oral_teeth_geometry",
    "oral_teeth_appearance",
    "source_grounded",
    "generative_identity_synthesis",
}
RESULT_FIELDS = {
    "format",
    "version",
    "adapter",
    "adapter_revision",
    "bodyrig_revision",
    "performer_id",
    "input_manifest_sha256",
    "fine_identity_attestation_sha256",
    "dental_vrm_sha256",
    "source_references",
    "source_derived_dental_identity",
    "generic_secondary_anatomy",
    "generative_identity_synthesis",
    "mouth_interior_source_derived",
    "upper_teeth_source_derived",
    "lower_teeth_source_derived",
    "appearance_source_derived",
    "human_review_required",
    "promotion_authority",
    "production_activation",
}


class PhotoIdentityDentalReconstructionError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotoIdentityDentalReconstructionError(f"required dental file is missing or symlinked: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise PhotoIdentityDentalReconstructionError(f"{label} is not a canonical SHA-256")
    return text


def _revision(value: Any, *, label: str = "BodyRig revision") -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise PhotoIdentityDentalReconstructionError(f"{label} is not a canonical Git SHA")
    return text


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityDentalReconstructionError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityDentalReconstructionError(f"{label} must be a JSON object")
    return value


def validate_adapter_config(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != CONFIG_FIELDS:
        raise PhotoIdentityDentalReconstructionError("dental adapter config fields must match v1 exactly")
    version = value.get("version")
    if (
        value.get("format") != CONFIG_FORMAT
        or isinstance(version, bool)
        or version != CONFIG_VERSION
    ):
        raise PhotoIdentityDentalReconstructionError("unsupported dental adapter config format/version")
    adapter = str(value.get("adapter") or "").strip()
    revision = str(value.get("revision") or "").strip()
    if not ADAPTER_RE.fullmatch(adapter):
        raise PhotoIdentityDentalReconstructionError("dental adapter name is invalid")
    if not revision or len(revision) > 160:
        raise PhotoIdentityDentalReconstructionError("dental adapter revision is invalid")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 32
        or any(not isinstance(item, str) or not item or len(item) > 2000 for item in command)
    ):
        raise PhotoIdentityDentalReconstructionError("dental adapter command must be 1..32 non-empty argv strings")
    capabilities = value.get("capabilities")
    if not isinstance(capabilities, Mapping) or set(capabilities) != CAPABILITY_FIELDS:
        raise PhotoIdentityDentalReconstructionError("dental adapter capabilities must match v1 exactly")
    if any(type(capabilities.get(field)) is not bool for field in CAPABILITY_FIELDS):
        raise PhotoIdentityDentalReconstructionError("dental adapter capabilities must be booleans")
    if (
        capabilities.get("oral_teeth_geometry") is not True
        or capabilities.get("oral_teeth_appearance") is not True
        or capabilities.get("source_grounded") is not True
        or capabilities.get("generative_identity_synthesis") is not False
    ):
        raise PhotoIdentityDentalReconstructionError(
            "dental adapter must explicitly provide source-grounded geometry+appearance without generative identity synthesis"
        )
    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
        raise PhotoIdentityDentalReconstructionError("dental adapter timeout_seconds must be in 1..86400")
    _bound_command(command, Path("input.json"), Path("output"))
    return dict(value)


def _bound_command(command: Sequence[str], input_manifest: Path, output_dir: Path) -> list[str]:
    argv = list(command)
    bindings = {
        "--bodyrig-dental-input": str(input_manifest),
        "--bodyrig-dental-output": str(output_dir),
    }
    for flag, replacement in bindings.items():
        indices = [index for index, item in enumerate(argv) if item == flag]
        if len(indices) != 1:
            raise PhotoIdentityDentalReconstructionError(
                f"dental adapter command requires exactly one {flag} binding"
            )
        index = indices[0]
        if index + 1 >= len(argv):
            raise PhotoIdentityDentalReconstructionError(f"dental adapter {flag} binding is incomplete")
        argv[index + 1] = replacement
    return argv


def _public_projection(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {field: entry[field] for field in PUBLIC_ENTRY_FIELDS}


def load_oral_source_evidence(
    *,
    private_manifest_path: Path,
    attestation_path: Path,
    bodyrig_revision: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    revision = _revision(bodyrig_revision)
    try:
        attestation = read_attestation(
            attestation_path,
            expected_bodyrig_revision=revision,
        )
    except PhotoIdentityFineIdentityAttestationError as exc:
        raise PhotoIdentityDentalReconstructionError(str(exc)) from exc
    if attestation.get("confirm_oral_teeth_photoidentity") is not True:
        raise PhotoIdentityDentalReconstructionError("fine-identity attestation lacks oral/teeth confirmation")
    if attestation.get("source_grounded") is not True or attestation.get("generic_guessing_permitted") is not False:
        raise PhotoIdentityDentalReconstructionError("fine-identity attestation crossed source-grounded oral/teeth boundary")

    manifest = _read_json(private_manifest_path, label="Private fine-identity review manifest")
    if set(manifest) != PRIVATE_TOP_FIELDS:
        raise PhotoIdentityDentalReconstructionError("private fine-identity review manifest fields must match v1 exactly")
    if manifest.get("format") != PRIVATE_FORMAT or manifest.get("version") != PRIVATE_VERSION:
        raise PhotoIdentityDentalReconstructionError("private fine-identity review manifest format/version mismatch")
    if str(manifest.get("performer_id") or "") != str(attestation.get("performer_id") or ""):
        raise PhotoIdentityDentalReconstructionError("private fine-identity manifest performer mismatch")
    if str(manifest.get("bodyrig_revision") or "").lower() != revision:
        raise PhotoIdentityDentalReconstructionError("private fine-identity manifest BodyRig revision mismatch")

    selected = attestation.get("selected_evidence")
    if not isinstance(selected, list):
        raise PhotoIdentityDentalReconstructionError("fine-identity attestation selected evidence is invalid")
    public_by_reference = {
        str(item.get("reference") or ""): dict(item)
        for item in selected
        if isinstance(item, Mapping) and item.get("domain") == DOMAIN
    }
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise PhotoIdentityDentalReconstructionError("private fine-identity evidence list is invalid")

    oral: list[dict[str, Any]] = []
    scenes: set[str] = set()
    for raw in entries:
        if not isinstance(raw, Mapping) or set(raw) != PRIVATE_ENTRY_FIELDS:
            raise PhotoIdentityDentalReconstructionError("private fine-identity evidence entry fields are invalid")
        if raw.get("domain") != DOMAIN:
            continue
        reference = str(raw.get("reference") or "").strip()
        public = public_by_reference.get(reference)
        if not reference or public is None:
            raise PhotoIdentityDentalReconstructionError(
                "private oral/teeth evidence is not present in the exact public attestation"
            )
        projected = _public_projection(raw)
        if projected != public:
            raise PhotoIdentityDentalReconstructionError(
                f"private/public oral/teeth evidence mismatch: {reference}"
            )
        review_image = Path(str(raw.get("review_image_path") or "")).expanduser().resolve()
        if _sha256_file(review_image) != _sha(raw.get("review_image_sha256"), label="review image SHA-256"):
            raise PhotoIdentityDentalReconstructionError(
                f"oral/teeth review image bytes changed after attestation: {reference}"
            )
        source_media = Path(str(raw.get("source_media_path") or "")).expanduser().resolve()
        if _sha256_file(source_media) != _sha(raw.get("source_media_sha256"), label="source media SHA-256"):
            raise PhotoIdentityDentalReconstructionError(
                f"oral/teeth source media bytes changed after attestation: {reference}"
            )
        oral.append(dict(raw))
        scenes.add(str(raw.get("scene_id") or ""))

    if len(scenes) < 2 or len(oral) < 2:
        raise PhotoIdentityDentalReconstructionError(
            "source-derived dental reconstruction requires at least two distinct reviewed oral/teeth scenes"
        )
    if set(public_by_reference) != {str(item["reference"]) for item in oral}:
        raise PhotoIdentityDentalReconstructionError(
            "public oral/teeth attestation contains evidence missing from the private manifest"
        )
    return manifest, attestation, sorted(
        oral,
        key=lambda item: (str(item["scene_id"]), int(item["source_ordinal"]), str(item["reference"])),
    )


def prepare_input_workspace(
    *,
    private_manifest_path: Path,
    attestation_path: Path,
    output_dir: Path,
    bodyrig_revision: str,
) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise PhotoIdentityDentalReconstructionError(f"dental reconstruction workspace already exists: {output_dir}")
    manifest, attestation, oral = load_oral_source_evidence(
        private_manifest_path=private_manifest_path.expanduser().resolve(),
        attestation_path=attestation_path.expanduser().resolve(),
        bodyrig_revision=bodyrig_revision,
    )
    revision = _revision(bodyrig_revision)
    input_dir = output_dir / "input"
    adapter_output = output_dir / "adapter-output"
    output_dir.mkdir(parents=True, exist_ok=False)
    input_dir.mkdir()
    adapter_output.mkdir()
    try:
        staged: list[dict[str, Any]] = []
        for index, entry in enumerate(oral, start=1):
            source = Path(str(entry["review_image_path"])).expanduser().resolve()
            suffix = source.suffix.lower()
            if not suffix or len(suffix) > 10:
                suffix = ".bin"
            expected = _sha(entry["review_image_sha256"], label="review image SHA-256")
            destination = input_dir / f"{index:02d}-{expected[:16]}{suffix}"
            shutil.copyfile(source, destination)
            if _sha256_file(destination) != expected:
                raise PhotoIdentityDentalReconstructionError(
                    f"staged oral/teeth review image hash mismatch: {entry['reference']}"
                )
            staged.append(
                {
                    "reference": str(entry["reference"]),
                    "scene_id": str(entry["scene_id"]),
                    "region": str(entry["region"]),
                    "source_ordinal": int(entry["source_ordinal"]),
                    "source_media_sha256": _sha(entry["source_media_sha256"], label="source media SHA-256"),
                    "review_image_sha256": expected,
                    "source_quality": entry["source_quality"],
                    "staged_review_image": str(destination),
                }
            )
        value = {
            "format": INPUT_FORMAT,
            "version": INPUT_VERSION,
            "performer_id": str(attestation["performer_id"]),
            "bodyrig_revision": revision,
            "domain": DOMAIN,
            "private_manifest_sha256": _sha256_file(private_manifest_path.expanduser().resolve()),
            "fine_identity_attestation_sha256": _sha256_file(attestation_path.expanduser().resolve()),
            "evidence": staged,
            "distinct_scene_count": len({item["scene_id"] for item in staged}),
            "source_grounded": True,
            "generic_guessing_permitted": False,
            "generative_identity_synthesis": False,
            "human_review_required": True,
            "production_activation": False,
        }
        input_manifest = output_dir / "dental-reconstruction-input.json"
        input_manifest.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return {
            **value,
            "input_manifest_path": str(input_manifest),
            "adapter_output_dir": str(adapter_output),
        }
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def _array(document: Mapping[str, Any], name: str) -> list[Any]:
    value = document.get(name)
    if not isinstance(value, list):
        raise PhotoIdentityDentalReconstructionError(f"dental VRM requires glTF {name} array")
    return value


def _named_index(document: Mapping[str, Any], array_name: str, name: str) -> int:
    values = _array(document, array_name)
    matches = [
        index
        for index, item in enumerate(values)
        if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(matches) != 1:
        raise PhotoIdentityDentalReconstructionError(
            f"dental VRM requires exactly one {array_name} entry named {name}"
        )
    return matches[0]


def validate_dental_vrm(vrm_bytes: bytes) -> dict[str, Any]:
    try:
        document, _binary = _read_glb(vrm_bytes)
    except PbrMaterialError as exc:
        raise PhotoIdentityDentalReconstructionError(str(exc)) from exc
    node_index = _named_index(document, "nodes", NODE_NAME)
    mesh_index = _named_index(document, "meshes", MESH_NAME)
    mouth_material = _named_index(document, "materials", MOUTH_MATERIAL)
    dental_material = _named_index(document, "materials", DENTAL_MATERIAL)
    image_index = _named_index(document, "images", DENTAL_IMAGE)

    node = _array(document, "nodes")[node_index]
    if not isinstance(node, Mapping) or node.get("mesh") != mesh_index or node.get("skin") != 0:
        raise PhotoIdentityDentalReconstructionError("dental VRM node is not bound to canonical mesh/skin 0")
    mesh = _array(document, "meshes")[mesh_index]
    primitives = mesh.get("primitives") if isinstance(mesh, Mapping) else None
    if not isinstance(primitives, list) or len(primitives) != len(REQUIRED_ROLES):
        raise PhotoIdentityDentalReconstructionError("dental VRM must contain exactly mouth/upper/lower primitives")

    seen_roles: set[str] = set()
    for primitive in primitives:
        if not isinstance(primitive, Mapping) or primitive.get("mode", 4) != 4:
            raise PhotoIdentityDentalReconstructionError("dental VRM primitive is invalid")
        extras = primitive.get("extras")
        role = extras.get("bodyrigDentalRole") if isinstance(extras, Mapping) else None
        if role not in REQUIRED_ROLES or role in seen_roles:
            raise PhotoIdentityDentalReconstructionError("dental VRM primitive role is missing/duplicated")
        attrs = primitive.get("attributes")
        required_attrs = {"POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"}
        if not isinstance(attrs, Mapping) or set(attrs) != required_attrs:
            raise PhotoIdentityDentalReconstructionError(f"dental VRM {role} attributes are not canonical")
        if not isinstance(primitive.get("indices"), int) or isinstance(primitive.get("indices"), bool):
            raise PhotoIdentityDentalReconstructionError(f"dental VRM {role} indices are invalid")
        expected_material = mouth_material if role == "mouth_interior" else dental_material
        if primitive.get("material") != expected_material:
            raise PhotoIdentityDentalReconstructionError(f"dental VRM {role} material binding is invalid")
        seen_roles.add(str(role))
    if seen_roles != set(REQUIRED_ROLES):
        raise PhotoIdentityDentalReconstructionError("dental VRM role set is incomplete")

    materials = _array(document, "materials")
    dental = materials[dental_material]
    pbr = dental.get("pbrMetallicRoughness") if isinstance(dental, Mapping) else None
    texture_info = pbr.get("baseColorTexture") if isinstance(pbr, Mapping) else None
    texture_index = texture_info.get("index") if isinstance(texture_info, Mapping) else None
    textures = _array(document, "textures")
    if (
        isinstance(texture_index, bool)
        or not isinstance(texture_index, int)
        or not 0 <= texture_index < len(textures)
        or not isinstance(textures[texture_index], Mapping)
        or textures[texture_index].get("source") != image_index
    ):
        raise PhotoIdentityDentalReconstructionError("dental VRM source texture is not bound to dental material")

    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, Mapping) else None
    metadata = bodyrig.get("dentalSourceRuntime") if isinstance(bodyrig, Mapping) else None
    if not isinstance(metadata, Mapping):
        raise PhotoIdentityDentalReconstructionError("dental VRM lacks dentalSourceRuntime metadata")
    if (
        metadata.get("sourceDerivedDentalIdentity") is not True
        or metadata.get("genericSecondaryAnatomy") is not False
        or metadata.get("generativeIdentitySynthesis") is not False
        or metadata.get("humanReviewRequired") is not True
        or metadata.get("promotionAuthority") is not False
        or metadata.get("productionActivation") is not False
    ):
        raise PhotoIdentityDentalReconstructionError("dental VRM source-derived authority boundary is invalid")
    return {
        "node_index": node_index,
        "mesh_index": mesh_index,
        "mouth_material_index": mouth_material,
        "dental_material_index": dental_material,
        "image_index": image_index,
        "metadata": dict(metadata),
    }


def validate_adapter_result(
    *,
    result_path: Path,
    vrm_path: Path,
    input_manifest_path: Path,
    config: Mapping[str, Any],
    performer_id: str,
    bodyrig_revision: str,
    attestation_sha256: str,
    source_references: Sequence[str],
) -> dict[str, Any]:
    result = _read_json(result_path, label="Dental reconstruction result")
    if set(result) != RESULT_FIELDS:
        raise PhotoIdentityDentalReconstructionError("dental reconstruction result fields must match v1 exactly")
    if result.get("format") != RESULT_FORMAT or result.get("version") != RESULT_VERSION:
        raise PhotoIdentityDentalReconstructionError("dental reconstruction result format/version mismatch")
    expected = {
        "adapter": str(config["adapter"]),
        "adapter_revision": str(config["revision"]),
        "bodyrig_revision": _revision(bodyrig_revision),
        "performer_id": str(performer_id),
        "input_manifest_sha256": _sha256_file(input_manifest_path),
        "fine_identity_attestation_sha256": _sha(attestation_sha256, label="fine-identity attestation SHA-256"),
        "dental_vrm_sha256": _sha256_file(vrm_path),
        "source_references": list(source_references),
        "source_derived_dental_identity": True,
        "generic_secondary_anatomy": False,
        "generative_identity_synthesis": False,
        "mouth_interior_source_derived": True,
        "upper_teeth_source_derived": True,
        "lower_teeth_source_derived": True,
        "appearance_source_derived": True,
        "human_review_required": True,
        "promotion_authority": False,
        "production_activation": False,
    }
    for field, expected_value in expected.items():
        if result.get(field) != expected_value:
            raise PhotoIdentityDentalReconstructionError(
                f"dental reconstruction result mismatch: {field}"
            )
    vrm = vrm_path.read_bytes()
    detail = validate_dental_vrm(vrm)
    metadata = detail["metadata"]
    for field, expected_value in (
        ("adapter", expected["adapter"]),
        ("adapterRevision", expected["adapter_revision"]),
        ("bodyrigRevision", expected["bodyrig_revision"]),
        ("performerId", expected["performer_id"]),
        ("inputManifestSha256", expected["input_manifest_sha256"]),
        ("fineIdentityAttestationSha256", expected["fine_identity_attestation_sha256"]),
    ):
        if metadata.get(field) != expected_value:
            raise PhotoIdentityDentalReconstructionError(
                f"dental VRM metadata mismatch: {field}"
            )
    return result


def run_reconstruction(
    *,
    private_manifest_path: Path,
    attestation_path: Path,
    config_path: Path,
    output_dir: Path,
    bodyrig_revision: str,
) -> dict[str, Any]:
    revision = _revision(bodyrig_revision)
    config = validate_adapter_config(_read_json(config_path.expanduser().resolve(), label="Dental adapter config"))
    prepared = prepare_input_workspace(
        private_manifest_path=private_manifest_path,
        attestation_path=attestation_path,
        output_dir=output_dir,
        bodyrig_revision=revision,
    )
    root = output_dir.expanduser().resolve()
    input_manifest = Path(prepared["input_manifest_path"])
    adapter_output = Path(prepared["adapter_output_dir"])
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
            raise PhotoIdentityDentalReconstructionError(
                f"dental reconstruction adapter failed ({completed.returncode}): {detail}"
            )
        result_path = adapter_output / "dental-reconstruction.json"
        vrm_path = adapter_output / "dental-source.vrm"
        result = validate_adapter_result(
            result_path=result_path,
            vrm_path=vrm_path,
            input_manifest_path=input_manifest,
            config=config,
            performer_id=str(prepared["performer_id"]),
            bodyrig_revision=revision,
            attestation_sha256=str(prepared["fine_identity_attestation_sha256"]),
            source_references=[str(item["reference"]) for item in prepared["evidence"]],
        )
        return {
            **result,
            "workspace": str(root),
            "input_manifest_path": str(input_manifest),
            "dental_vrm_path": str(vrm_path),
            "result_path": str(result_path),
        }
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a private source-derived oral/teeth reconstruction candidate from attested PhotoIdentity evidence."
    )
    parser.add_argument("--private-manifest", required=True)
    parser.add_argument("--attestation", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)
    try:
        value = run_reconstruction(
            private_manifest_path=Path(args.private_manifest),
            attestation_path=Path(args.attestation),
            config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            bodyrig_revision=args.bodyrig_revision,
        )
    except (OSError, subprocess.SubprocessError, PhotoIdentityDentalReconstructionError) as exc:
        print(f"BodyRig photoidentity dental reconstruction: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "BodyRig photoidentity dental reconstruction: CANDIDATE | "
        f"adapter={value['adapter']} | sources={len(value['source_references'])} | "
        "source_derived=true | generic=false | human_review=true | promotion=false | production=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
