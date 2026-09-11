from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_authority import validate_authoritative_bundle
from .photoidentity_evidence import DETAIL_QUALITY_THRESHOLD, PhotoIdentityEvidenceError
from .photoidentity_multiperformer_detail_aggregate import (
    FORMAT as MULTIPERFORMER_DETAIL_FORMAT,
    POLICY_REVISION as MULTIPERFORMER_DETAIL_POLICY_REVISION,
    VERSION as MULTIPERFORMER_DETAIL_VERSION,
)
from .photoidentity_source_chain import POLICY_REVISION as SOURCE_CHAIN_POLICY_REVISION
from .photoidentity_source_chain import validate_registration_source_chain
from .photoidentity_target_crop_quality_attestation import (
    ADAPTER as TARGET_DETAIL_ADAPTER,
    ADAPTER_REVISION as TARGET_DETAIL_REVISION,
    DOMAIN_MACHINE_AUTHORITY as TARGET_DETAIL_MACHINE_AUTHORITY,
    FORMAT as TARGET_DETAIL_FORMAT,
    HUMAN_ONLY_DOMAINS as TARGET_DETAIL_HUMAN_ONLY_DOMAINS,
    HUMAN_QUALITY_BASIS as TARGET_DETAIL_HUMAN_QUALITY_BASIS,
    POLICY as TARGET_DETAIL_POLICY,
    SUPPORTED_QUALITY_DOMAINS as TARGET_DETAIL_SUPPORTED_DOMAINS,
    VERSION as TARGET_DETAIL_VERSION,
)
from .storage import ui_jobs_dir
from .ui_jobs import UiJobError, manager as ui_jobs

FORMAT = "bodyrig-photoidentity-body-job-authority"
VERSION = 3
DIRNAME = "photoidentity-evidence"
RECEIPT_NAME = "photoidentity-authority.json"
REPORT_NAME = "photoidentity-evidence.json"
OBSERVATIONS_NAME = "photoidentity-observations.json"
SOURCE_AUTHORITY_DIRNAME = "source-authority"
NAIL_ATTESTATION_NAME = "nail-source-attestation.json"
ANATOMY_ATTESTATION_NAME = "anatomy-source-attestation.json"
MULTIPERFORMER_DETAIL_DIRNAME = "multiperformer-detail"
MULTIPERFORMER_AGGREGATION_NAME = "aggregation.json"
MULTIPERFORMER_QUALITY_DIRNAME = "quality-receipts"


class PhotoIdentityRegistryError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityRegistryError(f"photoidentity registry file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(value: object, *, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise PhotoIdentityRegistryError(f"{label} is not a canonical SHA-256")
    return digest


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityRegistryError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityRegistryError(f"{label} must be a JSON object")
    return value


def _job_authority(body_job_id: str) -> tuple[dict[str, Any], str, str, Path, str]:
    try:
        job = ui_jobs.get(body_job_id)
    except UiJobError as exc:
        raise PhotoIdentityRegistryError(str(exc)) from exc
    if job.get("kind") != "body-build" or job.get("status") != "succeeded":
        raise PhotoIdentityRegistryError("photoidentity authority requires a succeeded body-build job")
    person_id = str(job.get("person_id") or "").strip()
    revision = str(job.get("bodyrig_revision") or "").strip().lower()
    if not person_id or len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PhotoIdentityRegistryError("body-build lacks canonical Person/BodyRig revision authority")
    source_authority = job.get("source_enqueue_authority")
    if not isinstance(source_authority, dict):
        raise PhotoIdentityRegistryError(
            "body-build predates exact source enqueue authority; photoidentity evidence cannot be attached retroactively"
        )
    if (
        source_authority.get("format") != "bodyrig-body-build-source-enqueue-authority"
        or source_authority.get("version") != 1
        or source_authority.get("job_id") != body_job_id
        or source_authority.get("person_id") != person_id
        or str(source_authority.get("expected_bodyrig_revision") or "").lower() != revision
    ):
        raise PhotoIdentityRegistryError("body-build source enqueue authority is invalid")
    performer_id = str(source_authority.get("stash_performer_id") or "").strip()
    if not performer_id:
        raise PhotoIdentityRegistryError("body-build source authority lacks Stash performer identity")
    job_root = (ui_jobs_dir() / body_job_id).resolve()
    clone_output = Path(str(job.get("clone_output") or "")).expanduser().resolve()
    try:
        clone_output.relative_to(job_root)
    except ValueError as exc:
        raise PhotoIdentityRegistryError("body-build clone output escaped its persisted job root") from exc
    baseline_manifest = clone_output / "bodyrig-stash-source-manifest.json"
    if not baseline_manifest.is_file():
        raise PhotoIdentityRegistryError("body-build baseline Stash source manifest is missing")
    return job, performer_id, revision, job_root, _sha256(baseline_manifest)


def _write_json_create_only(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise PhotoIdentityRegistryError(f"photoidentity registry output already exists: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _persisted_human_receipt(path: Path, *, expected_format: str, expected_sha: str, label: str) -> dict[str, Any]:
    if _sha256(path) != expected_sha:
        raise PhotoIdentityRegistryError(f"registered {label} receipt hash mismatch")
    value = _read_json(path, label=f"registered {label} receipt")
    if (
        value.get("format") != expected_format
        or value.get("version") != 1
        or value.get("operator_supplied") is not True
        or value.get("source_grounded") is not True
        or value.get("generic_guessing_permitted") is not False
        or value.get("production_activation") is not False
    ):
        raise PhotoIdentityRegistryError(f"registered {label} receipt authority boundary is invalid")
    return value


def _target_detail_claims(observations_path: Path) -> dict[str, list[dict[str, Any]]]:
    observations = _read_json(observations_path, label="registered photoidentity observations")
    details = observations.get("detail_evidence")
    if not isinstance(details, Mapping):
        raise PhotoIdentityRegistryError("registered photoidentity detail evidence is invalid")
    result: dict[str, list[dict[str, Any]]] = {}
    for domain, raw_claims in details.items():
        if not isinstance(raw_claims, list):
            continue
        selected: list[dict[str, Any]] = []
        for raw in raw_claims:
            if not isinstance(raw, Mapping):
                continue
            if (
                str(raw.get("adapter") or "") == TARGET_DETAIL_ADAPTER
                and str(raw.get("revision") or "") == TARGET_DETAIL_REVISION
            ):
                quality = raw.get("quality")
                if isinstance(quality, bool) or not isinstance(quality, (int, float)):
                    raise PhotoIdentityRegistryError("registered multi-performer target-detail quality is not numeric")
                numeric = float(quality)
                if not math.isfinite(numeric) or numeric < DETAIL_QUALITY_THRESHOLD or numeric > 1.0:
                    raise PhotoIdentityRegistryError("registered multi-performer target-detail quality is invalid")
                if raw.get("source_derived") is not True:
                    raise PhotoIdentityRegistryError("registered multi-performer target-detail claim is not source-derived")
                scene_id = str(raw.get("scene_id") or "").strip()
                if not scene_id:
                    raise PhotoIdentityRegistryError("registered multi-performer target-detail scene is missing")
                selected.append(
                    {
                        "scene_id": scene_id,
                        "quality": round(numeric, 4),
                        "source_derived": True,
                        "adapter": TARGET_DETAIL_ADAPTER,
                        "revision": TARGET_DETAIL_REVISION,
                    }
                )
        if selected:
            selected.sort(key=lambda item: (item["scene_id"], item["quality"]))
            result[str(domain)] = selected
    return result


def _quality_receipt_claims(path: Path, *, performer_id: str, revision: str) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    receipt = _read_json(path, label="registered multi-performer quality receipt")
    if (
        receipt.get("format") != TARGET_DETAIL_FORMAT
        or receipt.get("version") != TARGET_DETAIL_VERSION
        or receipt.get("policy") != TARGET_DETAIL_POLICY
        or receipt.get("adapter") != TARGET_DETAIL_ADAPTER
        or receipt.get("adapter_revision") != TARGET_DETAIL_REVISION
        or receipt.get("human_source_detail_quality_attested") is not True
        or receipt.get("source_detail_quality_authority") is not True
        or receipt.get("photoidentity_source_evidence_authority") is not False
        or receipt.get("generic_guessing_permitted") is not False
        or receipt.get("reconstruction_permitted") is not False
        or receipt.get("production_activation") is not False
    ):
        raise PhotoIdentityRegistryError("registered multi-performer quality receipt authority boundary is invalid")
    if str(receipt.get("performer_id") or "") != performer_id:
        raise PhotoIdentityRegistryError("registered multi-performer quality receipt performer changed")
    if str(receipt.get("bodyrig_revision") or "") != revision:
        raise PhotoIdentityRegistryError("registered multi-performer quality receipt revision changed")
    scene_id = str(receipt.get("scene_id") or "").strip()
    if not scene_id:
        raise PhotoIdentityRegistryError("registered multi-performer quality receipt scene is missing")
    note = str(receipt.get("quality_note") or "").strip()
    if len(note) < 20 or (note.startswith("<") and note.endswith(">")):
        raise PhotoIdentityRegistryError("registered multi-performer quality receipt lacks a real source-review note")
    for field in (
        "human_target_isolation_attestation_sha256",
        "target_crop_detail_enrichment_sha256",
        "private_analysis_index_sha256",
    ):
        _canonical_sha(receipt.get(field), label=f"registered {field}")

    raw_claims = receipt.get("selected_claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise PhotoIdentityRegistryError("registered multi-performer quality receipt has no selected claims")
    domains: set[str] = set()
    claims: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_claims:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityRegistryError("registered multi-performer quality claim is invalid")
        domain = str(raw.get("domain") or "")
        if domain not in TARGET_DETAIL_SUPPORTED_DOMAINS or domain in domains:
            raise PhotoIdentityRegistryError("registered multi-performer quality claim domain is invalid/duplicate")
        domains.add(domain)
        if str(raw.get("scene_id") or "") != scene_id:
            raise PhotoIdentityRegistryError("registered multi-performer quality claim scene changed")
        if raw.get("source_derived") is not True:
            raise PhotoIdentityRegistryError("registered multi-performer quality claim is not source-derived")
        if str(raw.get("adapter") or "") != TARGET_DETAIL_ADAPTER or str(raw.get("revision") or "") != TARGET_DETAIL_REVISION:
            raise PhotoIdentityRegistryError("registered multi-performer quality claim adapter/revision changed")
        if domain in TARGET_DETAIL_HUMAN_ONLY_DOMAINS:
            if (
                raw.get("quality_basis") != TARGET_DETAIL_HUMAN_QUALITY_BASIS
                or raw.get("human_visibility_attested") is not True
                or raw.get("machine_observability_used") is not False
                or "machine_adapter" in raw
                or "machine_revision" in raw
            ):
                raise PhotoIdentityRegistryError("registered human-only hair claim authority boundary changed")
        else:
            expected_machine_adapter, expected_machine_revision = TARGET_DETAIL_MACHINE_AUTHORITY[domain]
            if (
                str(raw.get("machine_adapter") or "") != expected_machine_adapter
                or str(raw.get("machine_revision") or "") != expected_machine_revision
            ):
                raise PhotoIdentityRegistryError("registered multi-performer quality claim machine provenance changed")
        _canonical_sha(raw.get("target_crop_sha256"), label="registered target-crop SHA-256")
        quality = raw.get("quality")
        if isinstance(quality, bool) or not isinstance(quality, (int, float)):
            raise PhotoIdentityRegistryError("registered multi-performer quality claim score is not numeric")
        numeric = float(quality)
        if not math.isfinite(numeric) or numeric < DETAIL_QUALITY_THRESHOLD or numeric > 1.0:
            raise PhotoIdentityRegistryError("registered multi-performer quality claim score is invalid")
        claims.setdefault(domain, []).append(
            {
                "scene_id": scene_id,
                "quality": round(numeric, 4),
                "source_derived": True,
                "adapter": TARGET_DETAIL_ADAPTER,
                "revision": TARGET_DETAIL_REVISION,
            }
        )
    if set(receipt.get("selected_domains") or []) != domains:
        raise PhotoIdentityRegistryError("registered multi-performer quality selected-domain summary changed")
    return receipt, claims


def _validate_persisted_multiperformer_lineage(
    *,
    root: Path,
    authority_receipt: Mapping[str, Any],
    observations_path: Path,
    nail_receipt_path: Path,
) -> None:
    metadata = authority_receipt.get("multiperformer_detail")
    target_claims = _target_detail_claims(observations_path)
    multi_root = root / SOURCE_AUTHORITY_DIRNAME / MULTIPERFORMER_DETAIL_DIRNAME
    if metadata is None:
        if target_claims:
            raise PhotoIdentityRegistryError(
                "registered target-detail claims lack persisted multi-performer authority lineage"
            )
        if multi_root.exists():
            raise PhotoIdentityRegistryError("unexpected persisted multi-performer authority exists")
        return
    if not isinstance(metadata, Mapping):
        raise PhotoIdentityRegistryError("registered multi-performer authority metadata is invalid")
    required_metadata = {
        "aggregation_receipt_sha256",
        "aggregation_observation_evidence_sha256",
        "aggregation_sufficiency_report_sha256",
        "quality_receipt_sha256s",
    }
    if set(metadata) != required_metadata:
        raise PhotoIdentityRegistryError("registered multi-performer authority metadata fields are invalid")
    aggregation_sha = _canonical_sha(
        metadata.get("aggregation_receipt_sha256"),
        label="registered multi-performer aggregation receipt SHA",
    )
    observation_sha = _canonical_sha(
        metadata.get("aggregation_observation_evidence_sha256"),
        label="registered multi-performer observation SHA",
    )
    report_sha = _canonical_sha(
        metadata.get("aggregation_sufficiency_report_sha256"),
        label="registered multi-performer report SHA",
    )
    raw_quality_hashes = metadata.get("quality_receipt_sha256s")
    if not isinstance(raw_quality_hashes, list) or not raw_quality_hashes:
        raise PhotoIdentityRegistryError("registered multi-performer quality receipt hashes are missing")
    quality_hashes = [
        _canonical_sha(value, label="registered multi-performer quality receipt SHA")
        for value in raw_quality_hashes
    ]
    if quality_hashes != sorted(set(quality_hashes)):
        raise PhotoIdentityRegistryError("registered multi-performer quality receipt hashes are non-canonical")

    aggregation_path = multi_root / MULTIPERFORMER_AGGREGATION_NAME
    quality_root = multi_root / MULTIPERFORMER_QUALITY_DIRNAME
    if _sha256(aggregation_path) != aggregation_sha:
        raise PhotoIdentityRegistryError("registered multi-performer aggregation receipt hash mismatch")
    if not quality_root.is_dir():
        raise PhotoIdentityRegistryError("registered multi-performer quality receipt directory is missing")
    actual_quality_names = sorted(path.name for path in quality_root.iterdir() if path.is_file())
    expected_quality_names = [f"quality-{digest}.json" for digest in quality_hashes]
    if actual_quality_names != expected_quality_names:
        raise PhotoIdentityRegistryError("registered multi-performer quality receipt set changed")

    aggregation = _read_json(aggregation_path, label="registered multi-performer aggregation receipt")
    if (
        aggregation.get("format") != MULTIPERFORMER_DETAIL_FORMAT
        or aggregation.get("version") != MULTIPERFORMER_DETAIL_VERSION
        or aggregation.get("policy_revision") != MULTIPERFORMER_DETAIL_POLICY_REVISION
        or aggregation.get("prior_stage") != "human-parsing"
        or aggregation.get("source_grounded") is not True
        or aggregation.get("generic_guessing_permitted") is not False
        or aggregation.get("production_activation") is not False
    ):
        raise PhotoIdentityRegistryError("registered multi-performer aggregation authority boundary is invalid")
    for field in ("performer_id", "bodyrig_revision", "baseline_source_manifest_sha256"):
        receipt_field = {
            "performer_id": "stash_performer_id",
            "bodyrig_revision": "bodyrig_revision",
            "baseline_source_manifest_sha256": "baseline_source_manifest_sha256",
        }[field]
        if str(aggregation.get(field) or "") != str(authority_receipt.get(receipt_field) or ""):
            raise PhotoIdentityRegistryError(f"registered multi-performer aggregation differs on {field}")
    if aggregation.get("enriched_observation_evidence_sha256") != observation_sha:
        raise PhotoIdentityRegistryError("registered multi-performer aggregation observation binding changed")
    if aggregation.get("enriched_sufficiency_report_sha256") != report_sha:
        raise PhotoIdentityRegistryError("registered multi-performer aggregation report binding changed")

    raw_manifest = aggregation.get("quality_receipts")
    if (
        not isinstance(raw_manifest, list)
        or not raw_manifest
        or aggregation.get("quality_receipt_count") != len(raw_manifest)
    ):
        raise PhotoIdentityRegistryError("registered multi-performer quality manifest is invalid")
    manifest_hashes: list[str] = []
    derived_claims: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_manifest:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityRegistryError("registered multi-performer quality manifest row is invalid")
        digest = _canonical_sha(raw.get("receipt_sha256"), label="registered quality manifest SHA")
        expected_name = f"quality-{digest}.json"
        if str(raw.get("stored_name") or "") != expected_name:
            raise PhotoIdentityRegistryError("registered multi-performer quality manifest filename changed")
        path = quality_root / expected_name
        if _sha256(path) != digest:
            raise PhotoIdentityRegistryError("registered multi-performer quality receipt hash mismatch")
        quality_receipt, claims = _quality_receipt_claims(
            path,
            performer_id=str(authority_receipt["stash_performer_id"]),
            revision=str(authority_receipt["bodyrig_revision"]),
        )
        domains = sorted(claims)
        if str(raw.get("scene_id") or "") != str(quality_receipt.get("scene_id") or ""):
            raise PhotoIdentityRegistryError("registered multi-performer quality manifest scene changed")
        if list(raw.get("domains") or []) != domains:
            raise PhotoIdentityRegistryError("registered multi-performer quality manifest domains changed")
        manifest_hashes.append(digest)
        for domain, values in claims.items():
            derived_claims.setdefault(domain, []).extend(values)
    if manifest_hashes != quality_hashes:
        raise PhotoIdentityRegistryError("registered multi-performer quality manifest hashes changed")
    for values in derived_claims.values():
        values.sort(key=lambda item: (item["scene_id"], item["quality"]))
    if not derived_claims or derived_claims != target_claims:
        raise PhotoIdentityRegistryError(
            "registered final target-detail claims do not match persisted multi-performer quality receipts"
        )

    nail_receipt = _read_json(nail_receipt_path, label="registered nail source attestation")
    if nail_receipt.get("prior_stage") != "multiperformer-detail":
        raise PhotoIdentityRegistryError("registered nail authority no longer selects multi-performer detail prior")
    if nail_receipt.get("prior_observation_evidence_sha256") != observation_sha:
        raise PhotoIdentityRegistryError("registered nail authority lost multi-performer observation binding")
    if nail_receipt.get("prior_sufficiency_report_sha256") != report_sha:
        raise PhotoIdentityRegistryError("registered nail authority lost multi-performer report binding")


def register_body_job_photoidentity_evidence(
    body_job_id: str,
    *,
    report_path: str | Path,
    observation_path: str | Path | None = None,
) -> dict[str, Any]:
    job, performer_id, revision, job_root, baseline_sha = _job_authority(body_job_id)
    report_source = Path(report_path).expanduser().resolve()
    observations_source = (
        Path(observation_path).expanduser().resolve()
        if observation_path is not None
        else report_source.with_name(OBSERVATIONS_NAME)
    )
    try:
        chain = validate_registration_source_chain(
            report_source,
            observations_source,
            expected_performer_id=performer_id,
            expected_bodyrig_revision=revision,
            expected_baseline_source_manifest_sha256=baseline_sha,
        )
        report = chain["report"]
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityRegistryError(str(exc)) from exc

    root = job_root / DIRNAME
    if root.exists():
        raise PhotoIdentityRegistryError(
            "body-build photoidentity authority is create-only; existing evidence must not be overwritten"
        )
    root.mkdir(parents=True, exist_ok=False)
    destination_report = root / REPORT_NAME
    destination_observations = root / OBSERVATIONS_NAME
    source_authority_root = root / SOURCE_AUTHORITY_DIRNAME
    source_authority_root.mkdir()
    destination_nail_receipt = source_authority_root / NAIL_ATTESTATION_NAME
    destination_anatomy_receipt = source_authority_root / ANATOMY_ATTESTATION_NAME
    receipt_path = root / RECEIPT_NAME
    try:
        shutil.copyfile(report_source, destination_report)
        shutil.copyfile(observations_source, destination_observations)
        shutil.copyfile(Path(str(chain["nail_attestation"])), destination_nail_receipt)
        shutil.copyfile(Path(str(chain["anatomy_attestation"])), destination_anatomy_receipt)
        if _sha256(destination_report) != _sha256(report_source) or _sha256(destination_observations) != _sha256(observations_source):
            raise PhotoIdentityRegistryError("photoidentity registry evidence copy hash mismatch")
        if _sha256(destination_nail_receipt) != str(chain["nail_attestation_sha256"]):
            raise PhotoIdentityRegistryError("photoidentity registry nail receipt copy hash mismatch")
        if _sha256(destination_anatomy_receipt) != str(chain["anatomy_attestation_sha256"]):
            raise PhotoIdentityRegistryError("photoidentity registry anatomy receipt copy hash mismatch")

        multiperformer_metadata: dict[str, Any] | None = None
        chain_multi = chain.get("multiperformer_detail")
        if chain_multi is not None:
            if not isinstance(chain_multi, Mapping):
                raise PhotoIdentityRegistryError("source chain returned invalid multi-performer lineage")
            source_aggregation = Path(str(chain_multi.get("receipt") or "")).expanduser().resolve()
            source_quality = [
                Path(str(value)).expanduser().resolve()
                for value in list(chain_multi.get("quality_receipts") or [])
            ]
            expected_quality_hashes = [
                _canonical_sha(value, label="source-chain multi-performer quality receipt SHA")
                for value in list(chain_multi.get("quality_receipt_sha256s") or [])
            ]
            if not source_quality or len(source_quality) != len(expected_quality_hashes):
                raise PhotoIdentityRegistryError("source chain multi-performer quality receipt set is invalid")
            pairs = sorted(zip(expected_quality_hashes, source_quality), key=lambda item: item[0])
            if [item[0] for item in pairs] != sorted(set(expected_quality_hashes)):
                raise PhotoIdentityRegistryError("source chain multi-performer quality receipt hashes are non-canonical")
            multi_root = source_authority_root / MULTIPERFORMER_DETAIL_DIRNAME
            quality_root = multi_root / MULTIPERFORMER_QUALITY_DIRNAME
            quality_root.mkdir(parents=True)
            destination_aggregation = multi_root / MULTIPERFORMER_AGGREGATION_NAME
            shutil.copyfile(source_aggregation, destination_aggregation)
            aggregation_sha = _canonical_sha(
                chain_multi.get("receipt_sha256"),
                label="source-chain multi-performer aggregation receipt SHA",
            )
            if _sha256(destination_aggregation) != aggregation_sha:
                raise PhotoIdentityRegistryError("photoidentity registry multi-performer aggregation copy hash mismatch")
            for digest, source_path in pairs:
                destination = quality_root / f"quality-{digest}.json"
                shutil.copyfile(source_path, destination)
                if _sha256(destination) != digest:
                    raise PhotoIdentityRegistryError("photoidentity registry multi-performer quality copy hash mismatch")
            multiperformer_metadata = {
                "aggregation_receipt_sha256": aggregation_sha,
                "aggregation_observation_evidence_sha256": _canonical_sha(
                    chain_multi.get("observation_evidence_sha256"),
                    label="source-chain multi-performer observation SHA",
                ),
                "aggregation_sufficiency_report_sha256": _canonical_sha(
                    chain_multi.get("sufficiency_report_sha256"),
                    label="source-chain multi-performer report SHA",
                ),
                "quality_receipt_sha256s": [item[0] for item in pairs],
            }

        persisted = validate_authoritative_bundle(
            destination_report,
            destination_observations,
            require_sufficient=True,
            expected_performer_id=performer_id,
            expected_bodyrig_revision=revision,
            expected_baseline_source_manifest_sha256=baseline_sha,
        )
        _persisted_human_receipt(
            destination_nail_receipt,
            expected_format="bodyrig-photoidentity-nail-source-attestation",
            expected_sha=str(chain["nail_attestation_sha256"]),
            label="nail source attestation",
        )
        _persisted_human_receipt(
            destination_anatomy_receipt,
            expected_format="bodyrig-photoidentity-anatomy-source-attestation",
            expected_sha=str(chain["anatomy_attestation_sha256"]),
            label="anatomy source attestation",
        )
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "body_job_id": body_job_id,
            "person_id": str(job["person_id"]),
            "stash_performer_id": performer_id,
            "bodyrig_revision": revision,
            "baseline_source_manifest_sha256": baseline_sha,
            "observation_evidence_sha256": _sha256(destination_observations),
            "sufficiency_report_sha256": _sha256(destination_report),
            "source_chain_policy_revision": SOURCE_CHAIN_POLICY_REVISION,
            "nail_attestation_sha256": _sha256(destination_nail_receipt),
            "anatomy_attestation_sha256": _sha256(destination_anatomy_receipt),
            "multiperformer_detail": multiperformer_metadata,
            "source_evidence_sufficient": persisted["source_evidence_sufficient"],
            "reconstruction_permitted": persisted["reconstruction_permitted"],
            "human_review_render_permitted": persisted["human_review_render_permitted"],
            "generic_guessing_permitted": False,
            "production_activation": False,
        }
        _validate_persisted_multiperformer_lineage(
            root=root,
            authority_receipt=receipt,
            observations_path=destination_observations,
            nail_receipt_path=destination_nail_receipt,
        )
        _write_json_create_only(receipt_path, receipt)
        return {**receipt, "receipt_path": str(receipt_path)}
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def require_body_job_photoidentity_evidence(person_id: str, body_job_id: str) -> dict[str, Any]:
    job, performer_id, revision, job_root, baseline_sha = _job_authority(body_job_id)
    if str(job.get("person_id") or "") != str(person_id):
        raise PhotoIdentityRegistryError("photoidentity body-build belongs to a different Person")
    root = job_root / DIRNAME
    receipt_path = root / RECEIPT_NAME
    report_path = root / REPORT_NAME
    observations_path = root / OBSERVATIONS_NAME
    nail_receipt_path = root / SOURCE_AUTHORITY_DIRNAME / NAIL_ATTESTATION_NAME
    anatomy_receipt_path = root / SOURCE_AUTHORITY_DIRNAME / ANATOMY_ATTESTATION_NAME
    if not all(path.is_file() for path in (receipt_path, report_path, observations_path, nail_receipt_path, anatomy_receipt_path)):
        raise PhotoIdentityRegistryError(
            "photoidentity source sufficiency is not fully registered for this body-build; high-fidelity preview remains blocked"
        )
    receipt = _read_json(receipt_path, label="photoidentity body-job authority receipt")
    required = {
        "format",
        "version",
        "body_job_id",
        "person_id",
        "stash_performer_id",
        "bodyrig_revision",
        "baseline_source_manifest_sha256",
        "observation_evidence_sha256",
        "sufficiency_report_sha256",
        "source_chain_policy_revision",
        "nail_attestation_sha256",
        "anatomy_attestation_sha256",
        "multiperformer_detail",
        "source_evidence_sufficient",
        "reconstruction_permitted",
        "human_review_render_permitted",
        "generic_guessing_permitted",
        "production_activation",
    }
    if set(receipt) != required or receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise PhotoIdentityRegistryError("photoidentity body-job authority receipt format/fields are invalid")
    expected = {
        "body_job_id": body_job_id,
        "person_id": str(person_id),
        "stash_performer_id": performer_id,
        "bodyrig_revision": revision,
        "baseline_source_manifest_sha256": baseline_sha,
        "observation_evidence_sha256": _sha256(observations_path),
        "sufficiency_report_sha256": _sha256(report_path),
        "source_chain_policy_revision": SOURCE_CHAIN_POLICY_REVISION,
        "nail_attestation_sha256": _sha256(nail_receipt_path),
        "anatomy_attestation_sha256": _sha256(anatomy_receipt_path),
        "source_evidence_sufficient": True,
        "reconstruction_permitted": True,
        "human_review_render_permitted": True,
        "generic_guessing_permitted": False,
        "production_activation": False,
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise PhotoIdentityRegistryError(f"photoidentity body-job authority mismatch: {field}")
    _persisted_human_receipt(
        nail_receipt_path,
        expected_format="bodyrig-photoidentity-nail-source-attestation",
        expected_sha=str(receipt["nail_attestation_sha256"]),
        label="nail source attestation",
    )
    _persisted_human_receipt(
        anatomy_receipt_path,
        expected_format="bodyrig-photoidentity-anatomy-source-attestation",
        expected_sha=str(receipt["anatomy_attestation_sha256"]),
        label="anatomy source attestation",
    )
    _validate_persisted_multiperformer_lineage(
        root=root,
        authority_receipt=receipt,
        observations_path=observations_path,
        nail_receipt_path=nail_receipt_path,
    )
    try:
        return validate_authoritative_bundle(
            report_path,
            observations_path,
            require_sufficient=True,
            expected_performer_id=performer_id,
            expected_bodyrig_revision=revision,
            expected_baseline_source_manifest_sha256=baseline_sha,
        )
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityRegistryError(str(exc)) from exc
