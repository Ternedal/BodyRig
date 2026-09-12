from __future__ import annotations

import argparse
import hashlib
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
_SOURCE_ENQUEUE_FIELDS = {
    "format",
    "version",
    "job_id",
    "person_id",
    "stash_performer_id",
    "expected_bodyrig_revision",
}


class BodyJobReceiptAuthorityError(ValueError):
    pass


def _v1(value: object) -> bool:
    return not isinstance(value, bool) and value == 1


def _translate(exc: Exception) -> BodyJobReceiptAuthorityError:
    return BodyJobReceiptAuthorityError(str(exc))


def _sha256(value: object, label: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(text) is None:
        raise BodyJobReceiptAuthorityError(f"{label} is not a canonical SHA-256")
    return text


def _canonical_json_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _verify_source_enqueue_authority(
    *,
    job: Mapping[str, Any],
    person_id: str,
    job_id: str,
    job_revision: str,
) -> str:
    marker = job.get("source_enqueue_authority")
    if not isinstance(marker, Mapping) or set(marker) != _SOURCE_ENQUEUE_FIELDS:
        raise BodyJobReceiptAuthorityError("succeeded body job lacks canonical revision-bound source enqueue authority")
    if marker.get("format") != "bodyrig-body-build-source-enqueue-authority" or not _v1(marker.get("version")):
        raise BodyJobReceiptAuthorityError("succeeded body job source enqueue authority format/version mismatch")
    if str(marker.get("job_id") or "") != job_id or str(marker.get("person_id") or "") != person_id:
        raise BodyJobReceiptAuthorityError("succeeded body job source enqueue authority identity mismatch")
    try:
        marker_revision = _revision(marker.get("expected_bodyrig_revision"), "source enqueue expected revision")
    except PbrAbBodyJobSourceError as exc:
        raise _translate(exc) from exc
    if marker_revision != job_revision:
        raise BodyJobReceiptAuthorityError("succeeded body job source enqueue authority revision mismatch")
    performer_id = str(marker.get("stash_performer_id") or "").strip()
    if not performer_id:
        raise BodyJobReceiptAuthorityError("succeeded body job source enqueue authority has no Stash performer id")
    return performer_id


def _verify_source_manifest(
    *,
    source_binding: Mapping[str, Any],
    persisted_source_binding_sha256: str,
    source_binding_path: Path,
    expected_stash_performer_id: str,
) -> dict[str, str]:
    evidence = source_binding.get("evidence")
    if not isinstance(evidence, Mapping):
        raise BodyJobReceiptAuthorityError("registered body source binding has no canonical evidence object")
    if evidence.get("kind") != _SOURCE_EVIDENCE_KIND:
        raise BodyJobReceiptAuthorityError("registered body source binding is not backed by the canonical Stash physical source manifest")
    source_evidence_sha256 = _sha256(evidence.get("sha256"), "body source manifest SHA-256")

    evidence_ref = str(evidence.get("ref") or "").strip()
    if not evidence_ref:
        raise BodyJobReceiptAuthorityError("registered body source binding has no source manifest path")
    manifest_path = Path(evidence_ref).expanduser()
    if not manifest_path.is_absolute():
        raise BodyJobReceiptAuthorityError("registered body source manifest path is not absolute")
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise BodyJobReceiptAuthorityError("registered body source manifest is no longer present")
    try:
        manifest_sha_before = _file_sha256(manifest_path)
    except OSError as exc:
        raise BodyJobReceiptAuthorityError("registered body source manifest is no longer readable") from exc
    if manifest_sha_before != source_evidence_sha256:
        raise BodyJobReceiptAuthorityError("registered body source manifest bytes changed after body job success")

    try:
        manifest = _read_json(manifest_path, "registered body source manifest")
    except PbrAbBodyJobSourceError as exc:
        raise _translate(exc) from exc
    if manifest.get("format") != "bodyrig-stash-source-manifest" or not _v1(manifest.get("version")):
        raise BodyJobReceiptAuthorityError("registered body source manifest format/version mismatch")
    performer = manifest.get("performer")
    source = source_binding.get("source")
    if not isinstance(performer, Mapping) or not isinstance(source, Mapping):
        raise BodyJobReceiptAuthorityError("registered body source manifest performer identity is malformed")
    source_performer_id = str(source.get("performer_id") or "").strip()
    if str(performer.get("id") or "") != source_performer_id:
        raise BodyJobReceiptAuthorityError("registered body source manifest performer no longer matches Person source authority")
    if source_performer_id != expected_stash_performer_id:
        raise BodyJobReceiptAuthorityError(
            "registered body source binding performer differs from revision-bound source enqueue authority"
        )

    selected = manifest.get("selected")
    source_files = evidence.get("source_files")
    if not isinstance(selected, list) or not selected or not isinstance(source_files, list) or len(source_files) != len(selected):
        raise BodyJobReceiptAuthorityError("registered body source manifest/source-file receipt cardinality mismatch")
    clean_source_files: list[dict[str, str]] = []
    for selected_item, source_item in zip(selected, source_files, strict=True):
        if not isinstance(selected_item, Mapping) or not isinstance(source_item, Mapping):
            raise BodyJobReceiptAuthorityError("registered body source-file receipt entry is malformed")
        selected_path = Path(str(selected_item.get("path") or "")).expanduser()
        selected_name = selected_path.name
        selected_scene = str(selected_item.get("scene_id") or "")
        source_scene = str(source_item.get("scene_id") or "")
        source_name = str(source_item.get("name") or "")
        source_sha = _sha256(source_item.get("sha256"), "registered source-file SHA-256")
        if not selected_name or selected_scene != source_scene or selected_name != source_name:
            raise BodyJobReceiptAuthorityError("registered body source-file receipt no longer matches source manifest selection")
        clean_source_files.append({"scene_id": source_scene, "name": source_name, "sha256": source_sha})

    try:
        manifest_sha_after = _file_sha256(manifest_path)
        source_binding_sha_after = _file_sha256(source_binding_path)
    except OSError as exc:
        raise BodyJobReceiptAuthorityError("registered body source authority changed while being validated") from exc
    if manifest_sha_after != source_evidence_sha256:
        raise BodyJobReceiptAuthorityError("registered body source manifest changed while being validated")
    if source_binding_sha_after != persisted_source_binding_sha256:
        raise BodyJobReceiptAuthorityError("registered body source binding receipt changed while being validated")

    return {
        "stash_performer_id": expected_stash_performer_id,
        "source_evidence_kind": _SOURCE_EVIDENCE_KIND,
        "source_evidence": str(manifest_path),
        "source_evidence_sha256": source_evidence_sha256,
        "source_files_sha256": _canonical_json_sha256(clean_source_files),
    }


def inspect_succeeded_body_job_receipts(
    *,
    job_id: str,
    expected_revision: str,
    expected_person_id: str | None = None,
) -> dict[str, Any]:
    try:
        job_path = _canonical_job_path(job_id)
        job = _read_json(job_path, "succeeded body-build job")
        job_sha_before = _file_sha256(job_path)
    except (PbrAbBodyJobSourceError, OSError) as exc:
        raise _translate(exc) from exc

    if job.get("format") != "bodyrig-ui-job" or not _v1(job.get("version")):
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
    stash_performer_id = _verify_source_enqueue_authority(
        job=job,
        person_id=person_id,
        job_id=job_id,
        job_revision=job_revision,
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
    source_authority = _verify_source_manifest(
        source_binding=source_binding,
        persisted_source_binding_sha256=str(persisted["source_binding_sha256"]),
        source_binding_path=source_binding_path,
        expected_stash_performer_id=stash_performer_id,
    )

    component = source_binding.get("component")
    if not isinstance(component, Mapping):
        raise BodyJobReceiptAuthorityError("registered body source binding has no canonical component object")
    package_sha256 = _sha256(component.get("artifact_sha256"), "registered body package SHA-256")

    body_review_path = Path(persisted["body_review"]).expanduser().resolve()
    try:
        body_review_sha_after = _file_sha256(body_review_path)
        job_sha_after = _file_sha256(job_path)
    except OSError as exc:
        raise BodyJobReceiptAuthorityError("body job receipt authority changed while being validated") from exc
    if body_review_sha_after != str(persisted["body_review_sha256"]):
        raise BodyJobReceiptAuthorityError("registered body fidelity review receipt changed while being validated")
    if job_sha_after != job_sha_before:
        raise BodyJobReceiptAuthorityError("body job JSON changed while persisted receipts were being validated")

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
        "job_json_sha256": job_sha_after,
        "source_binding": persisted["source_binding"],
        "source_binding_sha256": persisted["source_binding_sha256"],
        "body_review": persisted["body_review"],
        "body_review_sha256": persisted["body_review_sha256"],
        **source_authority,
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