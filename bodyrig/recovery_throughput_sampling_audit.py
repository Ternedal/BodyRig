from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .bridges.hmr2_config import RECOVERY_TEMPORAL_SAMPLING_POLICY, RECOVERY_TEMPORAL_SAMPLING_REVISION
from .identity import bind_visual_identity_to_proof
from .person_body_review import read_review_by_package, validate_fidelity_output
from .person_profiles import load_profile
from .person_source_alignment import binding_path, file_sha256, read_binding
from .proof import load_recovery_proof
from .storage import person_library

FORMAT = "bodyrig-recovery-throughput-sampling-audit"
VERSION = 1
BASELINE_BODYRIG_REVISION = "76c64a9546238663dedf750a1da4a230cc1e7fa4"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_RE = re.compile(r"^\[([^\]]+)\]\s+RUN\b")


class RecoverySamplingAuditError(ValueError):
    pass


@dataclass(frozen=True)
class RunEvidence:
    job: dict[str, Any]
    binding: dict[str, Any]
    selection: dict[str, Any]
    segments: dict[str, Any]
    recovery: dict[str, Any]
    identity: dict[str, Any]
    acceptance: dict[str, Any]
    fidelity: dict[str, Any]
    review: dict[str, Any]
    package_sha256: str
    total_seconds: float | None
    clone_pipeline_seconds: float | None


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RecoverySamplingAuditError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoverySamplingAuditError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RecoverySamplingAuditError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA_RE.fullmatch(text) is None:
        raise RecoverySamplingAuditError(f"{label} is not a canonical SHA-256")
    return text


def _bodyrig_revision(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if _GIT_SHA_RE.fullmatch(text) is None:
        raise RecoverySamplingAuditError(f"{label} is not an exact 40-character Git revision")
    return text


def _job_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    return path / "job.json" if path.is_dir() else path


def _load_job(value: str | Path) -> dict[str, Any]:
    job = _read_json(_job_path(value), "UI body job")
    if job.get("format") != "bodyrig-ui-job" or job.get("version") != 1:
        raise RecoverySamplingAuditError("UI job format/version mismatch")
    if job.get("kind") != "body-build" or job.get("status") != "succeeded":
        raise RecoverySamplingAuditError("A/B audit requires a succeeded body-build job")
    for field in (
        "job_id",
        "person_id",
        "bodyrig_revision",
        "body_revision",
        "canonical_body_id",
        "clone_output",
        "acceptance_dir",
        "fidelity_dir",
        "source_binding_sha256",
        "body_review_sha256",
        "log_path",
    ):
        if not str(job.get(field) or "").strip():
            raise RecoverySamplingAuditError(f"succeeded body-build job is missing {field}")
    job["bodyrig_revision"] = _bodyrig_revision(job["bodyrig_revision"], "job.bodyrig_revision")
    _sha(job["source_binding_sha256"], "job.source_binding_sha256")
    _sha(job["body_review_sha256"], "job.body_review_sha256")
    return job


def _load_binding(root: Path, job: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    person_id = str(job["person_id"])
    revision = str(job["body_revision"])
    try:
        profile = load_profile(root, person_id)
        receipt = read_binding(root, profile, kind="body", revision_id=revision)
    except ValueError as exc:
        raise RecoverySamplingAuditError(f"body source binding is not authoritative: {exc}") from exc
    path = binding_path(root, person_id, "body", revision)
    if file_sha256(path) != _sha(job["source_binding_sha256"], "job.source_binding_sha256"):
        raise RecoverySamplingAuditError("body source binding SHA no longer matches the succeeded job")
    component = receipt.get("component")
    if not isinstance(component, Mapping):
        raise RecoverySamplingAuditError("body source binding component is invalid")
    package_sha = _sha(component.get("artifact_sha256"), "binding.component.artifact_sha256")
    evidence = receipt.get("evidence")
    if not isinstance(evidence, Mapping):
        raise RecoverySamplingAuditError("body source binding evidence is invalid")
    source_files = evidence.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise RecoverySamplingAuditError("body source binding has no exact source-file SHA evidence")
    for item in source_files:
        if not isinstance(item, Mapping) or not str(item.get("scene_id") or "") or not str(item.get("name") or ""):
            raise RecoverySamplingAuditError("body source binding source-file identity is invalid")
        _sha(item.get("sha256"), "binding.evidence.source_files.sha256")
    return receipt, package_sha


def _load_selection(clone_root: Path) -> dict[str, Any]:
    value = _read_json(clone_root / "bodyrig-observation-selection.json", "observation selection")
    if value.get("format") != "bodyrig-observation-selection" or value.get("version") != 1:
        raise RecoverySamplingAuditError("observation selection format/version mismatch")
    if not isinstance(value.get("selected"), list) or not value["selected"]:
        raise RecoverySamplingAuditError("observation selection contains no selected observations")
    return value


def _load_segments(clone_root: Path) -> dict[str, Any]:
    value = _read_json(clone_root / "bodyrig-observation-segments.json", "observation segment manifest")
    if value.get("format") != "bodyrig-observation-segments" or value.get("version") != 1:
        raise RecoverySamplingAuditError("observation segment manifest format/version mismatch")
    rows = value.get("segments")
    if not isinstance(rows, list) or not rows:
        raise RecoverySamplingAuditError("observation segment manifest contains no segments")
    for item in rows:
        if not isinstance(item, Mapping):
            raise RecoverySamplingAuditError("observation segment entry is invalid")
        _sha(item.get("sha256"), "observation segment SHA-256")
    return value


def _load_acceptance(job: Mapping[str, Any], recovery: Mapping[str, Any], package_sha: str) -> dict[str, Any]:
    value = _read_json(Path(str(job["acceptance_dir"])).resolve() / "bodyrig-acceptance.json", "Gate A acceptance")
    if value.get("format") != "bodyrig-rig-acceptance" or value.get("version") != 1:
        raise RecoverySamplingAuditError("Gate A acceptance format/version mismatch")
    if value.get("automated_pass") is not True:
        raise RecoverySamplingAuditError("Gate A automated_pass is not true")
    checks = value.get("checks")
    if not isinstance(checks, Mapping) or not checks or any(item is not True for item in checks.values()):
        raise RecoverySamplingAuditError("Gate A checks are not all true")
    if value.get("physical_renderer_acceptance") != "pending" or value.get("production_activation") is not False:
        raise RecoverySamplingAuditError("Gate A authority boundary is invalid")
    package = value.get("package")
    if not isinstance(package, Mapping):
        raise RecoverySamplingAuditError("Gate A package identity is invalid")
    if _sha(package.get("package_sha256"), "acceptance.package.package_sha256") != package_sha:
        raise RecoverySamplingAuditError("Gate A package SHA does not match the source-bound body revision")
    if str(package.get("body_id") or "") != str(job.get("canonical_body_id") or ""):
        raise RecoverySamplingAuditError("Gate A canonical body id does not match the succeeded job")
    accepted_recovery = value.get("recovery")
    if not isinstance(accepted_recovery, Mapping):
        raise RecoverySamplingAuditError("Gate A recovery identity is invalid")
    for field in ("adapter", "revision", "track_id", "observed_frames"):
        if accepted_recovery.get(field) != recovery.get(field):
            raise RecoverySamplingAuditError(f"Gate A recovery {field} does not match recovery proof")
    return value


def _load_identity(clone_root: Path, recovery: Mapping[str, Any]) -> dict[str, Any]:
    value = _read_json(clone_root / "clone" / "bodyrig-visual-identity.json", "visual identity profile")
    try:
        return bind_visual_identity_to_proof(value, dict(recovery))
    except ValueError as exc:
        raise RecoverySamplingAuditError(f"visual identity is not bound to recovery proof: {exc}") from exc


def _load_fidelity_and_review(root: Path, job: Mapping[str, Any], package_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    body_id = str(job["canonical_body_id"])
    try:
        fidelity = validate_fidelity_output(str(job["fidelity_dir"]), body_id=body_id, package_sha256=package_sha)
        review = read_review_by_package(root, person_id=str(job["person_id"]), package_sha256=package_sha)
    except ValueError as exc:
        raise RecoverySamplingAuditError(f"fidelity/review evidence is not authoritative: {exc}") from exc
    receipt_path = Path(str(review["root"])) / "review.json"
    if file_sha256(receipt_path) != _sha(job["body_review_sha256"], "job.body_review_sha256"):
        raise RecoverySamplingAuditError("persisted body review SHA no longer matches the succeeded job")
    if review.get("body_id") != body_id:
        raise RecoverySamplingAuditError("persisted body review canonical body id mismatch")
    return fidelity, review


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _total_seconds(job: Mapping[str, Any]) -> float | None:
    start = _parse_time(job.get("started_utc"))
    end = _parse_time(job.get("completed_utc"))
    if start is None or end is None or end < start:
        return None
    return (end - start).total_seconds()


def _clone_pipeline_seconds(log_path: Any) -> float | None:
    path = Path(str(log_path or "")).expanduser()
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    starts: list[datetime] = []
    for line in lines:
        match = _RUN_RE.match(line.strip())
        if match is None:
            continue
        stamp = _parse_time(match.group(1))
        if stamp is not None:
            starts.append(stamp)
        if len(starts) == 2:
            break
    if len(starts) != 2 or starts[1] < starts[0]:
        return None
    return (starts[1] - starts[0]).total_seconds()


def collect_run(job_ref: str | Path, *, person_root: str | Path | None = None) -> RunEvidence:
    job = _load_job(job_ref)
    root = Path(person_root).expanduser().resolve() if person_root is not None else person_library().resolve()
    binding, package_sha = _load_binding(root, job)
    clone_root = Path(str(job["clone_output"])).expanduser().resolve()
    selection = _load_selection(clone_root)
    segments = _load_segments(clone_root)
    recovery = load_recovery_proof(clone_root / "clone" / "bodyrig-recovery-proof.json")
    identity = _load_identity(clone_root, recovery)
    acceptance = _load_acceptance(job, recovery, package_sha)
    fidelity, review = _load_fidelity_and_review(root, job, package_sha)
    return RunEvidence(
        job=job,
        binding=binding,
        selection=selection,
        segments=segments,
        recovery=recovery,
        identity=identity,
        acceptance=acceptance,
        fidelity=fidelity,
        review=review,
        package_sha256=package_sha,
        total_seconds=_total_seconds(job),
        clone_pipeline_seconds=_clone_pipeline_seconds(job.get("log_path")),
    )


def expected_candidate_revision(baseline_revision: str) -> str:
    baseline = str(baseline_revision or "").strip()
    if not baseline:
        raise RecoverySamplingAuditError("baseline recovery revision is missing")
    suffix = f";s:{RECOVERY_TEMPORAL_SAMPLING_REVISION}"
    if baseline.endswith(suffix):
        raise RecoverySamplingAuditError("baseline already uses the candidate recovery sampling revision")
    candidate = baseline + suffix
    if len(candidate) > 160:
        raise RecoverySamplingAuditError("candidate recovery revision would violate the recovery-v1 length contract")
    return candidate


def _segment_identity(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = value.get("segments")
    if not isinstance(rows, list):
        return []
    return [
        {
            "source_id": item.get("source_id"),
            "scene_id": item.get("scene_id"),
            "start_seconds": item.get("start_seconds"),
            "duration_seconds": item.get("duration_seconds"),
            "sha256": item.get("sha256"),
        }
        for item in rows
        if isinstance(item, Mapping)
    ]


def _numeric_deltas(baseline: Any, candidate: Any, prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(baseline, Mapping) and isinstance(candidate, Mapping):
        for key in sorted(set(baseline).intersection(candidate)):
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_numeric_deltas(baseline[key], candidate[key], child))
        return result
    if isinstance(baseline, bool) or isinstance(candidate, bool):
        return result
    if isinstance(baseline, (int, float)) and isinstance(candidate, (int, float)):
        a = float(baseline)
        b = float(candidate)
        if math.isfinite(a) and math.isfinite(b):
            result[prefix] = b - a
    return result


def _ratio(candidate: float | int | None, baseline: float | int | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    a = float(candidate)
    b = float(baseline)
    if not math.isfinite(a) or not math.isfinite(b) or b <= 0:
        return None
    return a / b


def compare_runs(
    baseline: RunEvidence,
    candidate: RunEvidence,
    *,
    expected_candidate_bodyrig_revision: str | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []

    baseline_bodyrig_revision = _bodyrig_revision(
        baseline.job.get("bodyrig_revision"), "baseline job.bodyrig_revision"
    )
    candidate_bodyrig_revision = _bodyrig_revision(
        candidate.job.get("bodyrig_revision"), "candidate job.bodyrig_revision"
    )
    expected_candidate = (
        _bodyrig_revision(expected_candidate_bodyrig_revision, "expected candidate BodyRig revision")
        if expected_candidate_bodyrig_revision is not None
        else None
    )
    if baseline_bodyrig_revision != BASELINE_BODYRIG_REVISION:
        blockers.append("baseline BodyRig revision is not the exact uncapped Person Studio authority")
    if expected_candidate is not None and candidate_bodyrig_revision != expected_candidate:
        blockers.append("candidate BodyRig revision does not match the exact comparator checkout authority")

    if baseline.job.get("person_id") != candidate.job.get("person_id"):
        blockers.append("baseline and candidate person_id differ")

    baseline_source = baseline.binding.get("source")
    candidate_source = candidate.binding.get("source")
    baseline_files = baseline.binding.get("evidence", {}).get("source_files")
    candidate_files = candidate.binding.get("evidence", {}).get("source_files")
    if baseline_source != candidate_source:
        blockers.append("baseline and candidate Stash performer authority differ")
    if baseline_files != candidate_files:
        blockers.append("baseline and candidate exact source-file SHA evidence differ")

    if baseline.selection.get("adapter") != candidate.selection.get("adapter"):
        blockers.append("observation selection adapter differs")
    if baseline.selection.get("revision") != candidate.selection.get("revision"):
        blockers.append("observation selection revision differs")
    if baseline.selection.get("selected") != candidate.selection.get("selected"):
        blockers.append("observation selection windows/quality evidence differ")

    baseline_segments = _segment_identity(baseline.segments)
    candidate_segments = _segment_identity(candidate.segments)
    if baseline_segments != candidate_segments:
        blockers.append("native observation segment identity/bytes differ")

    baseline_revision = str(baseline.recovery.get("revision") or "")
    candidate_revision = str(candidate.recovery.get("revision") or "")
    try:
        expected_revision = expected_candidate_revision(baseline_revision)
    except RecoverySamplingAuditError as exc:
        expected_revision = ""
        blockers.append(str(exc))
    if expected_revision and candidate_revision != expected_revision:
        blockers.append("candidate recovery revision is not the exact versioned sampling derivative of baseline")
    if baseline.recovery.get("adapter") != candidate.recovery.get("adapter"):
        blockers.append("recovery adapter differs")
    if baseline.recovery.get("track_id") != candidate.recovery.get("track_id"):
        blockers.append("recovery track_id differs")

    baseline_frames = int(baseline.recovery.get("observed_frames") or 0)
    candidate_frames = int(candidate.recovery.get("observed_frames") or 0)
    frame_reduction = baseline_frames > 0 and 0 < candidate_frames < baseline_frames
    if not frame_reduction:
        blockers.append("candidate did not reduce recovery observed_frames")

    identity_deltas = {
        **_numeric_deltas(baseline.identity.get("capture", {}), candidate.identity.get("capture", {}), "capture"),
        **_numeric_deltas(baseline.identity.get("coverage", {}), candidate.identity.get("coverage", {}), "coverage"),
        **_numeric_deltas(baseline.identity.get("quality", {}), candidate.identity.get("quality", {}), "quality"),
    }
    bodyprint_deltas = _numeric_deltas(
        baseline.recovery.get("bodyprint", {}), candidate.recovery.get("bodyprint", {}), "bodyprint"
    )

    machine_pass = not blockers
    return {
        "format": FORMAT,
        "version": VERSION,
        "baseline_job_id": baseline.job.get("job_id"),
        "candidate_job_id": candidate.job.get("job_id"),
        "person_id": baseline.job.get("person_id"),
        "baseline_bodyrig_revision": baseline_bodyrig_revision,
        "expected_baseline_bodyrig_revision": BASELINE_BODYRIG_REVISION,
        "candidate_bodyrig_revision": candidate_bodyrig_revision,
        "expected_candidate_bodyrig_revision": expected_candidate,
        "software_authority_bound": baseline_bodyrig_revision == BASELINE_BODYRIG_REVISION
        and (expected_candidate is None or candidate_bodyrig_revision == expected_candidate),
        "sampling_policy": RECOVERY_TEMPORAL_SAMPLING_POLICY,
        "sampling_revision": RECOVERY_TEMPORAL_SAMPLING_REVISION,
        "baseline_recovery_revision": baseline_revision,
        "candidate_recovery_revision": candidate_revision,
        "expected_candidate_recovery_revision": expected_revision,
        "source_authority_equal": baseline_source == candidate_source and baseline_files == candidate_files,
        "observation_selection_equal": baseline.selection.get("selected") == candidate.selection.get("selected")
        and baseline.selection.get("adapter") == candidate.selection.get("adapter")
        and baseline.selection.get("revision") == candidate.selection.get("revision"),
        "native_observation_segment_bytes_equal": baseline_segments == candidate_segments,
        "recovery_track_equal": baseline.recovery.get("track_id") == candidate.recovery.get("track_id"),
        "frames": {
            "baseline": baseline_frames,
            "candidate": candidate_frames,
            "ratio": _ratio(candidate_frames, baseline_frames),
            "reduction_observed": frame_reduction,
        },
        "timing": {
            "baseline_total_seconds": baseline.total_seconds,
            "candidate_total_seconds": candidate.total_seconds,
            "total_ratio": _ratio(candidate.total_seconds, baseline.total_seconds),
            "baseline_clone_pipeline_seconds": baseline.clone_pipeline_seconds,
            "candidate_clone_pipeline_seconds": candidate.clone_pipeline_seconds,
            "clone_pipeline_ratio": _ratio(candidate.clone_pipeline_seconds, baseline.clone_pipeline_seconds),
            "clone_pipeline_semantics": "first-physical-command-to-Gate-A-command wall-clock",
        },
        "identity_metric_deltas_candidate_minus_baseline": identity_deltas,
        "bodyprint_numeric_deltas_candidate_minus_baseline": bodyprint_deltas,
        "baseline_package_sha256": baseline.package_sha256,
        "candidate_package_sha256": candidate.package_sha256,
        "machine_evidence_pass": machine_pass,
        "blockers": blockers,
        "human_visual_review_required": True,
        "promotion_authority": False,
        "production_activation": False,
        "decision": "eligible-for-human-ab-review" if machine_pass else "blocked",
    }


def audit(
    baseline_job: str | Path,
    candidate_job: str | Path,
    *,
    expected_candidate_bodyrig_revision: str,
    person_root: str | Path | None = None,
) -> dict[str, Any]:
    return compare_runs(
        collect_run(baseline_job, person_root=person_root),
        collect_run(candidate_job, person_root=person_root),
        expected_candidate_bodyrig_revision=expected_candidate_bodyrig_revision,
    )


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise RecoverySamplingAuditError(f"refusing to overwrite throughput audit: {path}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only A/B audit for the versioned BodyRig PHALP sampling candidate. Never grants promotion authority."
    )
    parser.add_argument("baseline_job", help="uncapped succeeded body-build job directory or job.json")
    parser.add_argument("candidate_job", help="sampling-candidate succeeded body-build job directory or job.json")
    parser.add_argument(
        "--candidate-bodyrig-revision",
        required=True,
        help="exact 40-character BodyRig candidate checkout revision used as comparator authority",
    )
    parser.add_argument("--person-root", default="", help="optional Person Library root override")
    parser.add_argument("--out", default="", help="optional create-only JSON report")
    args = parser.parse_args(argv)
    try:
        result = audit(
            args.baseline_job,
            args.candidate_job,
            expected_candidate_bodyrig_revision=args.candidate_bodyrig_revision,
            person_root=args.person_root or None,
        )
        if args.out:
            _write_create_only(Path(args.out), result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        return 0 if result["machine_evidence_pass"] else 1
    except (OSError, RecoverySamplingAuditError, ValueError) as exc:
        print(f"BodyRig recovery sampling A/B audit: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
