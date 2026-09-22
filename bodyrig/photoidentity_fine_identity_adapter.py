from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .fine_identity_application import REQUIRED_DOMAINS
from .photoidentity_fine_identity_attestation import (
    PRIVATE_ENTRY_FIELDS,
    PRIVATE_FORMAT,
    PRIVATE_TOP_FIELDS,
    PRIVATE_VERSION,
    PUBLIC_ENTRY_FIELDS,
    PhotoIdentityFineIdentityAttestationError,
    read_attestation,
)

CONFIG_FORMAT = "bodyrig-photoidentity-fine-identity-application-adapter-config"
CONFIG_VERSION = 1
INPUT_FORMAT = "bodyrig-photoidentity-fine-identity-application-input"
INPUT_VERSION = 1
ADAPTER_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

APPLICATION_DOMAINS = {
    domain: minimum
    for domain, minimum in REQUIRED_DOMAINS.items()
    if domain != "oral_teeth_detail"
}

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
    "domains",
    "source_grounded",
    "generative_identity_synthesis",
    "preserves_rig",
    "preserves_source_derived_dental_identity",
    "preserves_hfn_authority",
}
DOMAIN_CAPABILITY_FIELDS = {"geometry", "appearance"}


class PhotoIdentityFineIdentityAdapterError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise PhotoIdentityFineIdentityAdapterError(
            f"fine-identity application evidence file is missing or symlinked: {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _revision(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise PhotoIdentityFineIdentityAdapterError("BodyRig revision is not a canonical Git SHA")
    return text


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityFineIdentityAdapterError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityFineIdentityAdapterError(f"{label} must be a JSON object")
    return value


def _bound_command(command: Sequence[str], input_manifest: Path, output_dir: Path) -> list[str]:
    argv = list(command)
    bindings = {
        "--bodyrig-fine-identity-input": str(input_manifest),
        "--bodyrig-fine-identity-output": str(output_dir),
    }
    for flag, replacement in bindings.items():
        indices = [index for index, item in enumerate(argv) if item == flag]
        if len(indices) != 1:
            raise PhotoIdentityFineIdentityAdapterError(
                f"fine-identity adapter command requires exactly one {flag} binding"
            )
        index = indices[0]
        if index + 1 >= len(argv):
            raise PhotoIdentityFineIdentityAdapterError(
                f"fine-identity adapter {flag} binding is incomplete"
            )
        argv[index + 1] = replacement
    return argv


def validate_adapter_config(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != CONFIG_FIELDS:
        raise PhotoIdentityFineIdentityAdapterError(
            "fine-identity adapter config fields must match v1 exactly"
        )
    version = value.get("version")
    if (
        value.get("format") != CONFIG_FORMAT
        or isinstance(version, bool)
        or version != CONFIG_VERSION
    ):
        raise PhotoIdentityFineIdentityAdapterError(
            "unsupported fine-identity adapter config format/version"
        )

    adapter = str(value.get("adapter") or "").strip()
    revision = str(value.get("revision") or "").strip()
    if not ADAPTER_RE.fullmatch(adapter):
        raise PhotoIdentityFineIdentityAdapterError("fine-identity adapter name is invalid")
    if not revision or len(revision) > 160:
        raise PhotoIdentityFineIdentityAdapterError("fine-identity adapter revision is invalid")

    command = value.get("command")
    if (
        not isinstance(command, list)
        or not 1 <= len(command) <= 32
        or any(not isinstance(item, str) or not item or len(item) > 2000 for item in command)
    ):
        raise PhotoIdentityFineIdentityAdapterError(
            "fine-identity adapter command must be 1..32 non-empty argv strings"
        )

    capabilities = value.get("capabilities")
    if not isinstance(capabilities, Mapping) or set(capabilities) != CAPABILITY_FIELDS:
        raise PhotoIdentityFineIdentityAdapterError(
            "fine-identity adapter capabilities must match v1 exactly"
        )
    domains = capabilities.get("domains")
    if not isinstance(domains, Mapping) or set(domains) != set(APPLICATION_DOMAINS):
        raise PhotoIdentityFineIdentityAdapterError(
            "fine-identity adapter domain capabilities are incomplete"
        )
    for domain, minimum in APPLICATION_DOMAINS.items():
        entry = domains.get(domain)
        if not isinstance(entry, Mapping) or set(entry) != DOMAIN_CAPABILITY_FIELDS:
            raise PhotoIdentityFineIdentityAdapterError(
                f"{domain} adapter capabilities are not canonical"
            )
        if any(type(entry.get(field)) is not bool for field in DOMAIN_CAPABILITY_FIELDS):
            raise PhotoIdentityFineIdentityAdapterError(
                f"{domain} adapter capabilities must be booleans"
            )
        if entry.get("geometry") is not bool(minimum["geometry"]):
            raise PhotoIdentityFineIdentityAdapterError(
                f"{domain} geometry capability does not match required application authority"
            )
        if entry.get("appearance") is not bool(minimum["appearance"]):
            raise PhotoIdentityFineIdentityAdapterError(
                f"{domain} appearance capability does not match required application authority"
            )

    required_true = (
        "source_grounded",
        "preserves_rig",
        "preserves_source_derived_dental_identity",
        "preserves_hfn_authority",
    )
    if any(capabilities.get(field) is not True for field in required_true):
        raise PhotoIdentityFineIdentityAdapterError(
            "fine-identity adapter must preserve rig/dental/HFN authority and be source-grounded"
        )
    if capabilities.get("generative_identity_synthesis") is not False:
        raise PhotoIdentityFineIdentityAdapterError(
            "fine-identity adapter may not use generative identity synthesis"
        )

    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
        raise PhotoIdentityFineIdentityAdapterError(
            "fine-identity adapter timeout_seconds must be in 1..86400"
        )
    _bound_command(command, Path("input.json"), Path("output"))
    return dict(value)


def _public_projection(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {field: entry[field] for field in PUBLIC_ENTRY_FIELDS}


def load_application_source_evidence(
    *,
    private_manifest_path: Path,
    attestation_path: Path,
    bodyrig_revision: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    revision = _revision(bodyrig_revision)
    try:
        attestation = read_attestation(
            attestation_path,
            expected_bodyrig_revision=revision,
        )
    except PhotoIdentityFineIdentityAttestationError as exc:
        raise PhotoIdentityFineIdentityAdapterError(str(exc)) from exc

    if (
        attestation.get("source_grounded") is not True
        or attestation.get("generic_guessing_permitted") is not False
    ):
        raise PhotoIdentityFineIdentityAdapterError(
            "fine-identity attestation crossed source-grounded authority boundary"
        )

    manifest = _read_json(
        private_manifest_path,
        label="Private fine-identity review manifest",
    )
    if set(manifest) != PRIVATE_TOP_FIELDS:
        raise PhotoIdentityFineIdentityAdapterError(
            "private fine-identity review manifest fields must match v1 exactly"
        )
    if manifest.get("format") != PRIVATE_FORMAT or manifest.get("version") != PRIVATE_VERSION:
        raise PhotoIdentityFineIdentityAdapterError(
            "private fine-identity review manifest format/version mismatch"
        )
    if str(manifest.get("performer_id") or "") != str(attestation.get("performer_id") or ""):
        raise PhotoIdentityFineIdentityAdapterError(
            "private fine-identity manifest performer mismatch"
        )
    if str(manifest.get("bodyrig_revision") or "").lower() != revision:
        raise PhotoIdentityFineIdentityAdapterError(
            "private fine-identity manifest BodyRig revision mismatch"
        )

    selected = attestation.get("selected_evidence")
    if not isinstance(selected, list):
        raise PhotoIdentityFineIdentityAdapterError(
            "fine-identity attestation selected evidence is invalid"
        )
    public_by_reference = {
        str(item.get("reference") or ""): dict(item)
        for item in selected
        if isinstance(item, Mapping) and item.get("domain") in APPLICATION_DOMAINS
    }

    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise PhotoIdentityFineIdentityAdapterError(
            "private fine-identity evidence list is invalid"
        )

    grouped: dict[str, list[dict[str, Any]]] = {
        domain: [] for domain in APPLICATION_DOMAINS
    }
    scenes: dict[str, set[str]] = {domain: set() for domain in APPLICATION_DOMAINS}
    observed_refs: set[str] = set()

    for raw in entries:
        if not isinstance(raw, Mapping) or set(raw) != PRIVATE_ENTRY_FIELDS:
            raise PhotoIdentityFineIdentityAdapterError(
                "private fine-identity evidence entry fields are invalid"
            )
        domain = str(raw.get("domain") or "")
        if domain not in APPLICATION_DOMAINS:
            continue
        reference = str(raw.get("reference") or "").strip()
        public = public_by_reference.get(reference)
        if not reference or public is None:
            raise PhotoIdentityFineIdentityAdapterError(
                f"private {domain} evidence is not present in the exact public attestation"
            )
        if _public_projection(raw) != public:
            raise PhotoIdentityFineIdentityAdapterError(
                f"private/public fine-identity evidence mismatch: {reference}"
            )

        source_media = Path(str(raw.get("source_media_path") or "")).expanduser().resolve()
        review_image = Path(str(raw.get("review_image_path") or "")).expanduser().resolve()
        if _sha256_file(source_media) != str(raw.get("source_media_sha256") or "").lower():
            raise PhotoIdentityFineIdentityAdapterError(
                f"source media hash drifted for {reference}"
            )
        if _sha256_file(review_image) != str(raw.get("review_image_sha256") or "").lower():
            raise PhotoIdentityFineIdentityAdapterError(
                f"review image hash drifted for {reference}"
            )

        grouped[domain].append(dict(raw))
        scenes[domain].add(str(raw.get("scene_id") or ""))
        observed_refs.add(reference)

    if observed_refs != set(public_by_reference):
        raise PhotoIdentityFineIdentityAdapterError(
            "private/public non-dental fine-identity evidence set is not exact"
        )
    for domain in APPLICATION_DOMAINS:
        if len(scenes[domain]) < 2:
            raise PhotoIdentityFineIdentityAdapterError(
                f"{domain} requires at least two distinct source scenes"
            )

    marker_path = Path(str(manifest.get("marker_inventory_path") or "")).expanduser().resolve()
    marker_sha = _sha256_file(marker_path)
    if marker_sha != str(manifest.get("marker_inventory_sha256") or "").lower():
        raise PhotoIdentityFineIdentityAdapterError(
            "private distinctive-marker inventory hash drifted"
        )
    if marker_sha != str(attestation.get("marker_inventory_sha256") or "").lower():
        raise PhotoIdentityFineIdentityAdapterError(
            "private/public distinctive-marker inventory hash mismatch"
        )

    return dict(attestation), dict(manifest), grouped
