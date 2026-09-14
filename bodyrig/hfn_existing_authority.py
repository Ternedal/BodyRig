from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .hands_feet_nails_landmark_evidence import (
    HandsFeetNailsLandmarkEvidenceError,
    evidence_path as landmark_evidence_path,
    validate_landmark_evidence,
)
from .hands_feet_nails_source_capture import (
    REQUIRED_REGIONS,
    VERSION as SOURCE_CAPTURE_VERSION,
    HandsFeetNailsSourceCaptureError,
    capture_dir,
    read_source_capture,
)
from .hands_feet_nails_uv_domain_evidence import (
    HandsFeetNailsUvDomainEvidenceError,
    evidence_path as uv_evidence_path,
    validate_uv_domain_evidence,
)
from .package import MRBodyError, validate_package

PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_RE = re.compile(r"^body-r[0-9]{4}$")
CAPTURE_RE = re.compile(r"^hfncap-[0-9a-f]{32}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class HfnExistingAuthorityError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise HfnExistingAuthorityError(f"HFN authority file is missing or symlinked: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise HfnExistingAuthorityError(f"{label} is missing or symlinked: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HfnExistingAuthorityError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise HfnExistingAuthorityError(f"{label} must be a JSON object")
    return value


def _identity(person_id: str, body_revision: str) -> tuple[str, str]:
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    if not PERSON_RE.fullmatch(person) or not BODY_RE.fullmatch(body):
        raise HfnExistingAuthorityError("HFN existing-authority Person/body identity is not canonical")
    return person, body


def _package_authority(package_path: Path, expected_sha256: str) -> tuple[Path, str, str]:
    package = package_path.expanduser().resolve()
    expected = str(expected_sha256 or "").strip().lower()
    if not SHA_RE.fullmatch(expected):
        raise HfnExistingAuthorityError("HFN existing-authority package SHA-256 is not canonical")
    if not package.is_file() or package.is_symlink():
        raise HfnExistingAuthorityError(f"HFN existing-authority package is missing or symlinked: {package}")
    actual = _sha256_file(package)
    if actual != expected:
        raise HfnExistingAuthorityError("HFN existing-authority package bytes changed before reuse discovery")
    try:
        validated = validate_package(package)
    except (MRBodyError, OSError) as exc:
        raise HfnExistingAuthorityError("HFN existing-authority source package is invalid") from exc
    body_id = str(validated.manifest.get("id") or "").strip()
    if not body_id:
        raise HfnExistingAuthorityError("HFN existing-authority source package has no canonical body id")
    return package, body_id, actual


def _strict_source_capture_version(source: Mapping[str, Any]) -> bool:
    version = source.get("version")
    return (
        not isinstance(version, bool)
        and isinstance(version, (int, float))
        and version == SOURCE_CAPTURE_VERSION
    )


def _validate_chain(
    root: Path,
    *,
    person_id: str,
    body_revision: str,
    capture_id: str,
    uv_path: Path,
    expected_body_id: str,
    expected_package_sha256: str,
) -> dict[str, str] | None:
    try:
        source = read_source_capture(
            root,
            person_id,
            body_revision=body_revision,
            capture_id=capture_id,
        )
    except (HandsFeetNailsSourceCaptureError, OSError):
        return None
    if not _strict_source_capture_version(source):
        return None

    source_manifest = capture_dir(root, person_id, body_revision, capture_id) / "source-capture.json"
    try:
        source_capture_sha = _sha256_file(source_manifest)
        uv_raw = _read_json(uv_path, label="HFN UV-domain evidence")
        uv = validate_uv_domain_evidence(uv_raw)
    except (HfnExistingAuthorityError, HandsFeetNailsUvDomainEvidenceError, OSError):
        return None

    if (uv.get("person_id"), uv.get("body_revision"), uv.get("capture_id")) != (
        person_id,
        body_revision,
        capture_id,
    ):
        return None
    if uv.get("body_id") != expected_body_id or uv.get("package_sha256") != expected_package_sha256:
        return None

    uv_revision = str(uv.get("uv_evidence_bodyrig_revision") or "").strip().lower()
    if not GIT_RE.fullmatch(uv_revision):
        return None
    try:
        canonical_uv_path = uv_evidence_path(root, person_id, body_revision, capture_id, uv_revision).resolve()
    except HandsFeetNailsUvDomainEvidenceError:
        return None
    if uv_path.resolve() != canonical_uv_path:
        return None

    landmark_revision = str(uv.get("landmark_evidence_bodyrig_revision") or "").strip().lower()
    if not GIT_RE.fullmatch(landmark_revision):
        return None
    try:
        landmark_path = landmark_evidence_path(
            root,
            person_id,
            body_revision,
            capture_id,
            landmark_revision,
        ).resolve()
        landmark_raw = _read_json(landmark_path, label="HFN landmark evidence")
        landmark = validate_landmark_evidence(landmark_raw)
        landmark_sha = _sha256_file(landmark_path)
        uv_sha = _sha256_file(uv_path)
    except (
        HfnExistingAuthorityError,
        HandsFeetNailsLandmarkEvidenceError,
        OSError,
    ):
        return None

    if landmark_sha != uv.get("landmark_evidence_sha256"):
        return None
    if landmark.get("all_regions_application_ready") is not True:
        return None
    if landmark.get("source_capture_sha256") != source_capture_sha:
        return None
    if (landmark.get("person_id"), landmark.get("body_revision"), landmark.get("capture_id")) != (
        person_id,
        body_revision,
        capture_id,
    ):
        return None
    regions = landmark.get("regions")
    source_regions = source.get("regions")
    if not isinstance(regions, Mapping) or not isinstance(source_regions, Mapping):
        return None
    for region in REQUIRED_REGIONS:
        landmark_region = regions.get(region)
        source_region = source_regions.get(region)
        if not isinstance(landmark_region, Mapping) or not isinstance(source_region, Mapping):
            return None
        if landmark_region.get("closeup_image_sha256") != source_region.get("image_sha256"):
            return None

    return {
        "capture_id": capture_id,
        "uv_evidence_path": str(uv_path.resolve()),
        "uv_evidence_sha256": uv_sha,
        "source_capture_sha256": source_capture_sha,
        "landmark_evidence_sha256": landmark_sha,
        "body_id": expected_body_id,
        "package_sha256": expected_package_sha256,
    }


def find_reusable_hfn_source_uv_authorities(
    root: str | Path,
    person_id: str,
    *,
    body_revision: str,
    package_path: str | Path,
    package_sha256: str,
) -> list[dict[str, str]]:
    """Return every exact, still-valid source/UV chain for one Person/body/package.

    Discovery is deliberately non-selecting: callers may auto-reuse only when this
    returns exactly one entry. Invalid, stale, tampered or non-canonical evidence
    is ignored rather than allowed to influence a winner.
    """

    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir() or root_path.is_symlink():
        raise HfnExistingAuthorityError(f"HFN existing-authority root is missing or symlinked: {root_path}")
    person, body = _identity(person_id, body_revision)

    captures_root = root_path / "hands-feet-nails-source-captures" / person / body
    if not captures_root.is_dir() or captures_root.is_symlink():
        return []

    structural_candidates: list[tuple[str, Path]] = []
    for capture_path in sorted(captures_root.iterdir(), key=lambda item: item.name):
        capture_id = capture_path.name.lower()
        if (
            not CAPTURE_RE.fullmatch(capture_id)
            or not capture_path.is_dir()
            or capture_path.is_symlink()
            or capture_path.name != capture_id
        ):
            continue
        source_manifest = capture_path / "source-capture.json"
        if not source_manifest.is_file() or source_manifest.is_symlink():
            continue

        uv_root = (
            root_path
            / "hands-feet-nails-uv-domain-evidence"
            / person
            / body
            / capture_id
        )
        if not uv_root.is_dir() or uv_root.is_symlink():
            continue
        for uv_path in sorted(uv_root.glob("*.json"), key=lambda item: item.name):
            if not uv_path.is_file() or uv_path.is_symlink() or not GIT_RE.fullmatch(uv_path.stem):
                continue
            structural_candidates.append((capture_id, uv_path))

    # Zero structurally eligible source/UV tuples is the normal operator-stop
    # state. Do not demand package parsing merely to establish that nothing can
    # be reused; exact package authority is required only before a candidate is
    # allowed to count as reusable.
    if not structural_candidates:
        return []

    _package, body_id, exact_package_sha = _package_authority(
        Path(package_path),
        package_sha256,
    )
    matches: list[dict[str, str]] = []
    for capture_id, uv_path in structural_candidates:
        match = _validate_chain(
            root_path,
            person_id=person,
            body_revision=body,
            capture_id=capture_id,
            uv_path=uv_path,
            expected_body_id=body_id,
            expected_package_sha256=exact_package_sha,
        )
        if match is not None:
            matches.append(match)
    return matches
