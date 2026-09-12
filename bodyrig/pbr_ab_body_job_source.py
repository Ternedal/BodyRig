from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .person_body_review import PersonBodyReviewError, read_review
from .person_profiles import PersonProfileError, load_profile
from .person_source_alignment import PersonSourceAlignmentError, read_binding
from .storage import person_library, ui_jobs_dir


FORMAT = "bodyrig-pbr-ab-body-job-source"
VERSION = 1
_WORKSPACE_MARKER = "Private identity workspace: "
_JOB_RE = re.compile(r"^job-[0-9a-f]{32}$")
_PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
_BODY_REV_RE = re.compile(r"^body-r[0-9]{4}$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ENQUEUE_FIELDS = {
    "format",
    "version",
    "job_id",
    "person_id",
    "stash_performer_id",
    "expected_bodyrig_revision",
}


class PbrAbBodyJobSourceError(ValueError):
    pass


def _v1(value: object) -> bool:
    return not isinstance(value, bool) and value == 1


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PbrAbBodyJobSourceError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PbrAbBodyJobSourceError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PbrAbBodyJobSourceError(f"{label} must be a JSON object")
    return value


def _revision(value: object, label: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA40_RE.fullmatch(text) is None:
        raise PbrAbBodyJobSourceError(f"{label} is not an exact Git revision")
    return text


def _sha256(value: object, label: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(text) is None:
        raise PbrAbBodyJobSourceError(f"{label} is not a canonical SHA-256")
    return text


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PbrAbBodyJobSourceError(f"Git authority check failed: {' '.join(args)}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        suffix = f": {detail}" if detail else ""
        raise PbrAbBodyJobSourceError(f"Git authority check failed: {' '.join(args)}{suffix}")
    return completed.stdout.strip()


def _canonical_job_path(job_id: str) -> Path:
    if _JOB_RE.fullmatch(job_id) is None:
        raise PbrAbBodyJobSourceError("body job id is not canonical")
    return (ui_jobs_dir() / job_id / "job.json").resolve()


def _assert_exact_path(actual: object, expected: Path, label: str) -> Path:
    text = str(actual or "").strip()
    if not text:
        raise PbrAbBodyJobSourceError(f"succeeded body job is missing {label}")
    path = Path(text).expanduser().resolve()
    if path != expected.resolve():
        raise PbrAbBodyJobSourceError(f"succeeded body job {label} is outside its canonical job root")
    return path


def _workspace_from_log(job: dict[str, Any], log_path: Path) -> Path:
    marker: str | None = None
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                index = line.find(_WORKSPACE_MARKER)
                if index >= 0:
                    value = line[index + len(_WORKSPACE_MARKER) :].strip()
                    if value:
                        marker = value
    except OSError as exc:
        raise PbrAbBodyJobSourceError("succeeded A/B body job log could not be read") from exc
    if marker is None:
        raise PbrAbBodyJobSourceError("succeeded A/B body job did not record its private identity workspace")

    candidate = Path(marker).expanduser()
    if not candidate.is_absolute():
        raise PbrAbBodyJobSourceError("recorded private identity workspace is not absolute")
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise PbrAbBodyJobSourceError("recorded private identity workspace is no longer present")

    person_id = str(job.get("person_id") or "").strip()
    if _PERSON_RE.fullmatch(person_id) is None or not candidate.name.startswith(f"{person_id}-"):
        raise PbrAbBodyJobSourceError("recorded private identity workspace does not belong to this body job")

    allowed_roots: list[Path] = []
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        allowed_roots.append((Path(local_app_data).expanduser().resolve() / "BodyRig" / "identity-workspaces").resolve())
    allowed_roots.append((Path(tempfile.gettempdir()).expanduser().resolve() / "BodyRig" / "identity-workspaces").resolve())
    if not any(candidate.parent == root for root in allowed_roots):
        raise PbrAbBodyJobSourceError("recorded private identity workspace is outside BodyRig managed roots")
    return candidate


def _body_revision(profile: Mapping[str, Any], revision_id: str) -> dict[str, Any]:
    for item in profile.get("body_revisions", []):
        if isinstance(item, Mapping) and item.get("revision_id") == revision_id:
            return dict(item)
    raise PbrAbBodyJobSourceError("succeeded body job references an unknown registered body revision")


def _verify_source_enqueue_authority(
    *,
    job: dict[str, Any],
    person_id: str,
    job_id: str,
    job_revision: str,
) -> str:
    marker = job.get("source_enqueue_authority")
    if not isinstance(marker, dict) or set(marker) != _SOURCE_ENQUEUE_FIELDS:
        raise PbrAbBodyJobSourceError("body job lacks canonical revision-bound source enqueue authority")
    if marker.get("format") != "bodyrig-body-build-source-enqueue-authority" or not _v1(marker.get("version")):
        raise PbrAbBodyJobSourceError("body job source enqueue authority format/version mismatch")
    if str(marker.get("job_id") or "") != job_id or str(marker.get("person_id") or "") != person_id:
        raise PbrAbBodyJobSourceError("body job source enqueue authority identity mismatch")
    if _revision(marker.get("expected_bodyrig_revision"), "source enqueue expected revision") != job_revision:
        raise PbrAbBodyJobSourceError("body job source enqueue authority revision mismatch")
    performer_id = str(marker.get("stash_performer_id") or "").strip()
    if not performer_id:
        raise PbrAbBodyJobSourceError("body job source enqueue authority has no Stash performer id")
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise PbrAbBodyJobSourceError("body job Person profile is no longer valid for source enqueue authority") from exc
    source = profile.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        raise PbrAbBodyJobSourceError("Person is no longer bound to the body job's Stash performer")
    if str(source.get("performer_id") or "").strip() != performer_id:
        raise PbrAbBodyJobSourceError("Person Stash performer changed after the revision-bound body job")
    return performer_id


def _verify_persisted_receipts(
    *,
    job: dict[str, Any],
    person_id: str,
) -> dict[str, str]:
    body_revision = str(job.get("body_revision") or "").strip()
    if _BODY_REV_RE.fullmatch(body_revision) is None:
        raise PbrAbBodyJobSourceError("succeeded A/B body job has no canonical body revision")
    canonical_body_id = str(job.get("canonical_body_id") or "").strip()
    if not canonical_body_id:
        raise PbrAbBodyJobSourceError("succeeded A/B body job is missing canonical_body_id")

    library = person_library().resolve()
    try:
        profile = load_profile(library, person_id)
    except PersonProfileError as exc:
        raise PbrAbBodyJobSourceError("succeeded A/B body job Person profile is no longer valid") from exc
    registered = _body_revision(profile, body_revision)
    if str(registered.get("body_id") or "").strip() != canonical_body_id:
        raise PbrAbBodyJobSourceError("body job canonical body id no longer matches its registered body revision")

    source_binding_path = (library / ".source-bindings" / person_id / f"{body_revision}.json").resolve()
    try:
        read_binding(library, profile, kind="body", revision_id=body_revision)
    except PersonSourceAlignmentError as exc:
        raise PbrAbBodyJobSourceError("registered body source binding is no longer authoritative") from exc
    expected_source_binding_sha = _sha256(job.get("source_binding_sha256"), "body job source binding SHA-256")
    try:
        actual_source_binding_sha = _file_sha256(source_binding_path)
    except OSError as exc:
        raise PbrAbBodyJobSourceError("registered body source binding receipt is no longer readable") from exc
    if actual_source_binding_sha != expected_source_binding_sha:
        raise PbrAbBodyJobSourceError("registered body source binding receipt changed after body job success")

    try:
        review = read_review(library, profile, body_revision=body_revision)
    except PersonBodyReviewError as exc:
        raise PbrAbBodyJobSourceError("registered body fidelity review is no longer authoritative") from exc
    package_sha = _sha256(registered.get("package_sha256"), "registered body revision package SHA-256")
    expected_review_root = (library / ".body-reviews" / person_id / package_sha).resolve()
    review_root = Path(str(review.get("root") or "")).expanduser().resolve()
    if review_root != expected_review_root:
        raise PbrAbBodyJobSourceError("registered body fidelity review is outside its canonical Person/package root")
    review_path = review_root / "review.json"
    expected_review_sha = _sha256(job.get("body_review_sha256"), "body job review SHA-256")
    try:
        actual_review_sha = _file_sha256(review_path)
    except OSError as exc:
        raise PbrAbBodyJobSourceError("registered body fidelity review receipt is no longer readable") from exc
    if actual_review_sha != expected_review_sha:
        raise PbrAbBodyJobSourceError("registered body fidelity review receipt changed after body job success")

    return {
        "body_revision": body_revision,
        "canonical_body_id": canonical_body_id,
        "source_binding": str(source_binding_path),
        "source_binding_sha256": actual_source_binding_sha,
        "body_review": str(review_path),
        "body_review_sha256": actual_review_sha,
    }


def inspect_body_job_source(
    *,
    job_id: str,
    repo_root: str | Path,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    repo = Path(repo_root).expanduser().resolve()
    head = _revision(_git(repo, "rev-parse", "HEAD"), "BodyRig checkout HEAD")
    origin_main = _revision(_git(repo, "rev-parse", "refs/remotes/origin/main"), "origin/main")
    if head != origin_main:
        raise PbrAbBodyJobSourceError(
            f"PBR body-job reuse requires exact current origin/main; checkout={head}, origin/main={origin_main}"
        )
    if expected_revision is not None and head != _revision(expected_revision, "expected BodyRig revision"):
        raise PbrAbBodyJobSourceError("BodyRig checkout changed from the wrapper's expected revision")

    job_path = _canonical_job_path(job_id)
    job = _read_json(job_path, "succeeded A/B baseline body job")
    if job.get("format") != "bodyrig-ui-job" or not _v1(job.get("version")):
        raise PbrAbBodyJobSourceError("body job format/version mismatch")
    if job.get("job_id") != job_id:
        raise PbrAbBodyJobSourceError("body job id does not match its canonical storage path")
    if job.get("kind") != "body-build" or job.get("status") != "succeeded":
        raise PbrAbBodyJobSourceError("PBR body-job reuse requires a succeeded body-build job")

    person_id = str(job.get("person_id") or "").strip()
    if _PERSON_RE.fullmatch(person_id) is None:
        raise PbrAbBodyJobSourceError("succeeded body job has no canonical Person id")
    job_revision = _revision(job.get("bodyrig_revision"), "body job BodyRig revision")
    if job_revision != head:
        raise PbrAbBodyJobSourceError(
            f"succeeded A/B baseline body job belongs to {job_revision}, not current main {head}"
        )
    stash_performer_id = _verify_source_enqueue_authority(
        job=job,
        person_id=person_id,
        job_id=job_id,
        job_revision=job_revision,
    )

    retention = job.get("ab_baseline_retention")
    if not isinstance(retention, dict):
        raise PbrAbBodyJobSourceError("body job lacks revision-bound A/B private-workspace retention authority")
    if (
        retention.get("format") != "bodyrig-ab-baseline-retention"
        or not _v1(retention.get("version"))
        or retention.get("retain_private_workspace") is not True
        or retention.get("job_id") != job_id
        or _revision(retention.get("expected_bodyrig_revision"), "A/B retention expected revision") != job_revision
    ):
        raise PbrAbBodyJobSourceError("body job A/B retention authority is malformed or revision-mismatched")

    root = job_path.parent
    clone_output = _assert_exact_path(job.get("clone_output"), root / "clone-output", "clone_output")
    acceptance_dir = _assert_exact_path(job.get("acceptance_dir"), root / "acceptance", "acceptance_dir")
    fidelity_dir = _assert_exact_path(job.get("fidelity_dir"), root / "fidelity-review", "fidelity_dir")
    log_path = _assert_exact_path(job.get("log_path"), root / "job.log", "log_path")
    _assert_exact_path(job.get("session_report"), root / "physical-session.json", "session_report")

    for path, label in (
        (clone_output, "clone output"),
        (acceptance_dir, "Gate A acceptance directory"),
        (fidelity_dir, "fidelity review directory"),
    ):
        if not path.is_dir():
            raise PbrAbBodyJobSourceError(f"succeeded A/B body job {label} is missing")
    if not log_path.is_file():
        raise PbrAbBodyJobSourceError("succeeded A/B body job log is missing")
    if not (clone_output / "bodyrig-sith-fitter-config.json").is_file():
        raise PbrAbBodyJobSourceError("succeeded A/B body job lacks canonical SiTH fitter config")
    if not (acceptance_dir / "bodyrig-acceptance.json").is_file():
        raise PbrAbBodyJobSourceError("succeeded A/B body job lacks Gate A evidence")
    # The authoritative body fidelity review is persisted under the Person Library
    # and verified below against job.body_review_sha256. The per-job fidelity
    # directory is renderer evidence only; no duplicate review.json mirror is required.

    persisted = _verify_persisted_receipts(job=job, person_id=person_id)

    workspace = _workspace_from_log(job, log_path)
    sith_input = workspace / "sith-input-v1"
    reconstruction = sith_input / "reconstruction.json"
    reconstruction_authority = sith_input / "reconstruction-authority.json"
    if not reconstruction.is_file() or not reconstruction_authority.is_file():
        raise PbrAbBodyJobSourceError("retained A/B workspace lacks completed SiTH reconstruction authority")

    policy_path = repo / "contracts" / "pbr-ab-source-policy-v1.json"
    policy = _read_json(policy_path, "PBR A/B retained-source policy")
    if set(policy) != {"format", "version", "safe_source_floor_revision"}:
        raise PbrAbBodyJobSourceError("PBR A/B retained-source policy fields do not match v1")
    if policy.get("format") != "bodyrig-pbr-ab-source-policy" or not _v1(policy.get("version")):
        raise PbrAbBodyJobSourceError("PBR A/B retained-source policy format/version mismatch")
    floor = _revision(policy.get("safe_source_floor_revision"), "safe-source floor revision")
    _git(repo, "cat-file", "-e", f"{floor}^{{commit}}")
    _git(repo, "cat-file", "-e", f"{job_revision}^{{commit}}")
    try:
        _git(repo, "merge-base", "--is-ancestor", floor, job_revision)
    except PbrAbBodyJobSourceError as exc:
        raise PbrAbBodyJobSourceError(
            f"body job revision {job_revision} is not proven at/after safe-source floor {floor}"
        ) from exc

    return {
        "format": FORMAT,
        "version": VERSION,
        "source_mode": "revision-bound-succeeded-body-build",
        "body_job_id": job_id,
        "person_id": person_id,
        "stash_performer_id": stash_performer_id,
        "bodyrig_revision": job_revision,
        "body_revision": persisted["body_revision"],
        "canonical_body_id": persisted["canonical_body_id"],
        "safe_source_floor_revision": floor,
        "safe_source_lineage_passed": True,
        "job_json": str(job_path),
        "job_json_sha256": _file_sha256(job_path),
        "producer_log": str(log_path),
        "producer_log_sha256": _file_sha256(log_path),
        "baseline_clone_output": str(clone_output),
        "identity_workspace": str(workspace),
        "reconstruction": str(reconstruction),
        "reconstruction_sha256": _file_sha256(reconstruction),
        "reconstruction_authority": str(reconstruction_authority),
        "reconstruction_authority_sha256": _file_sha256(reconstruction_authority),
        "source_binding": persisted["source_binding"],
        "source_binding_sha256": persisted["source_binding_sha256"],
        "body_review": persisted["body_review"],
        "body_review_sha256": persisted["body_review_sha256"],
        "source_policy_sha256": _file_sha256(policy_path),
        "comparison_only": True,
        "human_visual_authority_required": True,
        "physical_acceptance_authority": False,
        "production_activation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a succeeded revision-bound A/B body job as retained PBR source")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--expected-revision")
    args = parser.parse_args(argv)
    try:
        result = inspect_body_job_source(
            job_id=args.job_id,
            repo_root=args.repo_root,
            expected_revision=args.expected_revision,
        )
    except PbrAbBodyJobSourceError as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
