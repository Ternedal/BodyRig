from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .fidelity_checkpoint import SNAPSHOT_NAMES, load_latest_checkpoint, sha256_file
from .package import validate_package

FORMAT = "bodyrig-fidelity-physical-handoff"
VERSION = 1


class FidelityPhysicalHandoffError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FidelityPhysicalHandoffError(f"{label} not found: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FidelityPhysicalHandoffError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FidelityPhysicalHandoffError(f"{label} must be a JSON object")
    return value


def _relative(root: Path, path: Path, *, label: str) -> str:
    resolved = path.expanduser().resolve()
    try:
        value = resolved.relative_to(root)
    except ValueError as exc:
        raise FidelityPhysicalHandoffError(f"{label} escapes work root: {resolved}") from exc
    return value.as_posix()


def _artifact(root: Path, path: Path, *, scope: str) -> dict[str, str]:
    resolved = path.expanduser().resolve()
    if scope == "work-root":
        stored = _relative(root, resolved, label="handoff artifact")
    elif scope == "private":
        stored = str(resolved)
    else:
        raise FidelityPhysicalHandoffError("handoff artifact scope is invalid")
    return {"path": stored, "sha256": sha256_file(resolved), "scope": scope}


def _resolve_artifact(root: Path, artifact: Mapping[str, Any]) -> Path:
    if not isinstance(artifact, Mapping) or set(artifact) != {"path", "sha256", "scope"}:
        raise FidelityPhysicalHandoffError("handoff artifact fields are invalid")
    scope = artifact.get("scope")
    raw = artifact.get("path")
    expected = artifact.get("sha256")
    if not isinstance(raw, str) or not raw or not isinstance(expected, str) or len(expected) != 64:
        raise FidelityPhysicalHandoffError("handoff artifact path/hash is invalid")
    if scope == "work-root":
        path = (root / raw).resolve()
        _relative(root, path, label="handoff artifact")
    elif scope == "private":
        path = Path(raw).expanduser().resolve()
    else:
        raise FidelityPhysicalHandoffError("handoff artifact scope is invalid")
    if sha256_file(path) != expected:
        raise FidelityPhysicalHandoffError(f"handoff artifact hash mismatch: {raw}")
    return path


def _validate_acceptance(
    *,
    acceptance_path: Path,
    skin_path: Path,
    topology_path: Path,
    package_path: Path,
    expected_revision: str,
    canonical_body_id: str,
) -> dict[str, str]:
    acceptance = _read_json(acceptance_path, label="Gate A acceptance report")
    skin = _read_json(skin_path, label="skin QA report")
    topology = _read_json(topology_path, label="mesh topology QA report")
    package_sha = sha256_file(package_path)

    if acceptance.get("format") != "bodyrig-rig-acceptance" or acceptance.get("version") != 1:
        raise FidelityPhysicalHandoffError("Gate A acceptance format/version is invalid")
    if acceptance.get("bodyrig_revision") != expected_revision or acceptance.get("bodyrig_checkout_clean") is not True:
        raise FidelityPhysicalHandoffError("Gate A acceptance is not bound to the expected clean #40 revision")
    if acceptance.get("automated_pass") is not True:
        raise FidelityPhysicalHandoffError("Gate A did not produce automated_pass=true")
    if acceptance.get("physical_renderer_acceptance") != "pending":
        raise FidelityPhysicalHandoffError("Gate A unexpectedly claims physical renderer acceptance")
    if acceptance.get("production_activation") is not False:
        raise FidelityPhysicalHandoffError("Gate A may not grant production activation")
    checks = acceptance.get("checks")
    if not isinstance(checks, dict) or not checks or any(value is not True for value in checks.values()):
        raise FidelityPhysicalHandoffError("Gate A checks are incomplete or contain a failure")

    for label, report in (("skin", skin), ("topology", topology)):
        if report.get("body_id") != canonical_body_id or str(report.get("package_sha256", "")).lower() != package_sha:
            raise FidelityPhysicalHandoffError(f"{label} QA is not bound to the candidate package")
        if report.get("structural_pass") is not True or report.get("manual_review_required") is not True:
            raise FidelityPhysicalHandoffError(f"{label} QA did not preserve structural/manual-review requirements")

    skin_assessment = skin.get("automated_assessment")
    if skin_assessment not in {"low-risk", "review"}:
        raise FidelityPhysicalHandoffError(f"skin QA is not acceptable for handoff: {skin_assessment}")
    topology_assessment = topology.get("automated_assessment")
    if topology_assessment not in {"pass", "review"}:
        raise FidelityPhysicalHandoffError(f"topology QA is not acceptable for handoff: {topology_assessment}")

    acceptance_skin = acceptance.get("skin_qa")
    acceptance_topology = acceptance.get("mesh_topology_qa")
    if not isinstance(acceptance_skin, dict) or not isinstance(acceptance_topology, dict):
        raise FidelityPhysicalHandoffError("Gate A acceptance is missing embedded QA authority")
    if str(acceptance_skin.get("report_sha256", "")).lower() != sha256_file(skin_path):
        raise FidelityPhysicalHandoffError("Gate A skin-QA hash does not match the report bytes")
    if str(acceptance_topology.get("report_sha256", "")).lower() != sha256_file(topology_path):
        raise FidelityPhysicalHandoffError("Gate A topology-QA hash does not match the report bytes")
    if acceptance_skin.get("automated_assessment") != skin_assessment:
        raise FidelityPhysicalHandoffError("Gate A skin assessment differs from its QA report")
    if acceptance_topology.get("automated_assessment") != topology_assessment:
        raise FidelityPhysicalHandoffError("Gate A topology assessment differs from its QA report")

    return {"skin_assessment": str(skin_assessment), "topology_assessment": str(topology_assessment)}


def seal_physical_handoff(
    *,
    work_root: str | os.PathLike[str],
    rig_setup: str | os.PathLike[str],
    expected_revision: str,
    expected_performer_id: str,
    expected_body_alias: str,
    expected_policy: Mapping[str, Any],
    human_geometry_approved: bool,
) -> dict[str, Any]:
    if human_geometry_approved is not True:
        raise FidelityPhysicalHandoffError(
            "physical handoff requires explicit human geometry approval after reviewing the #40 renders"
        )
    root = Path(work_root).expanduser().resolve()
    rig_path = Path(rig_setup).expanduser().resolve()
    if not root.is_dir():
        raise FidelityPhysicalHandoffError(f"work root not found: {root}")
    rig_sha = sha256_file(rig_path)

    checkpoint_path, checkpoint = load_latest_checkpoint(
        root / "checkpoints",
        work_root=root,
        expected_revision=expected_revision,
        expected_performer_id=expected_performer_id,
        expected_body_alias=expected_body_alias,
        expected_policy=expected_policy,
        expected_rig_setup_sha256=rig_sha,
    )
    state = checkpoint["state"]
    if checkpoint["stage"] != "post-candidate":
        raise FidelityPhysicalHandoffError("#40 handoff requires a post-candidate checkpoint")
    if state["full_rebuilds_completed"] != 1 or state["refinements_completed"] != 0 or state["current_rebuild_refinements"] != 0:
        raise FidelityPhysicalHandoffError("#40 handoff is not the planned one-rebuild / zero-refinement run")
    records = state["candidate_records"]
    if len(records) != 1 or records[0]["mode"] != "full-reconstruction":
        raise FidelityPhysicalHandoffError("#40 handoff requires exactly one full-reconstruction candidate")
    record = records[0]
    if not record["acceptance_dir"]:
        raise FidelityPhysicalHandoffError("#40 candidate has no Gate A acceptance directory")

    package_path = (root / record["package_path"]).resolve()
    evaluation_path = (root / record["evaluation_path"]).resolve()
    render_dir = (root / record["render_dir"]).resolve()
    acceptance_dir = (root / record["acceptance_dir"]).resolve()
    for label, path in (
        ("candidate package", package_path),
        ("candidate evaluation", evaluation_path),
        ("Gate A acceptance directory", acceptance_dir),
    ):
        if label.endswith("directory"):
            if not path.is_dir():
                raise FidelityPhysicalHandoffError(f"{label} not found: {path}")
        elif not path.is_file():
            raise FidelityPhysicalHandoffError(f"{label} not found: {path}")
        _relative(root, path, label=label)

    validated = validate_package(package_path)
    canonical_body_id = str(validated.manifest["id"])
    acceptance_package_candidates = sorted(acceptance_dir.glob("*.mrbody"))
    if len(acceptance_package_candidates) != 1:
        raise FidelityPhysicalHandoffError("Gate A acceptance must contain exactly one .mrbody package")
    acceptance_package = acceptance_package_candidates[0]
    if sha256_file(acceptance_package) != sha256_file(package_path):
        raise FidelityPhysicalHandoffError("Gate A package bytes differ from the evaluated #40 candidate")

    acceptance_path = acceptance_dir / "bodyrig-acceptance.json"
    skin_path = acceptance_dir / "bodyrig-skin-qa.json"
    topology_path = acceptance_dir / "bodyrig-mesh-topology-qa.json"
    qa = _validate_acceptance(
        acceptance_path=acceptance_path,
        skin_path=skin_path,
        topology_path=topology_path,
        package_path=package_path,
        expected_revision=expected_revision,
        canonical_body_id=canonical_body_id,
    )

    snapshot_dir = render_dir / "snapshots"
    snapshots = [snapshot_dir / name for name in SNAPSHOT_NAMES]
    for path in snapshots:
        if not path.is_file():
            raise FidelityPhysicalHandoffError(f"canonical #40 render evidence is missing: {path}")

    workspace = Path(state["current_identity_workspace"]).expanduser().resolve()
    reconstruction = workspace / "sith-input-v1" / "reconstruction.json"
    authority_path = workspace / "sith-input-v1" / "reconstruction-authority.json"
    authority = _read_json(authority_path, label="SiTH reconstruction authority")
    reconstruction_sha = sha256_file(reconstruction)
    if authority.get("format") != "bodyrig-sith-reconstruction-authority" or authority.get("version") != 1:
        raise FidelityPhysicalHandoffError("SiTH reconstruction authority format/version is invalid")
    if str(authority.get("reconstruction_sha256", "")).lower() != reconstruction_sha:
        raise FidelityPhysicalHandoffError("SiTH reconstruction authority does not bind reconstruction bytes")
    if authority.get("smplx_fit_profile") != "gender-aware-final-params-canonical-obj-v1":
        raise FidelityPhysicalHandoffError("SiTH reconstruction authority uses an unexpected SMPL-X fit profile")
    gender = str(authority.get("body_model_gender", "")).lower()
    if gender not in {"female", "male", "neutral"}:
        raise FidelityPhysicalHandoffError("SiTH reconstruction authority has an invalid body-model gender")

    artifacts = [
        _artifact(root, checkpoint_path, scope="work-root"),
        _artifact(root, package_path, scope="work-root"),
        _artifact(root, evaluation_path, scope="work-root"),
        _artifact(root, acceptance_package, scope="work-root"),
        _artifact(root, acceptance_path, scope="work-root"),
        _artifact(root, skin_path, scope="work-root"),
        _artifact(root, topology_path, scope="work-root"),
        _artifact(root, rig_path, scope="private"),
        _artifact(root, reconstruction, scope="private"),
        _artifact(root, authority_path, scope="private"),
    ]
    artifacts.extend(_artifact(root, path, scope="work-root") for path in snapshots)

    return {
        "format": FORMAT,
        "version": VERSION,
        "bodyrig_revision": expected_revision,
        "performer_id": expected_performer_id,
        "body_alias": expected_body_alias,
        "canonical_body_id": canonical_body_id,
        "policy": dict(expected_policy),
        "checkpoint": {
            "path": _relative(root, checkpoint_path, label="checkpoint"),
            "sha256": sha256_file(checkpoint_path),
            "sequence": checkpoint["sequence"],
            "stage": checkpoint["stage"],
        },
        "gate_a": {
            "acceptance_dir": _relative(root, acceptance_dir, label="acceptance directory"),
            "automated_pass": True,
            "skin_assessment": qa["skin_assessment"],
            "topology_assessment": qa["topology_assessment"],
        },
        "reconstruction": {
            "sha256": reconstruction_sha,
            "authority_sha256": sha256_file(authority_path),
            "body_model_gender": gender,
        },
        "human_review": {
            "geometry_approved": True,
            "scope": "closed armholes/no membrane faces/stable body silhouette and topology; face/appearance remain separately reviewable",
        },
        "artifacts": artifacts,
        "human_visual_authority_required": True,
        "production_activation": False,
    }


def verify_physical_handoff(
    receipt: Mapping[str, Any],
    *,
    work_root: str | os.PathLike[str],
    rig_setup: str | os.PathLike[str],
    expected_revision: str,
    expected_performer_id: str,
    expected_body_alias: str,
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise FidelityPhysicalHandoffError("physical handoff receipt must be an object")
    required = {
        "format", "version", "bodyrig_revision", "performer_id", "body_alias", "canonical_body_id",
        "policy", "checkpoint", "gate_a", "reconstruction", "human_review", "artifacts",
        "human_visual_authority_required", "production_activation",
    }
    if set(receipt) != required or receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise FidelityPhysicalHandoffError("unsupported physical handoff receipt")
    if receipt.get("bodyrig_revision") != expected_revision:
        raise FidelityPhysicalHandoffError("physical handoff revision mismatch")
    if receipt.get("performer_id") != expected_performer_id or receipt.get("body_alias") != expected_body_alias:
        raise FidelityPhysicalHandoffError("physical handoff performer/body alias mismatch")
    if receipt.get("human_visual_authority_required") is not True or receipt.get("production_activation") is not False:
        raise FidelityPhysicalHandoffError("physical handoff authority flags are invalid")
    human = receipt.get("human_review")
    if not isinstance(human, Mapping) or human.get("geometry_approved") is not True:
        raise FidelityPhysicalHandoffError("physical handoff lacks explicit human geometry approval")

    root = Path(work_root).expanduser().resolve()
    rig_path = Path(rig_setup).expanduser().resolve()
    if not root.is_dir():
        raise FidelityPhysicalHandoffError(f"work root not found: {root}")
    policy = receipt.get("policy")
    if not isinstance(policy, Mapping):
        raise FidelityPhysicalHandoffError("physical handoff policy is invalid")
    checkpoint_path, checkpoint = load_latest_checkpoint(
        root / "checkpoints",
        work_root=root,
        expected_revision=expected_revision,
        expected_performer_id=expected_performer_id,
        expected_body_alias=expected_body_alias,
        expected_policy=policy,
        expected_rig_setup_sha256=sha256_file(rig_path),
    )
    checkpoint_receipt = receipt.get("checkpoint")
    if not isinstance(checkpoint_receipt, Mapping):
        raise FidelityPhysicalHandoffError("physical handoff checkpoint authority is invalid")
    if checkpoint_receipt.get("path") != _relative(root, checkpoint_path, label="checkpoint"):
        raise FidelityPhysicalHandoffError("physical handoff no longer references the latest checkpoint")
    if checkpoint_receipt.get("sha256") != sha256_file(checkpoint_path):
        raise FidelityPhysicalHandoffError("physical handoff checkpoint bytes changed")
    if checkpoint["stage"] != "post-candidate":
        raise FidelityPhysicalHandoffError("physical handoff latest checkpoint is no longer post-candidate")

    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise FidelityPhysicalHandoffError("physical handoff artifacts are missing")
    resolved = [_resolve_artifact(root, artifact) for artifact in artifacts]
    if len({str(path) for path in resolved}) != len(resolved):
        raise FidelityPhysicalHandoffError("physical handoff contains duplicate artifact paths")

    gate = receipt.get("gate_a")
    reconstruction_receipt = receipt.get("reconstruction")
    if not isinstance(gate, Mapping) or gate.get("automated_pass") is not True:
        raise FidelityPhysicalHandoffError("physical handoff Gate A authority is invalid")
    if gate.get("skin_assessment") not in {"low-risk", "review"} or gate.get("topology_assessment") not in {"pass", "review"}:
        raise FidelityPhysicalHandoffError("physical handoff QA assessments are invalid")
    if not isinstance(reconstruction_receipt, Mapping):
        raise FidelityPhysicalHandoffError("physical handoff reconstruction authority is invalid")

    return dict(receipt)
