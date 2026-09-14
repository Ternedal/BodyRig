from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .person_profiles import BODY_ID_RE, PersonProfileError, load_profile
from .person_voice_source import PersonVoiceSourceError, source_files_for_body

FORMAT = "bodyrig-hfn-identity-binding"
VERSION = 1
POLICY_REVISION = "bodyrig-hfn-identity-binding-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_REVISION_RE = re.compile(r"^body-r[0-9]{4}$")


class HfnIdentityBindingError(ValueError):
    pass


def _canonical_body_id(value: Any) -> str:
    text = str(value or "").strip()
    if not BODY_ID_RE.fullmatch(text):
        raise HfnIdentityBindingError("body_id is invalid")
    return text


def _canonical_sha256(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise HfnIdentityBindingError("package_sha256 is invalid")
    return text


def _profile_body_revisions(profile: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    revisions = profile.get("body_revisions")
    if not isinstance(revisions, list):
        return []
    return [item for item in revisions if isinstance(item, Mapping)]


def resolve_hfn_identity(
    root: str | Path,
    *,
    body_id: str,
    package_sha256: str,
) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir() or root_path.is_symlink():
        raise HfnIdentityBindingError(f"canonical Person library root is missing or symlinked: {root_path}")
    canonical_body_id = _canonical_body_id(body_id)
    canonical_package_sha = _canonical_sha256(package_sha256)

    matches: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    metadata_match_count = 0
    for profile_path in sorted(root_path.glob("person-*.json")):
        if not profile_path.is_file() or profile_path.is_symlink():
            continue
        try:
            profile = load_profile(root_path, profile_path.stem)
        except PersonProfileError:
            continue
        person_id = str(profile.get("person_id") or "").strip().lower()
        if person_id != profile_path.stem or not PERSON_RE.fullmatch(person_id):
            continue
        for revision in _profile_body_revisions(profile):
            if str(revision.get("body_id") or "").strip() != canonical_body_id:
                continue
            if str(revision.get("package_sha256") or "").strip().lower() != canonical_package_sha:
                continue
            metadata_match_count += 1
            body_revision = str(revision.get("revision_id") or "").strip().lower()
            if not BODY_REVISION_RE.fullmatch(body_revision):
                rejected.append({
                    "person_id": person_id,
                    "body_revision": body_revision,
                    "reason": "matching body revision id is not canonical",
                })
                continue
            try:
                source = source_files_for_body(root_path, profile, body_revision=body_revision)
            except PersonVoiceSourceError as exc:
                rejected.append({
                    "person_id": person_id,
                    "body_revision": body_revision,
                    "reason": str(exc),
                })
                continue
            manifest_sha = str(source.get("manifest_sha256") or "").strip().lower()
            source_files = source.get("source_files")
            if not SHA256_RE.fullmatch(manifest_sha) or not isinstance(source_files, list) or not source_files:
                rejected.append({
                    "person_id": person_id,
                    "body_revision": body_revision,
                    "reason": "body source binding returned incomplete current source evidence",
                })
                continue
            matches.append({
                "person_id": person_id,
                "body_revision": body_revision,
                "source_manifest_sha256": manifest_sha,
                "source_file_count": len(source_files),
            })

    if len(matches) == 1:
        state = "resolved"
    elif len(matches) > 1:
        state = "ambiguous"
    elif metadata_match_count:
        state = "blocked"
    else:
        state = "unresolved"
    return {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "body_id": canonical_body_id,
        "source_package_sha256": canonical_package_sha,
        "state": state,
        "metadata_match_count": metadata_match_count,
        "match_count": len(matches),
        "rejected_match_count": len(rejected),
        "matches": matches,
        "rejected_matches": rejected,
        "source_authority_required": True,
        "human_review_required": True,
        "production_activation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve one exact source-authoritative Person/body revision for an HFN current-floor package."
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--body-id", required=True)
    parser.add_argument("--package-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = resolve_hfn_identity(
            args.root,
            body_id=args.body_id,
            package_sha256=args.package_sha256,
        )
    except (HfnIdentityBindingError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
