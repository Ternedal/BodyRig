from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .pbr_ab_body_job_source import (
    PbrAbBodyJobSourceError,
    _canonical_job_path,
    _file_sha256,
    _read_json,
    _revision,
    _verify_persisted_receipts,
)


FORMAT = "bodyrig-succeeded-body-job-receipt-authority"
VERSION = 1
_PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_EVIDENCE_KIND = "stash-physical-source-manifest-v1"


class BodyJobReceiptAuthorityError(ValueError):
    pass


def _translate(exc: Exception) -> BodyJobReceiptAuthorityError:
    return BodyJobReceiptAuthorityError(str(exc))


def _sha256(value: object, label: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(text) is None:
        raise BodyJobReceiptAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _body_revision(profile_like: Mapping[str, Any], revision_id: str) -> dict[str, Any]:
    for item in profile_like.get("body_revisions", []):
        if isinstance(item, Mapping) and item.get("revision_id") == revision_id:
            return dict(item)
    raise BodyJobReceiptAuthorityError("registered body revision disappeared while validating job receipts")


def inspect_succeeded_body_job_receipts(
    *,
    job_id: str,
    expected_revision: str,
    expected_person_id: str | None = None,
) -> dict[str, Any]:
    try:
        job_path = _canonical_job_path(job_id)
        job = _read_json(job_path, "succeeded body-build job")
    except PbrAbBodyJobSourceError as exc:
        raise _translate(exc) from exc

    if job.get("format") != "bodyrig-ui-job" or job.get("version") != 1:
        raise BodyJobReceiptAuthorityError("body job format/version mismatch")
    if job.get("job_id") != job_id:
        raise BodyJobReceiptAuthorityError("body job id does not match its canonical storage path")
    if job.get("kind") != "body-build" or job.get("status") != "succeeded":
        raise BodyJobReceiptAuthorityError("receipt authority requires a succeeded body-build job")

    person_id = str(job.get("person_id") or "").strip()
    if _PERSON_RE.fullmatch(person_id) is None:
        raise BodyJobReceiptAuthorityError("succeeded body job has no canonical Person id")
    if expected_person_id is not None:
        expected_person = str(expected_person_id or "").strip()
        if _PERSON_RE.fullmatch(expected_person) is None:
            raise BodyJobReceiptAuthorityError("expected Person id is not canonical")
        if person_id != expected_person:
            raise BodyJobReceiptAuthorityError("succeeded body job Person does not match expected authority")

    try:
        expected_bodyrig_revision = _revision(expected_revision, "expected BodyRig revision")
        job_revision = _revision(job.get("bodyrig_revision"), "body job BodyRig revision")
    except PbrAbBodyJobSourceError as exc:
        raise _translate(exc) from exc
    if job_revision != expected_bodyrig_revision:
        raise BodyJobReceiptAuthorityError(
            f"succeeded body job belongs to {job_revision}, not expected revision {expected_bodyrig_revision}"
        )

    try:
        persisted = _verify_persisted_receipts(job=job, person_id=person_id)
    except PbrAbBodyJobSourceError as exc:
        raise _translate(exc) from exc

    source_binding_path = Path(persisted["source_binding"]).expanduser().resolve()
    try:
        source_binding = _read_json(source_binding_path, "registered body source binding receipt")
    except PbrAbBodyJobSourceError as exc:
        raise _translate(exc) from exc
    evidence = source_binding.get("evidence")
    if not isinstance(evidence, Mapping):
        raise BodyJobReceiptAuthorityError("registered body source binding has no canonical evidence object")
    if evidence.get("kind") != _SOURCE_EVIDENCE_KIND:
        raise BodyJobReceiptAuthorityError("registered body source binding is not backed by the canonical Stash physical source manifest")
    source_evidence_sha256 = _sha256(evidence.get("sha256"), "body source manifest SHA-256")

    component = source_binding.get("component")
    if not isinstance(component, Mapping):
        raise BodyJobReceiptAuthorityError("registered body source binding has no canonical component object")
    package_sha256 = _sha256(component.get("artifact_sha256"), "registered body package SHA-256")

    return {
        "format": FORMAT,
        "version": VERSION,
        "body_job_id": job_id,
        "person_id": person_id,
        "bodyrig_revision": job_revision,
        "body_revision": persisted["body_revision"],
        "canonical_body_id": persisted["canonical_body_id"],
        "package_sha256": package_sha256,
        "job_json": str(job_path),
        "job_json_sha256": _file_sha256(job_path),
        "source_binding": persisted["source_binding"],
        "source_binding_sha256": persisted["source_binding_sha256"],
        "body_review": persisted["body_review"],
        "body_review_sha256": persisted["body_review_sha256"],
        "source_evidence_kind": _SOURCE_EVIDENCE_KIND,
        "source_evidence_sha256": source_evidence_sha256,
        "comparison_only": True,
        "human_visual_authority_required": True,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate persisted source/review receipts for a succeeded BodyRig body job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-person-id")
    args = parser.parse_args(argv)
    try:
        result = inspect_succeeded_body_job_receipts(
            job_id=args.job_id,
            expected_revision=args.expected_revision,
            expected_person_id=args.expected_person_id,
        )
    except BodyJobReceiptAuthorityError as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
