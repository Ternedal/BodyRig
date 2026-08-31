from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-fidelity-convergence-checkpoint"
VERSION = 1
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
CHECKPOINT_RE = re.compile(r"^checkpoint-(\d{6})\.json$")
STAGES = {"post-reconstruction", "post-candidate"}
SNAPSHOT_NAMES = (
    "front-full.png",
    "three-quarter-full.png",
    "side-full.png",
    "face-front.png",
    "fidelity-render-set.json",
)


class FidelityCheckpointError(ValueError):
    pass


def sha256_file(path: str | os.PathLike[str]) -> str:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FidelityCheckpointError(f"checkpoint artifact not found: {resolved}")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FidelityCheckpointError(f"{label} not found: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FidelityCheckpointError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FidelityCheckpointError(f"{label} must be a JSON object")
    return value


def _integer(value: Any, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FidelityCheckpointError(f"{field} is invalid")
    return value


def _number(value: Any, *, field: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FidelityCheckpointError(f"{field} is invalid")
    result = float(value)
    if result < minimum or result != result or result in {float("inf"), float("-inf")}:
        raise FidelityCheckpointError(f"{field} is invalid")
    return result


def _text(value: Any, *, field: str, allow_empty: bool = False, maximum: int = 4096) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value):
        raise FidelityCheckpointError(f"{field} is invalid")
    return value


def _sha(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise FidelityCheckpointError(f"{field} must be lowercase SHA-256")
    return value


def _relative(value: Any, *, field: str) -> str:
    raw = _text(value, field=field, maximum=1024).replace("\\", "/")
    path = Path(raw)
    if path.is_absolute() or raw.startswith("../") or "/../" in raw or raw in {".", ".."}:
        raise FidelityCheckpointError(f"{field} must be a safe relative path")
    return raw


def _work_key(path: str) -> str:
    return f"work-root:{path.replace('\\', '/')}"


def _private_key(path: str) -> str:
    return f"private:{str(Path(path).expanduser().resolve())}"


def _validate_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "max_full_rebuilds",
        "max_refinements_per_rebuild",
        "max_wall_clock_hours",
        "base_sith_seed",
        "reference_limit",
    }:
        raise FidelityCheckpointError("checkpoint policy fields must match v1 exactly")
    return {
        "max_full_rebuilds": _integer(value.get("max_full_rebuilds"), field="policy.max_full_rebuilds", minimum=1),
        "max_refinements_per_rebuild": _integer(
            value.get("max_refinements_per_rebuild"), field="policy.max_refinements_per_rebuild"
        ),
        "max_wall_clock_hours": _number(
            value.get("max_wall_clock_hours"), field="policy.max_wall_clock_hours", minimum=0.01
        ),
        "base_sith_seed": _integer(value.get("base_sith_seed"), field="policy.base_sith_seed"),
        "reference_limit": _integer(value.get("reference_limit"), field="policy.reference_limit", minimum=1),
    }


def _required_artifact_keys(
    *,
    body_alias: str,
    full_rebuilds_completed: int,
    current_baseline_clone_output: str,
    current_identity_workspace: str,
    candidate_records: list[dict[str, Any]],
    latest_candidate: dict[str, Any] | None,
) -> set[str]:
    required = {
        _work_key("references/reference-set.json"),
        _work_key("references/private-body-reference-rgba.png"),
    }
    baseline = current_baseline_clone_output.rstrip("/")
    required.update(
        {
            _work_key(f"{baseline}/clone/{body_alias}.mrbody"),
            _work_key(f"{baseline}/clone/bodyrig-recovery-proof.json"),
            _work_key(f"{baseline}/clone/bodyrig-visual-identity.json"),
            _work_key(f"{baseline}/clone/bodyrig-portable-identity.json"),
            _work_key(f"{baseline}/bodyrig-sith-fitter-config.json"),
        }
    )
    if full_rebuilds_completed < 1:
        raise FidelityCheckpointError("resumable checkpoint requires at least one completed full rebuild")
    required.add(_work_key(f"rebuild-{full_rebuilds_completed:02d}/physical-session.json"))
    reconstruction = Path(current_identity_workspace) / "sith-input-v1" / "reconstruction.json"
    required.add(_private_key(str(reconstruction)))

    for record in candidate_records:
        required.add(_work_key(record["package_path"]))
        required.add(_work_key(record["evaluation_path"]))
        snapshot_root = record["render_dir"].rstrip("/") + "/snapshots"
        for name in SNAPSHOT_NAMES:
            required.add(_work_key(f"{snapshot_root}/{name}"))

    if latest_candidate is not None:
        for field in ("decision_path", "evaluation_path", "adjustment_plan_path"):
            required.add(_work_key(latest_candidate[field]))
        if latest_candidate["adjustment_request_path"]:
            required.add(_work_key(latest_candidate["adjustment_request_path"]))
    return required


def validate_checkpoint(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FidelityCheckpointError("checkpoint must be a JSON object")
    required = {
        "format",
        "version",
        "sequence",
        "stage",
        "bodyrig_revision",
        "performer_id",
        "body_alias",
        "policy",
        "rig_setup_sha256",
        "active_elapsed_seconds",
        "state",
        "artifacts",
        "human_visual_authority_required",
        "production_activation",
    }
    if set(value) != required:
        raise FidelityCheckpointError("checkpoint fields must match v1 exactly")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise FidelityCheckpointError("unsupported checkpoint format/version")

    sequence = _integer(value.get("sequence"), field="sequence", minimum=1)
    stage = value.get("stage")
    if stage not in STAGES:
        raise FidelityCheckpointError("checkpoint stage is invalid")
    revision = value.get("bodyrig_revision")
    if not isinstance(revision, str) or not GIT_RE.fullmatch(revision):
        raise FidelityCheckpointError("bodyrig_revision must be lowercase Git SHA")
    performer_id = _text(value.get("performer_id"), field="performer_id", maximum=160)
    body_alias = _text(value.get("body_alias"), field="body_alias", maximum=160)
    policy = _validate_policy(value.get("policy"))
    rig_setup_sha = _sha(value.get("rig_setup_sha256"), field="rig_setup_sha256")
    active_elapsed = _number(value.get("active_elapsed_seconds"), field="active_elapsed_seconds")

    state = value.get("state")
    if not isinstance(state, dict):
        raise FidelityCheckpointError("checkpoint state must be an object")
    required_state = {
        "full_rebuilds_completed",
        "refinements_completed",
        "current_rebuild_refinements",
        "current_seed",
        "full_durations",
        "refinement_durations",
        "phase_timings",
        "latest_scores",
        "best_scores",
        "best_candidate",
        "strategy",
        "next_focus",
        "evaluation_paths",
        "candidate_records",
        "used_adjustment_hashes",
        "frozen_body_reference_sha256",
        "current_baseline_clone_output",
        "current_identity_workspace",
        "effective_name",
        "first_renderer_build",
        "latest_candidate",
    }
    if set(state) != required_state:
        raise FidelityCheckpointError("checkpoint state fields must match v1 exactly")

    full_completed = _integer(state.get("full_rebuilds_completed"), field="state.full_rebuilds_completed")
    refinements = _integer(state.get("refinements_completed"), field="state.refinements_completed")
    current_refinements = _integer(
        state.get("current_rebuild_refinements"), field="state.current_rebuild_refinements"
    )
    seed = state.get("current_seed")
    if seed is not None:
        seed = _integer(seed, field="state.current_seed")

    def durations(field: str) -> list[float]:
        raw = state.get(field)
        if not isinstance(raw, list):
            raise FidelityCheckpointError(f"state.{field} must be an array")
        return [_number(item, field=f"state.{field}[]") for item in raw]

    full_durations = durations("full_durations")
    refinement_durations = durations("refinement_durations")
    phase = state.get("phase_timings")
    phase_fields = {"full-rebuild", "resume-refinement", "gate-a", "render", "evaluate"}
    if not isinstance(phase, dict) or set(phase) != phase_fields:
        raise FidelityCheckpointError("state.phase_timings fields must match v1 exactly")
    phase_timings: dict[str, list[float]] = {}
    for key in phase_fields:
        raw = phase[key]
        if not isinstance(raw, list):
            raise FidelityCheckpointError("state.phase_timings entries must be arrays")
        phase_timings[key] = [_number(item, field=f"state.phase_timings.{key}[]") for item in raw]

    evaluation_paths = state.get("evaluation_paths")
    if not isinstance(evaluation_paths, list):
        raise FidelityCheckpointError("state.evaluation_paths must be an array")
    validated_evaluations = [_relative(item, field="state.evaluation_paths[]") for item in evaluation_paths]
    if len(set(validated_evaluations)) != len(validated_evaluations):
        raise FidelityCheckpointError("state.evaluation_paths contains duplicates")

    records = state.get("candidate_records")
    if not isinstance(records, list):
        raise FidelityCheckpointError("state.candidate_records must be an array")
    validated_records: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != {
            "relative_name",
            "mode",
            "package_path",
            "render_dir",
            "evaluation_path",
            "acceptance_dir",
        }:
            raise FidelityCheckpointError(f"state.candidate_records[{index}] fields are invalid")
        validated_records.append(
            {
                "relative_name": _relative(record["relative_name"], field="candidate.relative_name"),
                "mode": _text(record["mode"], field="candidate.mode", maximum=80),
                "package_path": _relative(record["package_path"], field="candidate.package_path"),
                "render_dir": _relative(record["render_dir"], field="candidate.render_dir"),
                "evaluation_path": _relative(record["evaluation_path"], field="candidate.evaluation_path"),
                "acceptance_dir": (
                    _relative(record["acceptance_dir"], field="candidate.acceptance_dir")
                    if record["acceptance_dir"]
                    else ""
                ),
            }
        )
    relative_names = [item["relative_name"] for item in validated_records]
    if len(set(relative_names)) != len(relative_names):
        raise FidelityCheckpointError("candidate relative_name values must be unique")
    record_evaluations = [item["evaluation_path"] for item in validated_records]
    if record_evaluations != validated_evaluations:
        raise FidelityCheckpointError("evaluation_paths must exactly match candidate record order")

    used = state.get("used_adjustment_hashes")
    if not isinstance(used, list):
        raise FidelityCheckpointError("state.used_adjustment_hashes must be an array")
    validated_used = [_sha(item, field="state.used_adjustment_hashes[]") for item in used]
    if len(set(validated_used)) != len(validated_used):
        raise FidelityCheckpointError("state.used_adjustment_hashes contains duplicates")

    frozen_sha = _sha(state.get("frozen_body_reference_sha256"), field="state.frozen_body_reference_sha256")
    current_baseline = _relative(
        state.get("current_baseline_clone_output"), field="state.current_baseline_clone_output"
    )
    current_workspace = _text(
        state.get("current_identity_workspace"), field="state.current_identity_workspace", maximum=4096
    )
    effective_name = _text(state.get("effective_name"), field="state.effective_name", maximum=160)
    first_renderer_build = state.get("first_renderer_build")
    if not isinstance(first_renderer_build, bool):
        raise FidelityCheckpointError("state.first_renderer_build must be boolean")

    latest_candidate = state.get("latest_candidate")
    validated_latest: dict[str, Any] | None = None
    if latest_candidate is not None:
        if not isinstance(latest_candidate, dict) or set(latest_candidate) != {
            "decision_path",
            "evaluation_path",
            "adjustment_plan_path",
            "adjustment_request_path",
            "adjustment_sha256",
        }:
            raise FidelityCheckpointError("state.latest_candidate fields are invalid")
        validated_latest = {
            "decision_path": _relative(latest_candidate["decision_path"], field="latest_candidate.decision_path"),
            "evaluation_path": _relative(latest_candidate["evaluation_path"], field="latest_candidate.evaluation_path"),
            "adjustment_plan_path": _relative(
                latest_candidate["adjustment_plan_path"], field="latest_candidate.adjustment_plan_path"
            ),
            "adjustment_request_path": (
                _relative(latest_candidate["adjustment_request_path"], field="latest_candidate.adjustment_request_path")
                if latest_candidate["adjustment_request_path"]
                else ""
            ),
            "adjustment_sha256": (
                _sha(latest_candidate["adjustment_sha256"], field="latest_candidate.adjustment_sha256")
                if latest_candidate["adjustment_sha256"]
                else ""
            ),
        }

    if stage == "post-candidate":
        if validated_latest is None or not validated_records:
            raise FidelityCheckpointError("post-candidate checkpoint requires a latest candidate")
        if validated_latest["evaluation_path"] != validated_evaluations[-1]:
            raise FidelityCheckpointError("latest candidate evaluation must be the final evaluation path")
    elif validated_latest is not None:
        raise FidelityCheckpointError("post-reconstruction checkpoint may not contain latest_candidate")

    if full_completed > policy["max_full_rebuilds"]:
        raise FidelityCheckpointError("checkpoint full rebuild count exceeds policy")
    if current_refinements > policy["max_refinements_per_rebuild"]:
        raise FidelityCheckpointError("checkpoint current refinement count exceeds policy")
    if refinements < current_refinements:
        raise FidelityCheckpointError("checkpoint total refinements is lower than current rebuild refinements")

    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise FidelityCheckpointError("checkpoint artifacts must be a non-empty array")
    validated_artifacts: list[dict[str, str]] = []
    artifact_keys: set[str] = set()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256", "scope"}:
            raise FidelityCheckpointError(f"artifacts[{index}] fields are invalid")
        scope = artifact.get("scope")
        if scope not in {"work-root", "private"}:
            raise FidelityCheckpointError(f"artifacts[{index}].scope is invalid")
        raw_path = _text(artifact.get("path"), field=f"artifacts[{index}].path", maximum=4096)
        if scope == "work-root":
            raw_path = _relative(raw_path, field=f"artifacts[{index}].path")
            key = _work_key(raw_path)
        else:
            raw_path = str(Path(raw_path).expanduser().resolve())
            key = _private_key(raw_path)
        if key in artifact_keys:
            raise FidelityCheckpointError("checkpoint contains duplicate artifact paths")
        artifact_keys.add(key)
        validated_artifacts.append(
            {
                "path": raw_path,
                "sha256": _sha(artifact.get("sha256"), field=f"artifacts[{index}].sha256"),
                "scope": scope,
            }
        )

    required_artifacts = _required_artifact_keys(
        body_alias=body_alias,
        full_rebuilds_completed=full_completed,
        current_baseline_clone_output=current_baseline,
        current_identity_workspace=current_workspace,
        candidate_records=validated_records,
        latest_candidate=validated_latest,
    )
    missing = sorted(required_artifacts - artifact_keys)
    if missing:
        raise FidelityCheckpointError(f"checkpoint state references unhashed artifacts: {missing[0]}")

    if value.get("human_visual_authority_required") is not True:
        raise FidelityCheckpointError("checkpoint must require human visual authority")
    if value.get("production_activation") is not False:
        raise FidelityCheckpointError("checkpoint may not grant production activation")

    return {
        "format": FORMAT,
        "version": VERSION,
        "sequence": sequence,
        "stage": stage,
        "bodyrig_revision": revision,
        "performer_id": performer_id,
        "body_alias": body_alias,
        "policy": policy,
        "rig_setup_sha256": rig_setup_sha,
        "active_elapsed_seconds": active_elapsed,
        "state": {
            "full_rebuilds_completed": full_completed,
            "refinements_completed": refinements,
            "current_rebuild_refinements": current_refinements,
            "current_seed": seed,
            "full_durations": full_durations,
            "refinement_durations": refinement_durations,
            "phase_timings": phase_timings,
            "latest_scores": state.get("latest_scores"),
            "best_scores": state.get("best_scores"),
            "best_candidate": state.get("best_candidate"),
            "strategy": state.get("strategy"),
            "next_focus": state.get("next_focus"),
            "evaluation_paths": validated_evaluations,
            "candidate_records": validated_records,
            "used_adjustment_hashes": validated_used,
            "frozen_body_reference_sha256": frozen_sha,
            "current_baseline_clone_output": current_baseline,
            "current_identity_workspace": current_workspace,
            "effective_name": effective_name,
            "first_renderer_build": first_renderer_build,
            "latest_candidate": validated_latest,
        },
        "artifacts": validated_artifacts,
        "human_visual_authority_required": True,
        "production_activation": False,
    }


def verify_checkpoint_artifacts(checkpoint: Mapping[str, Any], *, work_root: str | os.PathLike[str]) -> None:
    root = Path(work_root).expanduser().resolve()
    if not root.is_dir():
        raise FidelityCheckpointError(f"work root not found: {root}")
    for artifact in checkpoint["artifacts"]:
        if artifact["scope"] == "work-root":
            path = (root / artifact["path"]).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise FidelityCheckpointError("checkpoint work-root artifact escapes work root") from exc
        else:
            path = Path(artifact["path"]).expanduser().resolve()
        actual = sha256_file(path)
        if actual != artifact["sha256"]:
            raise FidelityCheckpointError(f"checkpoint artifact hash mismatch: {artifact['path']}")


def load_latest_checkpoint(
    checkpoint_dir: str | os.PathLike[str],
    *,
    work_root: str | os.PathLike[str],
    expected_revision: str,
    expected_performer_id: str,
    expected_body_alias: str,
    expected_policy: Mapping[str, Any],
    expected_rig_setup_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    directory = Path(checkpoint_dir).expanduser().resolve()
    if not directory.is_dir():
        raise FidelityCheckpointError(f"checkpoint directory not found: {directory}")
    candidates: list[tuple[int, Path]] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = CHECKPOINT_RE.fullmatch(path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    if not candidates:
        raise FidelityCheckpointError("no fidelity convergence checkpoints found")
    candidates.sort(key=lambda item: item[0])
    sequences = [item[0] for item in candidates]
    expected_sequences = list(range(1, sequences[-1] + 1))
    if sequences != expected_sequences:
        raise FidelityCheckpointError("checkpoint sequence contains a gap or duplicate")
    for sequence, path in candidates:
        raw = _read_json(path, label="fidelity convergence checkpoint")
        content_sequence = raw.get("sequence")
        if content_sequence != sequence:
            raise FidelityCheckpointError("checkpoint filename sequence does not match content")

    latest_path = candidates[-1][1]
    checkpoint = validate_checkpoint(_read_json(latest_path, label="fidelity convergence checkpoint"))
    if checkpoint["bodyrig_revision"] != expected_revision:
        raise FidelityCheckpointError("checkpoint belongs to a different BodyRig revision")
    if checkpoint["performer_id"] != expected_performer_id:
        raise FidelityCheckpointError("checkpoint performer differs from requested performer")
    if checkpoint["body_alias"] != expected_body_alias:
        raise FidelityCheckpointError("checkpoint body alias differs from requested body")
    if checkpoint["policy"] != _validate_policy(dict(expected_policy)):
        raise FidelityCheckpointError("checkpoint policy differs from requested convergence policy")
    if checkpoint["rig_setup_sha256"] != _sha(
        expected_rig_setup_sha256, field="expected_rig_setup_sha256"
    ):
        raise FidelityCheckpointError("checkpoint rig setup bytes differ from current rig setup")
    verify_checkpoint_artifacts(checkpoint, work_root=work_root)
    return latest_path, checkpoint


def _strict_policy(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FidelityCheckpointError("--policy-json is invalid JSON") from exc
    return _validate_policy(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and load fail-closed BodyRig fidelity convergence checkpoints.")
    sub = parser.add_subparsers(dest="command", required=True)
    latest = sub.add_parser("latest")
    latest.add_argument("--checkpoint-dir", required=True)
    latest.add_argument("--work-root", required=True)
    latest.add_argument("--revision", required=True)
    latest.add_argument("--performer-id", required=True)
    latest.add_argument("--body-alias", required=True)
    latest.add_argument("--policy-json", required=True)
    latest.add_argument("--rig-setup-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        policy = _strict_policy(args.policy_json)
        path, checkpoint = load_latest_checkpoint(
            args.checkpoint_dir,
            work_root=args.work_root,
            expected_revision=args.revision,
            expected_performer_id=args.performer_id,
            expected_body_alias=args.body_alias,
            expected_policy=policy,
            expected_rig_setup_sha256=args.rig_setup_sha256,
        )
        value = {"checkpoint_path": str(path), "checkpoint": checkpoint}
    except (FidelityCheckpointError, OSError, ValueError) as exc:
        print(f"BodyRig fidelity checkpoint: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
