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

from .identity import bind_visual_identity_to_proof
from .person_body_review import read_review_by_package, validate_fidelity_output
from .person_source_alignment import file_sha256
from .proof import load_recovery_proof
from .storage import person_library

FORMAT = "bodyrig-recovery-throughput-audit"
VERSION = 1
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_RE = re.compile(r"^\[([^\]]+)\]\s+RUN\s*$")


class RecoveryThroughputAuditError(ValueError):
    pass


@dataclass(frozen=True)
class RunEvidence:
    job: dict[str, Any]
    source_binding: dict[str, Any]
    selection: dict[str, Any]
    segments: dict[str, Any]
    recovery: dict[str, Any]
    identity: dict[str, Any]
    acceptance: dict[str, Any]
    fidelity: dict[str, Any]
    review: dict[str, Any]
    total_seconds: float | None
    clone_pipeline_seconds: float | None


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RecoveryThroughputAuditError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryThroughputAuditError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RecoveryThroughputAuditError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA_RE.fullmatch(text) is None:
        raise RecoveryThroughputAuditError(f"{label} is not a canonical SHA-256")
    return text


def _job_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path.is_dir():
        path = path / "job.json"
    return path


def _load_job(value: str | Path) -> dict[str, Any]:
    job = _read_json(_job_path(value), "UI body job")
    if job.get("format") != "bodyrig-ui-job" or job.get("version") != 1:
        raise RecoveryThroughputAuditError("UI job format/version mismatch")
    if job.get("kind") != "body-build" or job.get("status") != "succeeded":
        raise RecoveryThroughputAuditError("A/B audit requires a succeeded body-build job")
    for field in (
        "person_id",
        "performer_id",
        "body_revision",
        "package_sha256",
        "clone_output",
        "acceptance_dir",
        "fidelity_dir",
        "source_binding_sha256",
        "body_review_sha256",
    ):
        if not str(job.get(field) or "").strip():
            raise RecoveryThroughputAuditError(f"succeeded body-build job is missing {field}")
    _sha(job["package_sha256"], "job.package_sha256")
    _sha(job["source_binding_sha256"], "job.source_binding_sha256")
    _sha(job["body_review_sha256"], "job.body_review_sha256")
    return job


def _binding_path(root: Path, job: Mapping[str, Any]) -> Path:
    return root / ".source-bindings" / str(job["person_id"]) / f"{job['body_revision']}.json"


def _load_binding(root: Path, job: Mapping[str, Any]) -> dict[str, Any]:
    path = _binding_path(root, job)
    receipt = _read_json(path, "body source binding")
    if file_sha256(path) != _sha(job["source_binding_sha256"], "job.source_binding_sha256"):
        raise RecoveryThroughputAuditError("body source binding SHA no longer matches the succeeded job")
    if receipt.get("format") != "bodyrig-person-source-binding" or receipt.get("version") != 1:
        raise RecoveryThroughputAuditError("body source binding format/version mismatch")
    if receipt.get("person_id") != job.get("person_id"):
        raise RecoveryThroughputAuditError("body source binding person mismatch")
    source = receipt.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        raise RecoveryThroughputAuditError("body source binding has no authoritative Stash performer")
    if str(source.get("performer_id") or "") != str(job.get("performer_id") or ""):
        raise RecoveryThroughputAuditError("body source binding performer mismatch")
    component = receipt.get("component")
    if not isinstance(component, Mapping):
        raise RecoveryThroughputAuditError("body source binding component is invalid")
    if component.get("kind") != "body" or component.get("revision_id") != job.get("body_revision"):
        raise RecoveryThroughputAuditError("body source binding component revision mismatch")
    if _sha(component.get("artifact_sha256"), "binding.component.artifact_sha256") != _sha(
        job.get("package_sha256"), "job.package_sha256"
    ):
        raise RecoveryThroughputAuditError("body source binding package SHA mismatch")
    evidence = receipt.get("evidence")
    if not isinstance(evidence, Mapping):
        raise RecoveryThroughputAuditError("body source binding evidence is invalid")
    _sha(evidence.get("sha256"), "binding.evidence.sha256")
    source_files = evidence.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise RecoveryThroughputAuditError("body source binding has no source-file evidence")
    for item in source_files:
        if not isinstance(item, Mapping) or not str(item.get("scene_id") or "") or not str(item.get("name") or ""):
            raise RecoveryThroughputAuditError("body source binding source-file identity is invalid")
        _sha(item.get("sha256"), "binding.evidence.source_files.sha256")
    return receipt


def _load_selection(clone_root: Path) -> dict[str, Any]:
    value = _read_json(clone_root / "bodyrig-observation-selection.json", "observation selection")
    if value.get("format") != "bodyrig-observation-selection" or value.get("version") != 1:
        raise RecoveryThroughputAuditError("observation selection format/version mismatch")
    selected = value.get("selected")
    if not isinstance(selected, list) or not selected:
        raise RecoveryThroughputAuditError("observation selection contains no selected observations")
    return value


def _load_segments(clone_root: Path) -> dict[str, Any]:
    value = _read_json(clone_root / "bodyrig-observation-segments.json", "observation segment manifest")
    if value.get("format") != "bodyrig-observation-segments" or value.get("version") != 1:
        raise RecoveryThroughputAuditError("observation segment manifest format/version mismatch")
    rows = value.get("segments")
    if not isinstance(rows, list) or not rows:
        raise RecoveryThroughputAuditError("observation segment manifest contains no segments")
    for item in rows:
        if not isinstance(item, Mapping):
            raise RecoveryThroughputAuditError("observation segment entry is invalid")
        _sha(item.get("sha256"), "observation segment SHA-256")
    return value


def _load_acceptance(job: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(job["acceptance_dir"])).expanduser().resolve() / "bodyrig-acceptance.json"
    value = _read_json(path, "Gate A acceptance")
    if value.get("format") != "bodyrig-rig-acceptance" or value.get("version") != 1:
        raise RecoveryThroughputAuditError("Gate A acceptance format/version mismatch")
    if value.get("automated_pass") is not True:
        raise RecoveryThroughputAuditError("Gate A automated_pass is not true")
    checks = value.get("checks")
    if not isinstance(checks, Mapping) or not checks or any(item is not True for item in checks.values()):
        raise RecoveryThroughputAuditError("Gate A checks are not all true")
    if value.get("physical_renderer_acceptance") != "pending" or value.get("production_activation") is not False:
        raise RecoveryThroughputAuditError("Gate A authority boundary is invalid")
    package = value.get("package")
    if not isinstance(package, Mapping):
        raise RecoveryThroughputAuditError("Gate A package identity is invalid")
    if _sha(package.get("package_sha256"), "acceptance.package.package_sha256") != _sha(
        job.get("package_sha256"), "job.package_sha256"
    ):
        raise RecoveryThroughputAuditError("Gate A package SHA does not match the succeeded job")
    body_id = str(package.get("body_id") or "").strip()
    if not body_id:
        raise RecoveryThroughputAuditError("Gate A canonical body id is missing")
    canonical = str(job.get("canonical_body_id") or "").strip()
    if canonical and canonical != body_id:
        raise RecoveryThroughputAuditError("Gate A canonical body id does not match the succeeded job")
    return value


def _load_identity(clone_root: Path, recovery: Mapping[str, Any]) -> dict[str, Any]:
    value = _read_json(clone_root / "clone" / "bodyrig-visual-identity.json", "visual identity profile")
    try:
        return bind_visual_identity_to_proof(value, dict(recovery))
    except ValueError as exc:
        raise RecoveryThroughputAuditError(f"visual identity is not bound to recovery proof: {exc}") from exc


def _load_fidelity_and_review(
    root: Path,
    job: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    package = acceptance["package"]
    body_id = str(package["body_id"])
    package_sha = str(package["package_sha256"])
    try:
        fidelity = validate_fidelity_output(
            str(job["fidelity_dir"]),
            body_id=body_id,
            package_sha256=package_sha,
        )
        review = read_review_by_package(
            root,
            person_id=str(job["person_id"]),
            package_sha256=package_sha,
        )
    except ValueError as exc:
        raise RecoveryThroughputAuditError(f"fidelity/review evidence is not authoritative: {exc}") from exc
    receipt = Path(str(review["root"])) / "review.json"
    if file_sha256(receipt) != _sha(job["body_review_sha256"], "job.body_review_sha256"):
        raise RecoveryThroughputAuditError("persisted body review SHA no longer matches the succeeded job")
    if review.get("body_id") != body_id:
        raise RecoveryThroughputAuditError("persisted body review canonical body id mismatch")
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
    clone_root = Path(str(job["clone_output"])).expanduser().resolve()
    binding = _load_binding(root, job)
    selection = _load_selection(clone_root)
    segments = _load_segments(clone_root)
    recovery = load_recovery_proof(clone_root / "clone" / "bodyrig-recovery-proof.json")
    identity = _load_identity(clone_root, recovery)
    acceptance = _load_acceptance(job)
    accepted_recovery = acceptance.get("recovery")
    if not isinstance(accepted_recovery, Mapping):
        raise RecoveryThroughputAuditError("Gate A recovery identity is invalid")
    for key in ("adapter", "revision", "track_id", "observed_frames"):
        if accepted_recovery.get(key) != recovery.get(key):
            raise RecoveryThroughputAuditError(f"Gate A recovery {key} does not match recovery proof")
    fidelity, review = _load_fidelity_and_review(root, job, acceptance)
    return RunEvidence(
        job=job,
        source_binding=binding,
        selection=selection,
        segments=segments,
        recovery=recovery,
        identity=identity,
        acceptance=acceptance,
        fidelity=fidelity,
        review=review,
        total_seconds=_total_seconds(job),
        clone_pipeline_seconds=_clone_pipeline_seconds(job.get("log_path")),
    )


def _segment_identity(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": item.get("source_id"),
            "scene_id": item.get("scene_id"),
            "start_seconds": item.get("start_seconds"),
            "duration_seconds": item.get("duration_seconds"),
        }
        for item in value.get("segments", [])
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


def compare_runs(baseline: RunEvidence, candidate: RunEvidence) -> dict[str, Any]:
    blockers: list[str] = []
    if baseline.job.get("person_id") != candidate.job.get("person_id"):
        blockers.append("baseline and candidate person_id differ")
    if baseline.source_binding.get("source") != candidate.source_binding.get("source"):
        blockers.append("baseline and candidate Stash performer authority differ")
    base_files = baseline.source_binding.get("evidence", {}).get("source_files")
    cand_files = candidate.source_binding.get("evidence", {}).get("source_files")
    if base_files != cand_files:
        blockers.append("baseline and candidate exact source-file SHA evidence differ")

    for field in ("adapter", "revision"):
        if baseline.selection.get(field) != candidate.selection.get(field):
            blockers.append(f"observation selection {field} differs")
    if baseline.selection.get("selected") != candidate.selection.get("selected"):
        blockers.append("observation selection windows/quality evidence differ")
    if _segment_identity(baseline.segments) != _segment_identity(candidate.segments):
        blockers.append("materialized segment source/start/duration identity differs")

    for field in ("adapter", "revision", "track_id"):
        if baseline.recovery.get(field) != candidate.recovery.get(field):
            blockers.append(f"recovery {field} differs")
    baseline_frames = int(baseline.recovery["observed_frames"])
    candidate_frames = int(candidate.recovery["observed_frames"])
    frame_reduction = candidate_frames < baseline_frames
    if not frame_reduction:
        blockers.append("candidate did not reduce recovery observed_frames")

    identity_deltas = {
        **_numeric_deltas(baseline.identity.get("capture", {}), candidate.identity.get("capture", {}), "capture"),
        **_numeric_deltas(baseline.identity.get("coverage", {}), candidate.identity.get("coverage", {}), "coverage"),
        **_numeric_deltas(baseline.identity.get("quality", {}), candidate.identity.get("quality", {}), "quality"),
    }
    bodyprint_deltas = _numeric_deltas(
        baseline.recovery.get("bodyprint", {}),
        candidate.recovery.get("bodyprint", {}),
        "bodyprint",
    )

    machine_pass = not blockers
    return {
        "format": FORMAT,
        "version": VERSION,
        "baseline_job_id": baseline.job.get("job_id"),
        "candidate_job_id": candidate.job.get("job_id"),
        "person_id": baseline.job.get("person_id"),
        "source_authority_equal": baseline.source_binding.get("source") == candidate.source_binding.get("source")
        and base_files == cand_files,
        "observation_selection_equal": baseline.selection.get("selected") == candidate.selection.get("selected")
        and baseline.selection.get("adapter") == candidate.selection.get("adapter")
        and baseline.selection.get("revision") == candidate.selection.get("revision"),
        "segment_windows_equal": _segment_identity(baseline.segments) == _segment_identity(candidate.segments),
        "recovery_authority_equal": all(
            baseline.recovery.get(field) == candidate.recovery.get(field) for field in ("adapter", "revision", "track_id")
        ),
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
            "clone_pipeline_semantics": "clone-pipeline-wall-clock-includes-observation-recovery-identity-and-fitting",
        },
        "identity_metric_deltas_candidate_minus_baseline": identity_deltas,
        "bodyprint_numeric_deltas_candidate_minus_baseline": bodyprint_deltas,
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
    person_root: str | Path | None = None,
) -> dict[str, Any]:
    baseline = collect_run(baseline_job, person_root=person_root)
    candidate = collect_run(candidate_job, person_root=person_root)
    return compare_runs(baseline, candidate)


def _write_create_only(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise RecoveryThroughputAuditError(f"refusing to overwrite throughput audit: {path}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only A/B audit for BodyRig recovery throughput candidates. Never grants promotion authority."
    )
    parser.add_argument("baseline_job", help="baseline body-build job directory or job.json")
    parser.add_argument("candidate_job", help="candidate body-build job directory or job.json")
    parser.add_argument("--person-root", default="", help="optional Person Library root override")
    parser.add_argument("--out", default="", help="optional create-only JSON report")
    args = parser.parse_args(argv)
    try:
        result = audit(
            args.baseline_job,
            args.candidate_job,
            person_root=args.person_root or None,
        )
        if args.out:
            _write_create_only(Path(args.out), result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        return 0 if result["machine_evidence_pass"] else 1
    except (OSError, RecoveryThroughputAuditError, ValueError) as exc:
        print(f"BodyRig recovery throughput A/B audit: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
