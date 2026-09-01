from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .fidelity_checkpoint import FidelityCheckpointError, load_latest_checkpoint, sha256_file
from .fidelity_physical_handoff import FidelityPhysicalHandoffError, verify_physical_handoff
from .fidelity_review_bundle import KNOWN_BAD_PACKAGE_SHA256, FidelityReviewBundleError, _snapshots_dir

PR40_REVISION = "c9dc066ef40f95a6004499a895b22a9cb3ff26c7"
PERFORMER_ID = "42"
BODY_ALIAS = "lauren-phillips-pr40-physical01"
POLICY = {
    "max_full_rebuilds": 1,
    "max_refinements_per_rebuild": 0,
    "max_wall_clock_hours": 8.0,
    "base_sith_seed": 1337,
    "reference_limit": 24,
}
STATUS_FORMAT = "bodyrig-fidelity-physical-status"
STATUS_VERSION = 1
AB_FORMAT = "bodyrig-fidelity-ab-evidence"
AB_VERSION = 1


class FidelityPhysicalStatusError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FidelityPhysicalStatusError(f"{label} not found: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FidelityPhysicalStatusError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FidelityPhysicalStatusError(f"{label} must be a JSON object")
    return value


def _status(*, phase: str, next_action: str, summary: str, paths: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {
        "format": STATUS_FORMAT,
        "version": STATUS_VERSION,
        "phase": phase,
        "next_action": next_action,
        "summary": summary,
        "paths": dict(paths or {}),
        "human_visual_authority_required": True,
        "production_activation": False,
    }


def _verified_render_set(path: Path, *, label: str, package_sha256: str) -> Path:
    try:
        root, _ = _snapshots_dir(path, label=label, expected_package_sha256=package_sha256)
    except FidelityReviewBundleError as exc:
        raise FidelityPhysicalStatusError(f"{label} render authority is invalid: {exc}") from exc
    return root


def _checkpoint_files(checkpoint_dir: Path) -> list[Path]:
    if not checkpoint_dir.is_dir():
        return []
    return sorted(path for path in checkpoint_dir.glob("checkpoint-*.json") if path.is_file())


def physical_status(
    *,
    work_root: str | os.PathLike[str],
    baseline_snapshots: str | os.PathLike[str],
    rig_setup: str | os.PathLike[str],
) -> dict[str, Any]:
    work = Path(work_root).expanduser().resolve()
    baseline = Path(baseline_snapshots).expanduser().resolve()
    rig = Path(rig_setup).expanduser().resolve()

    if not rig.is_file():
        raise FidelityPhysicalStatusError(f"rig setup report not found: {rig}")
    rig_sha = sha256_file(rig)

    if not baseline.exists():
        return _status(
            phase="historical-baseline-missing",
            next_action="render-historical-baseline",
            summary="The exact physically-bad historical baseline has not been rendered yet.",
            paths={"baseline_snapshots": str(baseline)},
        )
    baseline = _verified_render_set(
        baseline,
        label="historical baseline",
        package_sha256=KNOWN_BAD_PACKAGE_SHA256,
    )

    if not work.exists():
        return _status(
            phase="pr40-not-started",
            next_action="run-pr40-reconstruction",
            summary="Historical baseline is byte-verified; the planned one-rebuild/zero-refinement #40 run has not started.",
            paths={"baseline_snapshots": str(baseline), "work_root": str(work)},
        )
    if not work.is_dir():
        raise FidelityPhysicalStatusError(f"#40 work root is not a directory: {work}")

    checkpoint_dir = work / "checkpoints"
    if not _checkpoint_files(checkpoint_dir):
        if (work / "convergence-result.json").exists():
            raise FidelityPhysicalStatusError("#40 work root has a terminal convergence result but no checkpoint authority")
        progress = work / "progress.json"
        return _status(
            phase="pr40-awaiting-checkpoint",
            next_action="watch-pr40",
            summary="#40 work root exists but no resumable checkpoint has been published yet; do not start another reconstruction.",
            paths={"work_root": str(work), "progress": str(progress)},
        )

    try:
        checkpoint_path, checkpoint = load_latest_checkpoint(
            checkpoint_dir,
            work_root=work,
            expected_revision=PR40_REVISION,
            expected_performer_id=PERFORMER_ID,
            expected_body_alias=BODY_ALIAS,
            expected_policy=POLICY,
            expected_rig_setup_sha256=rig_sha,
        )
    except (FidelityCheckpointError, OSError, ValueError) as exc:
        raise FidelityPhysicalStatusError(f"#40 checkpoint authority is invalid: {exc}") from exc

    if checkpoint["stage"] == "post-reconstruction":
        if (work / "convergence-result.json").exists():
            raise FidelityPhysicalStatusError("#40 has a terminal convergence result while latest authority is only post-reconstruction")
        return _status(
            phase="pr40-reconstruction-checkpointed",
            next_action="continue-pr40-gate-render-evaluation",
            summary="#40 expensive reconstruction is checkpointed and byte-verified; Gate A/render/evaluation still need to reach post-candidate.",
            paths={"work_root": str(work), "checkpoint": str(checkpoint_path)},
        )
    if checkpoint["stage"] != "post-candidate":
        raise FidelityPhysicalStatusError(f"unsupported #40 checkpoint stage: {checkpoint['stage']}")

    records = checkpoint["state"]["candidate_records"]
    if len(records) != 1 or records[0]["mode"] != "full-reconstruction":
        raise FidelityPhysicalStatusError("#40 post-candidate checkpoint is not the planned single full-reconstruction candidate")
    record = records[0]
    package_path = (work / record["package_path"]).resolve()
    if not package_path.is_file():
        raise FidelityPhysicalStatusError(f"#40 candidate package is missing: {package_path}")
    render = (work / record["render_dir"]).resolve()
    snapshots = _verified_render_set(
        render / "snapshots",
        label="#40",
        package_sha256=sha256_file(package_path),
    )

    handoff_path = work / "handoff" / "pr40-physical-handoff.json"
    if not handoff_path.exists():
        return _status(
            phase="pr40-awaiting-human-geometry-review",
            next_action="review-and-seal-pr40-geometry",
            summary="#40 machine/render evidence is byte-verified. Human geometry review is now required before #41; do not infer face/appearance approval from this gate.",
            paths={"work_root": str(work), "checkpoint": str(checkpoint_path), "pr40_snapshots": str(snapshots)},
        )

    receipt = _read_json(handoff_path, label="#40 physical handoff receipt")
    try:
        verify_physical_handoff(
            receipt,
            work_root=work,
            rig_setup=rig,
            expected_revision=PR40_REVISION,
            expected_performer_id=PERFORMER_ID,
            expected_body_alias=BODY_ALIAS,
        )
    except (FidelityPhysicalHandoffError, FidelityCheckpointError, OSError, ValueError) as exc:
        raise FidelityPhysicalStatusError(f"sealed #40 physical handoff is invalid: {exc}") from exc

    pr41_root = work / "pr41-clean-ab"
    pr41_package = pr41_root / "lauren-phillips-pr41-ab.mrbody"
    pr41_snapshots = pr41_root / "comparison-render" / "snapshots"
    if not pr41_root.exists():
        return _status(
            phase="pr40-handoff-sealed",
            next_action="run-pr41-fit-only",
            summary="#40 geometry handoff is human-approved and byte-verified. The frozen #41 fit-only comparison may now run on the retained reconstruction.",
            paths={"work_root": str(work), "handoff": str(handoff_path), "pr40_snapshots": str(snapshots)},
        )
    if not pr41_package.is_file():
        raise FidelityPhysicalStatusError(f"#41 A/B output exists without its package: {pr41_package}")
    pr41_snapshots = _verified_render_set(
        pr41_snapshots,
        label="#41",
        package_sha256=sha256_file(pr41_package),
    )

    final_root = work / "pr40-pr41-review"
    if not final_root.exists():
        return _status(
            phase="pr41-render-ready",
            next_action="finalize-pr40-pr41-review",
            summary="#41 package/render are byte-verified and #40 handoff still verifies. Run the machine A/B proof and build the human review surface.",
            paths={
                "work_root": str(work),
                "handoff": str(handoff_path),
                "pr40_snapshots": str(snapshots),
                "pr41_package": str(pr41_package),
                "pr41_snapshots": str(pr41_snapshots),
            },
        )
    if not final_root.is_dir():
        raise FidelityPhysicalStatusError(f"final review output is not a directory: {final_root}")

    evidence_path = final_root / "pr40-pr41-ab-evidence.json"
    review_index = final_root / "review-bundle" / "index.html"
    evidence = _read_json(evidence_path, label="final #40/#41 A/B evidence")
    if evidence.get("format") != AB_FORMAT or evidence.get("version") != AB_VERSION:
        raise FidelityPhysicalStatusError("final #40/#41 A/B evidence format/version is invalid")
    invariants = evidence.get("invariants")
    if not isinstance(invariants, dict) or invariants.get("clean_appearance_ab") is not True:
        raise FidelityPhysicalStatusError("final #40/#41 A/B evidence does not prove a clean appearance-only comparison")
    if evidence.get("human_visual_authority_required") is not True or evidence.get("production_activation") is not False:
        raise FidelityPhysicalStatusError("final A/B evidence has invalid authority semantics")
    if not review_index.is_file():
        raise FidelityPhysicalStatusError(f"final human review page is missing: {review_index}")

    return _status(
        phase="awaiting-human-appearance-review",
        next_action="review-pr40-pr41-appearance",
        summary="Machine A/B is clean and the review page is ready. Human face/skin/hair/appearance review is the remaining authority; production activation is still false.",
        paths={
            "work_root": str(work),
            "handoff": str(handoff_path),
            "ab_evidence": str(evidence_path),
            "review_page": str(review_index),
        },
    )
