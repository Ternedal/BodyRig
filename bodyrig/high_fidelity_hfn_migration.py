from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import high_fidelity_continuation_status_legacy as legacy_status
from .high_fidelity_preview_jobs import HighFidelityPreviewError, ROOT_DIRNAME, manager as preview_manager
from .storage import ui_jobs_dir

FORMAT = "bodyrig-high-fidelity-hfn-migration"
VERSION = 1
RECEIPT_NAME = "migration-authority.json"
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
JOB_RE = re.compile(r"^hfpreview-[0-9a-f]{32}$")
FIELDS = {
    "format",
    "version",
    "preview_job_id",
    "person_id",
    "body_revision",
    "canonical_body_id",
    "source_bodyrig_revision",
    "integration_bodyrig_revision",
    "source_package_sha256",
    "created_utc",
    "comparison_only",
    "human_review_required",
    "physical_acceptance_authority",
    "production_activation",
}


class HighFidelityHfnMigrationError(RuntimeError):
    pass


def _is_v1(value: object) -> bool:
    return not isinstance(value, bool) and value == VERSION


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def migration_path(preview_job_id: str) -> Path:
    if not JOB_RE.fullmatch(preview_job_id):
        raise HighFidelityHfnMigrationError("HFN migration preview job id is not canonical")
    return (
        ui_jobs_dir()
        / ROOT_DIRNAME
        / preview_job_id
        / "continuation"
        / "hands-feet-nails"
        / RECEIPT_NAME
    ).resolve()


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityHfnMigrationError(f"HFN migration authority is unreadable: {path}") from exc
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise HighFidelityHfnMigrationError("HFN migration authority fields are not canonical")
    if value.get("format") != FORMAT or not _is_v1(value.get("version")):
        raise HighFidelityHfnMigrationError("HFN migration authority format/version is not canonical")
    if value.get("comparison_only") is not True or value.get("human_review_required") is not True:
        raise HighFidelityHfnMigrationError("HFN migration authority crossed its review-only boundary")
    if value.get("physical_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise HighFidelityHfnMigrationError("HFN migration authority cannot create physical/release authority")
    for key in ("source_bodyrig_revision", "integration_bodyrig_revision"):
        if not GIT_RE.fullmatch(str(value.get(key) or "").lower()):
            raise HighFidelityHfnMigrationError(f"HFN migration {key} is not a canonical Git revision")
    if not SHA_RE.fullmatch(str(value.get("source_package_sha256") or "").lower()):
        raise HighFidelityHfnMigrationError("HFN migration source package SHA is not canonical")
    if not JOB_RE.fullmatch(str(value.get("preview_job_id") or "")):
        raise HighFidelityHfnMigrationError("HFN migration preview job id is invalid")
    return value


def read_migration(
    preview_job_id: str,
    *,
    source_bodyrig_revision: str,
    source_package_sha256: str,
) -> dict[str, Any] | None:
    path = migration_path(preview_job_id)
    if not path.is_file():
        return None
    value = _read(path)
    if value["preview_job_id"] != preview_job_id:
        raise HighFidelityHfnMigrationError("HFN migration authority belongs to a different preview")
    if value["source_bodyrig_revision"] != source_bodyrig_revision.lower():
        raise HighFidelityHfnMigrationError("HFN migration source revision differs from the preview producer revision")
    if value["source_package_sha256"] != source_package_sha256.lower():
        raise HighFidelityHfnMigrationError("HFN migration source package differs from the promoted legacy package")
    return value


def prepare_migration(preview_job_id: str, *, integration_bodyrig_revision: str) -> dict[str, Any]:
    integration_revision = str(integration_bodyrig_revision or "").strip().lower()
    if not GIT_RE.fullmatch(integration_revision):
        raise HighFidelityHfnMigrationError("integration BodyRig revision is not a canonical Git SHA")
    try:
        preview = preview_manager.get(preview_job_id)
    except HighFidelityPreviewError as exc:
        raise HighFidelityHfnMigrationError(str(exc)) from exc
    if preview.get("status") != "succeeded":
        raise HighFidelityHfnMigrationError("HFN migration requires a succeeded high-fidelity preview")
    source_revision = str(preview.get("bodyrig_revision") or "").strip().lower()
    if not GIT_RE.fullmatch(source_revision):
        raise HighFidelityHfnMigrationError("preview producer revision is not canonical")
    if source_revision == integration_revision:
        raise HighFidelityHfnMigrationError("HFN migration is unnecessary when preview and integration revisions match")

    try:
        legacy = legacy_status.inspect_continuation(preview_job_id)
    except Exception as exc:
        raise HighFidelityHfnMigrationError(f"legacy high-fidelity continuation could not be revalidated: {exc}") from exc
    if legacy.get("high_fidelity_complete") is not True:
        raise HighFidelityHfnMigrationError(
            "HFN migration requires the historical anatomy/hair/eyes/face-secondary continuation to be complete"
        )
    package_value = str(legacy.get("current_package_path") or "").strip()
    package_sha = str(legacy.get("current_package_sha256") or "").strip().lower()
    package = Path(package_value).expanduser().resolve() if package_value else None
    if package is None or not package.is_file() or not SHA_RE.fullmatch(package_sha) or _sha256(package) != package_sha:
        raise HighFidelityHfnMigrationError("legacy promoted package bytes are missing or no longer match continuation authority")

    person_id = str(preview.get("person_id") or "").strip().lower()
    body_revision = str(preview.get("body_revision") or "").strip().lower()
    canonical_body_id = str(preview.get("canonical_body_id") or "").strip()
    if not person_id or not body_revision or not canonical_body_id:
        raise HighFidelityHfnMigrationError("preview lacks canonical Person/body identity for HFN migration")

    path = migration_path(preview_job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_migration(
        preview_job_id,
        source_bodyrig_revision=source_revision,
        source_package_sha256=package_sha,
    )
    if existing is not None:
        if existing["integration_bodyrig_revision"] != integration_revision:
            raise HighFidelityHfnMigrationError(
                "HFN migration authority is create-only and already binds a different integration revision"
            )
        return {**existing, "path": str(path), "sha256": _sha256(path)}

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "preview_job_id": preview_job_id,
        "person_id": person_id,
        "body_revision": body_revision,
        "canonical_body_id": canonical_body_id,
        "source_bodyrig_revision": source_revision,
        "integration_bodyrig_revision": integration_revision,
        "source_package_sha256": package_sha,
        "created_utc": _now(),
        "comparison_only": True,
        "human_review_required": True,
        "physical_acceptance_authority": False,
        "production_activation": False,
    }
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise HighFidelityHfnMigrationError("HFN migration authority appeared concurrently; rerun status") from exc
    validated = read_migration(
        preview_job_id,
        source_bodyrig_revision=source_revision,
        source_package_sha256=package_sha,
    )
    if validated is None or validated["integration_bodyrig_revision"] != integration_revision:
        path.unlink(missing_ok=True)
        raise HighFidelityHfnMigrationError("persisted HFN migration authority failed readback validation")
    return {**validated, "path": str(path), "sha256": _sha256(path)}
