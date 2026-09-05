from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .acceptance_status import AcceptanceStatusError, _validate_gate_a, inspect_acceptance_dir
from .high_fidelity_continuation_status import (
    HighFidelityContinuationStatusError,
    continuation_paths,
    inspect_continuation,
)
from .high_fidelity_human_review import (
    HighFidelityHumanReviewError,
    read_review as read_human_review,
    review_path as human_review_path,
)
from .high_fidelity_package_audit import HighFidelityPackageAuditError, audit_high_fidelity_package
from .high_fidelity_preview_jobs import HighFidelityPreviewError, manager as preview_manager
from .materialize import materialize_runtime
from .mesh_topology_qa import analyze_package as analyze_topology
from .package import MRBodyError, validate_package
from .skin_qa import SkinQaError, analyze_package as analyze_skin
from .storage import ui_jobs_dir
from .ui_jobs import UiJobError, manager as ui_jobs

FORMAT = "bodyrig-high-fidelity-physical-handoff"
VERSION = 1
RECEIPT_NAME = "bodyrig-high-fidelity-physical-handoff.json"
ACCEPTANCE_DIRNAME = "physical-acceptance"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")


class HighFidelityPhysicalAcceptanceError(RuntimeError):
    pass


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityPhysicalAcceptanceError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise HighFidelityPhysicalAcceptanceError(f"{label} must be an object: {path}")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise HighFidelityPhysicalAcceptanceError(f"{label} is not a canonical SHA-256")
    return text


def _revision(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise HighFidelityPhysicalAcceptanceError("BodyRig revision is not a canonical Git SHA")
    return text


def physical_acceptance_dir(preview_job_id: str) -> Path:
    try:
        return (continuation_paths(preview_job_id)["continuation_root"] / ACCEPTANCE_DIRNAME).resolve()
    except HighFidelityContinuationStatusError as exc:
        raise HighFidelityPhysicalAcceptanceError(str(exc)) from exc


def _ready_package(preview_job_id: str) -> tuple[Path, str, dict[str, Any], dict[str, Any]]:
    try:
        status = inspect_continuation(preview_job_id)
    except HighFidelityContinuationStatusError as exc:
        raise HighFidelityPhysicalAcceptanceError(str(exc)) from exc
    if status.get("high_fidelity_complete") is not True:
        raise HighFidelityPhysicalAcceptanceError("final promoted package is not component-complete")
    package = Path(str(status.get("current_package_path") or "")).expanduser().resolve()
    expected = _sha(status.get("current_package_sha256"), "final promoted package SHA")
    if not package.is_file() or _hash(package) != expected:
        raise HighFidelityPhysicalAcceptanceError("final promoted package bytes no longer match continuation authority")
    try:
        audit = audit_high_fidelity_package(package)
        review = read_human_review(package)
    except (OSError, HighFidelityPackageAuditError, HighFidelityHumanReviewError) as exc:
        raise HighFidelityPhysicalAcceptanceError(str(exc)) from exc
    components = dict(audit.get("components") or {})
    if (
        audit.get("package_sha256") != expected
        or audit.get("high_fidelity_ready") is not True
        or not components
        or any(value != "complete" for value in components.values())
        or review.get("human_review_complete") is not True
        or review.get("production_activation") is not False
    ):
        raise HighFidelityPhysicalAcceptanceError("final package/review authority is not ready for physical handoff")
    if _hash(package) != expected:
        raise HighFidelityPhysicalAcceptanceError("final promoted package changed during handoff validation")
    return package, expected, audit, review


def _source_gate(preview_job_id: str) -> tuple[dict[str, Any], dict[str, Any], Path, Any, dict[str, Any]]:
    try:
        preview = preview_manager.get(preview_job_id)
    except HighFidelityPreviewError as exc:
        raise HighFidelityPhysicalAcceptanceError(str(exc)) from exc
    if preview.get("status") != "succeeded":
        raise HighFidelityPhysicalAcceptanceError("physical handoff requires a succeeded high-fidelity preview")
    body_job_id = str(preview.get("body_job_id") or "")
    try:
        body_job = ui_jobs.get(body_job_id)
    except UiJobError as exc:
        raise HighFidelityPhysicalAcceptanceError(str(exc)) from exc
    if body_job.get("kind") != "body-build" or body_job.get("status") != "succeeded":
        raise HighFidelityPhysicalAcceptanceError("source body-build job is not a succeeded physical build")
    if str(body_job.get("canonical_body_id") or "") != str(preview.get("canonical_body_id") or ""):
        raise HighFidelityPhysicalAcceptanceError("preview/body-build body identity no longer matches")
    source = Path(str(body_job.get("acceptance_dir") or "")).expanduser().resolve()
    root = (ui_jobs_dir() / body_job_id).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise HighFidelityPhysicalAcceptanceError("source Gate A escaped its persisted body-build root") from exc
    try:
        gate = _validate_gate_a(source / "bodyrig-acceptance.json")
    except AcceptanceStatusError as exc:
        raise HighFidelityPhysicalAcceptanceError(f"source Gate A is invalid: {exc}") from exc
    return preview, body_job, source, gate, _json(gate.path, "source Gate A")


def _copy(source: Path, destination: Path, label: str) -> str:
    shutil.copyfile(source, destination)
    expected = _hash(source)
    if _hash(destination) != expected:
        raise HighFidelityPhysicalAcceptanceError(f"{label} changed while copying")
    return expected


def _fresh_qa(package: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        skin = analyze_skin(package)
        topology = analyze_topology(package)
    except (OSError, MRBodyError, SkinQaError, ValueError) as exc:
        raise HighFidelityPhysicalAcceptanceError(f"fresh final-package QA failed: {exc}") from exc
    if (
        skin.get("structural_pass") is not True
        or skin.get("manual_review_required") is not True
        or skin.get("automated_assessment") not in {"low-risk", "review"}
    ):
        raise HighFidelityPhysicalAcceptanceError("fresh final-package skin QA did not satisfy Gate A")
    if (
        topology.get("structural_pass") is not True
        or topology.get("manual_review_required") is not True
        or topology.get("automated_assessment") not in {"pass", "review"}
    ):
        raise HighFidelityPhysicalAcceptanceError("fresh final-package topology QA did not satisfy Gate A")
    return skin, topology


def prepare_physical_acceptance(preview_job_id: str, *, bodyrig_revision: str) -> dict[str, Any]:
    revision = _revision(bodyrig_revision)
    package, package_sha, audit, review = _ready_package(preview_job_id)
    preview, body_job, source_dir, source_gate, source_report = _source_gate(preview_job_id)
    body_id = str(audit.get("canonical_body_id") or "")
    if not body_id or body_id != source_gate.body_id or body_id != str(preview.get("canonical_body_id") or ""):
        raise HighFidelityPhysicalAcceptanceError("final package identity differs from the physical source lineage")

    final = physical_acceptance_dir(preview_job_id)
    if final.exists():
        raise HighFidelityPhysicalAcceptanceError(f"physical acceptance output is create-only: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = final.with_name(f".{final.name}.partial-{uuid.uuid4().hex}")
    staging.mkdir()
    moved = False
    verified = False
    try:
        physical = source_report.get("physical_clone")
        if not isinstance(physical, dict) or physical.get("mode") != "stash-sith-high-fidelity":
            raise HighFidelityPhysicalAcceptanceError("source Gate A lacks canonical Stash/SiTH lineage")
        session_sha = _sha(physical.get("session_sha256"), "physical session SHA")
        readiness_sha = _sha(physical.get("readiness_sha256"), "rig readiness SHA")
        source_session = source_dir / "bodyrig-physical-clone-session.json"
        source_readiness = source_dir / "bodyrig-rig-readiness.json"
        if _hash(source_session) != session_sha or _hash(source_readiness) != readiness_sha:
            raise HighFidelityPhysicalAcceptanceError("source physical session/readiness bytes changed")

        accepted = staging / f"{body_id}.mrbody"
        _copy(package, accepted, "promoted package")
        review_source = human_review_path(package, package_sha256=package_sha)
        review_copy = human_review_path(accepted, package_sha256=package_sha)
        review_sha = _copy(review_source, review_copy, "high-fidelity human review")
        if read_human_review(accepted) != review:
            raise HighFidelityPhysicalAcceptanceError("copied human review differs from final review authority")
        _copy(source_session, staging / "bodyrig-physical-clone-session.json", "physical session")
        _copy(source_readiness, staging / "bodyrig-rig-readiness.json", "rig readiness")

        skin, topology = _fresh_qa(accepted)
        skin_path = staging / "bodyrig-skin-qa.json"
        topology_path = staging / "bodyrig-mesh-topology-qa.json"
        _write(skin_path, skin)
        _write(topology_path, topology)
        if skin.get("package_sha256") != package_sha or topology.get("package_sha256") != package_sha:
            raise HighFidelityPhysicalAcceptanceError("fresh QA is not bound to the exact promoted package")

        runtime_dir = staging / "runtime"
        try:
            runtime = materialize_runtime(accepted, runtime_dir)
        except (OSError, MRBodyError) as exc:
            raise HighFidelityPhysicalAcceptanceError(f"runtime materialization failed: {exc}") from exc
        runtime_path = runtime_dir / "runtime-manifest.json"
        runtime_sha = _hash(runtime_path)
        if runtime.manifest.get("body_id") != body_id or runtime.manifest.get("package_sha256") != package_sha:
            raise HighFidelityPhysicalAcceptanceError("materialized runtime differs from the exact promoted package")

        source_gate_sha = _hash(source_gate.path)
        handoff = {
            "format": FORMAT,
            "version": VERSION,
            "previewJobId": preview_job_id,
            "bodyJobId": str(body_job["job_id"]),
            "canonicalBodyId": body_id,
            "bodyrigRevision": revision,
            "sourceGateABodyRigRevision": source_gate.revision,
            "sourceGateASha256": source_gate_sha,
            "sourcePackageSha256": source_gate.package_hash,
            "sourcePhysicalSessionSha256": session_sha,
            "sourceReadinessSha256": readiness_sha,
            "promotedPackageSha256": package_sha,
            "highFidelityHumanReviewSha256": review_sha,
            "skinQaSha256": _hash(skin_path),
            "meshTopologyQaSha256": _hash(topology_path),
            "runtimeManifestSha256": runtime_sha,
            "physicalAcceptanceAuthority": False,
            "productionActivation": False,
        }
        handoff_path = staging / RECEIPT_NAME
        _write(handoff_path, handoff)

        validated = validate_package(accepted)
        gate_report = {
            "format": "bodyrig-rig-acceptance",
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bodyrig_revision": revision,
            "bodyrig_checkout_clean": True,
            "source_count": source_report.get("source_count"),
            "physical_clone": {
                "session_sha256": session_sha,
                "readiness_sha256": readiness_sha,
                "mode": "stash-sith-high-fidelity",
            },
            "skin_qa": {
                "report_sha256": _hash(skin_path),
                "structural_pass": True,
                "automated_assessment": str(skin["automated_assessment"]),
                "manual_review_required": True,
            },
            "mesh_topology_qa": {
                "report_sha256": _hash(topology_path),
                "structural_pass": True,
                "automated_assessment": str(topology["automated_assessment"]),
                "manual_review_required": True,
            },
            "package": {
                "package_sha256": package_sha,
                "body_id": body_id,
                "body_name": str(validated.manifest["name"]),
                "payload_names": list(validated.payload_names),
                "placeholder_avatar": False,
            },
            "runtime": {
                "manifest": "runtime/runtime-manifest.json",
                "manifest_sha256": runtime_sha,
                "materialized_from_package": True,
            },
            "high_fidelity_handoff": {
                "receipt_sha256": _hash(handoff_path),
                "source_gate_a_sha256": source_gate_sha,
                "package_sha256": package_sha,
                "human_review_sha256": review_sha,
                "preview_job_id": preview_job_id,
                "body_job_id": str(body_job["job_id"]),
            },
            "checks": {
                "source_gate_a_validated": True,
                "promoted_package_exact": True,
                "high_fidelity_components_complete": True,
                "package_bound_human_review_complete": True,
                "fresh_skin_qa": True,
                "fresh_mesh_topology_qa": True,
                "runtime_materialized_from_promoted_package": True,
            },
            "automated_pass": True,
            "physical_renderer_acceptance": "pending",
            "production_activation": False,
        }
        gate_path = staging / "bodyrig-acceptance.json"
        _write(gate_path, gate_report)
        try:
            gate = _validate_gate_a(gate_path)
            status = inspect_acceptance_dir(staging)
        except AcceptanceStatusError as exc:
            raise HighFidelityPhysicalAcceptanceError(f"fresh promoted-package Gate A is invalid: {exc}") from exc
        if gate.package_hash != package_sha or gate.body_id != body_id or status.gate != "windows-probe":
            raise HighFidelityPhysicalAcceptanceError("fresh Gate A did not stop at the Windows physical probe")

        os.replace(staging, final)
        moved = True
        status = inspect_acceptance_dir(final)
        if status.gate != "windows-probe":
            raise HighFidelityPhysicalAcceptanceError("committed Gate A did not reopen at the Windows probe")
        verified = True
        return {
            "format": FORMAT,
            "version": VERSION,
            "preview_job_id": preview_job_id,
            "body_job_id": str(body_job["job_id"]),
            "body_id": body_id,
            "bodyrig_revision": revision,
            "package_sha256": package_sha,
            "acceptance_dir": str(final),
            "handoff_receipt_sha256": _hash(final / RECEIPT_NAME),
            "next_gate": status.gate,
            "next_command": status.next_command,
            "production_activation": False,
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if moved and not verified and final.exists():
            shutil.rmtree(final, ignore_errors=True)


def physical_acceptance_status(
    preview_job_id: str,
    *,
    package_path: str | Path,
    package_sha256: str,
) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    expected = _sha(package_sha256, "continuation package SHA")
    acceptance = physical_acceptance_dir(preview_job_id)
    if not package.is_file() or _hash(package) != expected:
        return {
            "state": "invalid", "gate": "physical-gate-a", "acceptance_dir": str(acceptance),
            "message": "continuation promoted package is missing or changed",
            "next_command": None, "production_activation": False,
        }
    if not acceptance.exists():
        return {
            "state": "required", "gate": "physical-gate-a", "acceptance_dir": str(acceptance),
            "message": (
                "Create a fresh Gate A for the exact promoted package. Only the original physical "
                "session/readiness are reused as lineage evidence; old package/runtime acceptance is not reused."
            ),
            "next_command": f".\\prepare-high-fidelity-physical-acceptance.ps1 -PreviewJobId '{preview_job_id}'",
            "production_activation": False,
        }
    if not acceptance.is_dir():
        return {
            "state": "invalid", "gate": "physical-gate-a", "acceptance_dir": str(acceptance),
            "message": "canonical physical acceptance path is not a directory",
            "next_command": None, "production_activation": False,
        }
    try:
        receipt = _json(acceptance / RECEIPT_NAME, "physical handoff receipt")
        if (
            receipt.get("format") != FORMAT
            or receipt.get("version") != VERSION
            or receipt.get("previewJobId") != preview_job_id
            or receipt.get("promotedPackageSha256") != expected
            or receipt.get("physicalAcceptanceAuthority") is not False
            or receipt.get("productionActivation") is not False
        ):
            raise HighFidelityPhysicalAcceptanceError("physical handoff receipt is stale or non-canonical")
        accepted = acceptance / f"{receipt.get('canonicalBodyId')}.mrbody"
        if not accepted.is_file() or _hash(accepted) != expected:
            raise HighFidelityPhysicalAcceptanceError("physical acceptance package copy changed")
        if _hash(human_review_path(accepted, package_sha256=expected)) != receipt.get("highFidelityHumanReviewSha256"):
            raise HighFidelityPhysicalAcceptanceError("physical acceptance human-review copy changed")
        read_human_review(accepted)
        gate = _validate_gate_a(acceptance / "bodyrig-acceptance.json")
        if gate.package_hash != expected or gate.revision != receipt.get("bodyrigRevision"):
            raise HighFidelityPhysicalAcceptanceError("physical Gate A differs from handoff receipt")
        status = inspect_acceptance_dir(acceptance)
    except (OSError, AcceptanceStatusError, HighFidelityHumanReviewError, HighFidelityPhysicalAcceptanceError) as exc:
        return {
            "state": "invalid", "gate": "physical-gate-a", "acceptance_dir": str(acceptance),
            "message": str(exc), "next_command": None, "production_activation": False,
        }
    value = asdict(status)
    return {
        "state": value["state"],
        "gate": value["gate"],
        "acceptance_dir": value["acceptance_dir"],
        "body_id": value["body_id"],
        "bodyrig_revision": value["bodyrig_revision"],
        "message": value["message"],
        "next_command": value["next_command"],
        "production_activation": value["state"] == "complete" and value["gate"] == "release",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare exact final package for canonical physical acceptance")
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_physical_acceptance(args.preview_job_id, bodyrig_revision=args.bodyrig_revision)
    except (HighFidelityPhysicalAcceptanceError, MRBodyError, OSError, ValueError) as exc:
        print(f"BodyRig high-fidelity physical handoff: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
