from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .hands_feet_nails_detail_candidate import (
    HandsFeetNailsDetailCandidateError,
    _load_authorities,
    _read_package,
)

FORMAT = "bodyrig-hfn-reusable-detail-authority"
VERSION = 1
POLICY_REVISION = "bodyrig-hfn-reusable-detail-authority-v1"
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_RE = re.compile(r"^body-r[0-9]{4}$")
CAPTURE_RE = re.compile(r"^hfncap-[0-9a-f]{32}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class HfnReusableDetailAuthorityError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(person_id: str, body_revision: str) -> tuple[str, str]:
    person = str(person_id or "").strip().lower()
    body = str(body_revision or "").strip().lower()
    if not PERSON_RE.fullmatch(person) or not BODY_RE.fullmatch(body):
        raise HfnReusableDetailAuthorityError("HFN reusable authority identity is not canonical")
    return person, body


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise HfnReusableDetailAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _result(
    *,
    person_id: str,
    body_revision: str,
    source_package_sha256: str,
    body_id: str | None,
    state: str,
    evidence_file_count: int,
    matches: list[dict[str, Any]],
    rejected: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "person_id": person_id,
        "body_revision": body_revision,
        "body_id": body_id,
        "source_package_sha256": source_package_sha256,
        "state": state,
        "evidence_file_count": evidence_file_count,
        "match_count": len(matches),
        "rejected_match_count": len(rejected),
        "matches": matches,
        "rejected_matches": rejected,
        "source_authority_required": True,
        "human_review_required": True,
        "production_activation": False,
    }


def resolve_reusable_detail_authority(
    root: str | Path,
    *,
    person_id: str,
    body_revision: str,
    source_package_path: str | Path,
    source_package_sha256: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    person, body = _identity(person_id, body_revision)
    expected_package_sha = _sha(source_package_sha256, label="HFN source package SHA-256")
    base = root_path / "hands-feet-nails-uv-domain-evidence" / person / body
    if not base.is_dir():
        return _result(
            person_id=person,
            body_revision=body,
            source_package_sha256=expected_package_sha,
            body_id=None,
            state="unresolved",
            evidence_file_count=0,
            matches=[],
            rejected=[],
        )
    if base.is_symlink():
        raise HfnReusableDetailAuthorityError("HFN UV authority root is symlinked")

    package = Path(source_package_path).expanduser().resolve()
    if not package.is_file() or package.is_symlink():
        raise HfnReusableDetailAuthorityError("HFN exact source package is missing or symlinked")
    if _sha256_file(package) != expected_package_sha:
        raise HfnReusableDetailAuthorityError("HFN exact source package bytes changed before authority reuse")
    try:
        _avatar, body_id, package_sha = _read_package(package)
    except HandsFeetNailsDetailCandidateError as exc:
        raise HfnReusableDetailAuthorityError(str(exc)) from exc
    if package_sha != expected_package_sha or not str(body_id or "").strip():
        raise HfnReusableDetailAuthorityError("HFN source package validation disagrees with exact package authority")

    evidence_files = sorted(base.glob("*/*.json"))
    matches: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for uv_path in evidence_files:
        capture_id = uv_path.parent.name.lower()
        uv_revision = uv_path.stem.lower()
        reject_identity = {"capture_id": capture_id, "uv_evidence_path": str(uv_path.resolve())}
        if uv_path.is_symlink() or uv_path.parent.is_symlink():
            rejected.append({**reject_identity, "reason": "UV evidence path is symlinked"})
            continue
        if not CAPTURE_RE.fullmatch(capture_id) or not GIT_RE.fullmatch(uv_revision):
            rejected.append({**reject_identity, "reason": "UV evidence path identity is not canonical"})
            continue
        try:
            source, landmark, uv, source_capture_sha, landmark_sha, uv_sha = _load_authorities(
                root_path,
                person_id=person,
                body_revision=body,
                capture_id=capture_id,
                uv_evidence_file=uv_path,
            )
        except HandsFeetNailsDetailCandidateError as exc:
            rejected.append({**reject_identity, "reason": str(exc)})
            continue
        if (
            uv.get("person_id") != person
            or uv.get("body_revision") != body
            or uv.get("capture_id") != capture_id
            or uv.get("uv_evidence_bodyrig_revision") != uv_revision
        ):
            rejected.append({**reject_identity, "reason": "UV evidence path/identity no longer matches its strict authority"})
            continue
        if uv.get("body_id") != body_id or uv.get("package_sha256") != expected_package_sha:
            rejected.append({**reject_identity, "reason": "UV evidence targets different body/package bytes"})
            continue
        if landmark.get("all_regions_application_ready") is not True:
            rejected.append({**reject_identity, "reason": "linked landmark evidence is not application-ready"})
            continue
        source_manifest = str(source.get("source_manifest_sha256") or "").lower()
        if source_manifest and not SHA_RE.fullmatch(source_manifest):
            rejected.append({**reject_identity, "reason": "source capture manifest authority is invalid"})
            continue
        matches.append({
            "person_id": person,
            "body_revision": body,
            "body_id": body_id,
            "capture_id": capture_id,
            "uv_evidence_bodyrig_revision": uv_revision,
            "uv_evidence_path": str(uv_path.resolve()),
            "uv_evidence_sha256": uv_sha,
            "source_capture_sha256": source_capture_sha,
            "landmark_evidence_sha256": landmark_sha,
            "source_package_sha256": expected_package_sha,
        })

    if len(matches) == 1:
        state = "resolved"
    elif len(matches) > 1:
        state = "ambiguous"
    elif evidence_files:
        state = "blocked"
    else:
        state = "unresolved"
    return _result(
        person_id=person,
        body_revision=body,
        source_package_sha256=expected_package_sha,
        body_id=str(body_id),
        state=state,
        evidence_file_count=len(evidence_files),
        matches=matches,
        rejected=rejected,
    )
