from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .avatar import validate_vrm1
from .bodyprint_adjustment import apply_adjustment_to_bodyprint, load_adjustment_evidence
from .identity import bind_visual_identity_to_proof
from .mesh_topology_qa import analyze_package as analyze_topology
from .package import validate_package
from .physical_session import validate_session
from .portable_identity import bind_portable_identity_to_evidence, load_portable_identity
from .proof import load_recovery_proof, read_canonical_json
from .skin_qa import write_report as write_skin_report
from .skin_qa_gate import analyze_package as analyze_skin

FORMAT = "bodyrig-gate-a-validation-authority"
VERSION = 1


class GateAResumeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise GateAResumeError(f"{label} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GateAResumeError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise GateAResumeError(f"{label} must be a JSON object: {path}")
    return value


def _create_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise GateAResumeError(f"refusing to overwrite Gate A evidence: {path}") from exc


def _copy_exact(source: Path, destination: Path, *, label: str) -> None:
    if not source.is_file():
        raise GateAResumeError(f"{label} not found: {source}")
    shutil.copyfile(source, destination)
    if _sha256(source) != _sha256(destination):
        raise GateAResumeError(f"{label} changed while copying into resumed Gate A")


def _need_revision(value: str, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 40 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise GateAResumeError(f"{label} is not a canonical Git SHA")
    return normalized


def _validate_package_lineage(
    *,
    package_path: Path,
    proof_path: Path,
    identity_path: Path,
    portable_identity_path: Path,
    adjustment_path: Path | None,
    requested_alias: str,
) -> dict[str, Any]:
    proof = load_recovery_proof(proof_path)
    identity = bind_visual_identity_to_proof(
        read_canonical_json(identity_path, label="visual identity profile"),
        proof,
    )
    portable = bind_portable_identity_to_evidence(
        load_portable_identity(portable_identity_path),
        proof=proof,
        visual_identity=identity,
        requested_alias=requested_alias,
    )
    package = validate_package(package_path)

    expected_bodyprint = proof["bodyprint"]
    adjustment_sha = None
    if adjustment_path is not None:
        adjustment = load_adjustment_evidence(adjustment_path, proof_path=proof_path)
        expected_bodyprint = apply_adjustment_to_bodyprint(expected_bodyprint, adjustment)
        adjustment_sha = _sha256(adjustment_path)
    if package.bodyprint != expected_bodyprint:
        raise GateAResumeError("resumed package BodyPrint does not match proof-bound derivation")
    if package.provenance["source"]["count"] != proof["source_count"]:
        raise GateAResumeError("resumed package source count does not match recovery proof")
    if package.manifest["id"] != portable["body_id"]:
        raise GateAResumeError("resumed package canonical body identity mismatch")

    pipeline = package.provenance["pipeline"]
    recovery = next((item for item in pipeline if item.get("stage") == "body-recovery"), None)
    visual = next((item for item in pipeline if item.get("stage") == "visual-identity-capture"), None)
    fitting = next((item for item in pipeline if item.get("stage") == "avatar-fitting"), None)
    identity_stages = [item for item in pipeline if item.get("stage") == "identity_content"]
    adjustment_stages = [item for item in pipeline if item.get("stage") == "bodyprint-adjustment"]
    if not recovery or recovery.get("adapter") != proof.get("adapter") or recovery.get("revision") != proof.get("revision"):
        raise GateAResumeError("resumed package recovery provenance mismatch")
    if not visual or visual.get("adapter") != identity.get("adapter") or visual.get("revision") != identity.get("revision"):
        raise GateAResumeError("resumed package visual identity provenance mismatch")
    if not fitting or fitting.get("adapter") != "sith-smplx-vrm" or fitting.get("revision") != "1":
        raise GateAResumeError("resumed Gate A requires the production sith-smplx-vrm v1 fitter")
    expected_identity_revision = portable["body_id"].removeprefix("bodyid-")
    if len(identity_stages) != 1 or identity_stages[0].get("adapter") != "bodyrig.portable_identity" or identity_stages[0].get("revision") != expected_identity_revision:
        raise GateAResumeError("resumed package portable identity provenance mismatch")
    if adjustment_sha is None:
        if adjustment_stages:
            raise GateAResumeError("resumed package contains unexpected BodyPrint adjustment provenance")
    elif len(adjustment_stages) != 1 or adjustment_stages[0].get("adapter") != "bodyrig.bodyprint_adjustment" or adjustment_stages[0].get("revision") != adjustment_sha:
        raise GateAResumeError("resumed package BodyPrint adjustment provenance mismatch")

    with zipfile.ZipFile(package_path, "r") as archive:
        avatar_document = validate_vrm1(archive.read("avatar.vrm"))
    extra = avatar_document.get("extras", {}).get("bodyrig", {})
    if extra.get("placeholder") is True:
        raise GateAResumeError("resumed Gate A refuses a placeholder avatar")
    if avatar_document["extensions"]["VRMC_vrm"]["specVersion"] != "1.0":
        raise GateAResumeError("resumed package avatar is not VRM 1.0")

    return {
        "body_id": portable["body_id"],
        "body_name": package.manifest["name"],
        "payload_names": list(package.payload_names),
        "source_count": int(proof["source_count"]),
        "recovery_adapter": str(proof["adapter"]),
        "recovery_revision": str(proof["revision"]),
        "track_id": str(proof["track_id"]),
        "observed_frames": int(proof["observed_frames"]),
        "adjustment_sha256": adjustment_sha,
    }


def resume_gate_a(
    *,
    session_report: Path,
    validator_revision: str,
    output_dir: Path,
    python_executable: str,
) -> dict[str, Any]:
    validator_revision = _need_revision(validator_revision, label="validator revision")
    session_report = session_report.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise GateAResumeError(f"resumed Gate A output already exists: {output_dir}")

    session = validate_session(_read_json(session_report, label="physical clone session"))
    if session["status"] != "pass" or session["stage"] != "complete" or session["bodyrig_checkout_clean"] is not True:
        raise GateAResumeError("only a completed clean physical clone PASS can be resumed at Gate A")
    producer_revision = _need_revision(session["bodyrig_revision"], label="physical producer revision")

    readiness_path = session_report.with_suffix(".readiness.json")
    readiness = _read_json(readiness_path, label="physical clone readiness")
    if _sha256(readiness_path) != session["readiness_sha256"]:
        raise GateAResumeError("physical readiness bytes no longer match the completed session")
    if readiness.get("format") != "bodyrig-rig-readiness" or readiness.get("version") != 1 or readiness.get("ready") is not True:
        raise GateAResumeError("physical readiness report is not READY v1 evidence")
    if str(readiness.get("rig_setup_sha256") or "").lower() != session["rig_setup_sha256"]:
        raise GateAResumeError("physical readiness rig setup differs from the completed session")

    clone_root = Path(str(session["clone_output"])).expanduser().resolve()
    clone_dir = clone_root / "clone"
    if not clone_dir.is_dir():
        raise GateAResumeError(f"completed clone artifact directory not found: {clone_dir}")
    requested_alias = str(session["body_id"])
    package_source = clone_dir / f"{requested_alias}.mrbody"
    proof_path = clone_dir / "bodyrig-recovery-proof.json"
    identity_path = clone_dir / "bodyrig-visual-identity.json"
    portable_identity_path = clone_dir / "bodyrig-portable-identity.json"
    preflight_path = clone_dir / "bodyrig-recovery-preflight.json"
    adjustment_candidate = clone_dir / "bodyrig-bodyprint-adjustment.json"
    adjustment_path = adjustment_candidate if adjustment_candidate.is_file() else None
    preflight = _read_json(preflight_path, label="recovery preflight")
    if preflight.get("ok") is not True:
        raise GateAResumeError("completed clone recovery preflight is not ok=true")
    if not package_source.is_file():
        raise GateAResumeError(f"completed high-fidelity package not found: {package_source}")

    lineage = _validate_package_lineage(
        package_path=package_source,
        proof_path=proof_path,
        identity_path=identity_path,
        portable_identity_path=portable_identity_path,
        adjustment_path=adjustment_path,
        requested_alias=requested_alias,
    )
    source_package_sha = _sha256(package_source)

    output_dir.mkdir(parents=True)
    committed = False
    try:
        package_path = output_dir / f"{lineage['body_id']}.mrbody"
        session_copy = output_dir / "bodyrig-physical-clone-session.json"
        readiness_copy = output_dir / "bodyrig-rig-readiness.json"
        portable_copy = output_dir / "bodyrig-portable-identity.json"
        _copy_exact(package_source, package_path, label="high-fidelity .mrbody")
        _copy_exact(session_report, session_copy, label="physical clone session")
        _copy_exact(readiness_path, readiness_copy, label="physical readiness")
        _copy_exact(portable_identity_path, portable_copy, label="portable identity")
        if adjustment_path is not None:
            _copy_exact(adjustment_path, output_dir / adjustment_path.name, label="BodyPrint adjustment evidence")
        if _sha256(package_path) != source_package_sha:
            raise GateAResumeError("high-fidelity package changed during resumed Gate A promotion")

        skin = analyze_skin(package_path)
        if skin.get("structural_pass") is not True or skin.get("manual_review_required") is not True:
            raise GateAResumeError("anatomical skin QA did not produce the required structural/manual-review state")
        skin_assessment = str(skin.get("automated_assessment") or "")
        if skin_assessment not in {"low-risk", "review", "high-risk"}:
            raise GateAResumeError("anatomical skin QA assessment is unsupported")
        if skin_assessment == "high-risk":
            raise GateAResumeError("anatomical skin QA is high-risk; resumed Gate A refuses automated acceptance")
        skin_path = output_dir / "bodyrig-skin-qa.json"
        write_skin_report(skin_path, skin)

        topology = analyze_topology(package_path)
        if topology.get("structural_pass") is not True or topology.get("manual_review_required") is not True:
            raise GateAResumeError("mesh topology QA rejected the package structure")
        topology_assessment = str(topology.get("automated_assessment") or "")
        if topology_assessment not in {"pass", "review"}:
            raise GateAResumeError("mesh topology QA assessment is not acceptable for Gate A")
        topology_path = output_dir / "bodyrig-mesh-topology-qa.json"
        _create_json(topology_path, topology)

        runtime_dir = output_dir / "runtime"
        completed = subprocess.run(
            [python_executable, "-m", "bodyrig.materialize_cli", str(package_path), "--out", str(runtime_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-4000:]
            raise GateAResumeError(f"runtime materialization failed: {detail}")
        runtime_manifest_path = runtime_dir / "runtime-manifest.json"
        runtime = _read_json(runtime_manifest_path, label="materialized runtime manifest")
        if runtime.get("format") != "bodyrig-runtime-assets" or runtime.get("version") != 1:
            raise GateAResumeError("materialized runtime manifest format/version mismatch")
        if runtime.get("body_id") != lineage["body_id"] or str(runtime.get("package_sha256") or "").lower() != source_package_sha:
            raise GateAResumeError("materialized runtime identity does not match the resumed package")

        authority = {
            "format": FORMAT,
            "version": VERSION,
            "producer_revision": producer_revision,
            "validator_revision": validator_revision,
            "physical_session_sha256": _sha256(session_report),
            "readiness_sha256": _sha256(readiness_path),
            "package_sha256": source_package_sha,
            "reason": "resume-existing-clone-after-validator-contract-failure",
            "package_rebuilt": False,
            "recovery_rerun": False,
            "fitter_rerun": False,
            "production_activation": False,
        }
        authority_path = output_dir / "bodyrig-gate-a-validation-authority.json"
        _create_json(authority_path, authority)

        checks = {
            "bodyrig_checkout_clean": True,
            "historical_physical_producer_bound": True,
            "validator_revision_bound": True,
            "preflight_ok": True,
            "recovery_adapter_pinned": True,
            "observed_frames_ge_2": lineage["observed_frames"] >= 2,
            "source_derived_shape_present": True,
            "source_derived_motion_present": True,
            "bodyprint_matches_package": True,
            "source_count_matches_package": True,
            "recovery_provenance_matches": True,
            "avatar_fitting_provenance_present": True,
            "avatar_is_vrm_1_0": True,
            "runtime_materialized_from_package": True,
        }
        if not all(checks.values()):
            raise GateAResumeError("resumed Gate A invariant checks are incomplete")

        report = {
            "format": "bodyrig-rig-acceptance",
            "version": 1,
            "bodyrig_revision": validator_revision,
            "bodyrig_checkout_clean": True,
            "producer_revision": producer_revision,
            "source_count": lineage["source_count"],
            "physical_clone": {
                "session_sha256": _sha256(session_copy),
                "readiness_sha256": _sha256(readiness_copy),
                "mode": "stash-sith-high-fidelity",
                "producer_revision": producer_revision,
                "gate_a_resume_authority_sha256": _sha256(authority_path),
            },
            "skin_qa": {
                "report_sha256": _sha256(skin_path),
                "structural_pass": True,
                "automated_assessment": skin_assessment,
                "manual_review_required": True,
            },
            "mesh_topology_qa": {
                "report_sha256": _sha256(topology_path),
                "structural_pass": True,
                "automated_assessment": topology_assessment,
                "manual_review_required": True,
            },
            "recovery": {
                "adapter": lineage["recovery_adapter"],
                "revision": lineage["recovery_revision"],
                "track_id": lineage["track_id"],
                "observed_frames": lineage["observed_frames"],
            },
            "package": {
                "package_sha256": source_package_sha,
                "body_id": lineage["body_id"],
                "body_name": lineage["body_name"],
                "payload_names": lineage["payload_names"],
                "bodyprint_matches_proof": True,
                "source_count_matches": True,
                "recovery_provenance_matches": True,
                "avatar_fitting_provenance_present": True,
                "vrm_spec_version": "1.0",
                "placeholder_avatar": False,
            },
            "runtime": {
                "manifest": "runtime/runtime-manifest.json",
                "manifest_sha256": _sha256(runtime_manifest_path),
                "materialized_from_package": True,
            },
            "checks": checks,
            "automated_pass": True,
            "physical_renderer_acceptance": "pending",
            "production_activation": False,
        }
        report_path = output_dir / "bodyrig-acceptance.json"
        _create_json(report_path, report)
        committed = True
        return {
            "acceptance": str(report_path),
            "package": str(package_path),
            "package_sha256": source_package_sha,
            "body_id": lineage["body_id"],
            "producer_revision": producer_revision,
            "validator_revision": validator_revision,
            "skin_assessment": skin_assessment,
            "topology_assessment": topology_assessment,
            "recovery_rerun": False,
            "fitter_rerun": False,
        }
    finally:
        if not committed and output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resume Gate A from a completed historical BodyRig physical clone without rerunning recovery/fitting.")
    parser.add_argument("--session-report", required=True)
    parser.add_argument("--validator-revision", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        value = resume_gate_a(
            session_report=Path(args.session_report),
            validator_revision=args.validator_revision,
            output_dir=Path(args.out),
            python_executable=sys.executable,
        )
    except Exception as exc:
        print(f"BodyRig resumed Gate A: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
