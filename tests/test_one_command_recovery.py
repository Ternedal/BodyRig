from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.one_command_recovery as recovery
from bodyrig.automatic_run_discovery import candidate_from_run, inspect_run_authority
from bodyrig.physical_session import mark_fail, mark_readiness_pass, start_session


REVISION = "1" * 40
BODY_ID = "fixture-person"
PERFORMER_ID = "42"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, *, mode: str = "resume-fit-only") -> tuple[Path, dict]:
    run_root = tmp_path / "automatic-production" / "fixture-run"
    clone_output = run_root / "clone-output"
    clone_dir = clone_output / "clone"
    clone_dir.mkdir(parents=True)
    identity = tmp_path / "identity-workspaces" / "fixture"
    reconstruction = identity / "sith-input-v1" / "reconstruction.json"
    reconstruction.parent.mkdir(parents=True)
    reconstruction.write_bytes(b"reconstruction-authority")

    session = run_root / "bodyrig-physical-clone-session.json"
    start_session(
        session,
        performer_id=PERFORMER_ID,
        body_id=BODY_ID,
        bodyrig_revision=REVISION,
        bodyrig_checkout_clean=True,
        rig_setup_sha256="a" * 64,
    )
    mark_readiness_pass(session, readiness_sha256="b" * 64)
    mark_fail(session, stage="clone", message="fixture interrupted fit")

    files = {
        "proof": clone_dir / "bodyrig-recovery-proof.json",
        "visual_identity": clone_dir / "bodyrig-visual-identity.json",
        "portable_identity": clone_dir / "bodyrig-portable-identity.json",
        "fitter_config": clone_output / "bodyrig-sith-fitter-config.json",
        "source_manifest": clone_output / "bodyrig-stash-source-manifest.json",
    }
    for key, path in files.items():
        path.write_bytes((key + "-authority").encode())

    package = clone_dir / f"{BODY_ID}.mrbody"
    package_sha = None
    reconstruction_sha = _sha(reconstruction)
    if mode == "adopt-complete-package":
        package.write_bytes(b"complete-package-authority")
        package_sha = _sha(package)
        reconstruction.unlink()
        reconstruction_sha = None

    plan = {
        "format": "bodyrig-interrupted-fit-recovery-plan",
        "version": 1,
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER_ID,
        "body_alias": BODY_ID,
        "display_name": "Fixture Person",
        "failed_session_id": json.loads(session.read_text(encoding="utf-8"))["session_id"],
        "recovery_mode": mode,
        "package_already_complete": mode == "adopt-complete-package",
        "package_sha256": package_sha,
        "authority": {
            "failed_session_sha256": _sha(session),
            "recovery_proof_sha256": _sha(files["proof"]),
            "visual_identity_sha256": _sha(files["visual_identity"]),
            "portable_identity_sha256": _sha(files["portable_identity"]),
            "fitter_config_sha256": _sha(files["fitter_config"]),
            "source_manifest_sha256": _sha(files["source_manifest"]),
            "reconstruction_sha256": reconstruction_sha,
        },
        "paths": {
            "failed_session": str(session),
            "clone_output": str(clone_output),
            "clone_dir": str(clone_dir),
            "proof": str(files["proof"]),
            "visual_identity": str(files["visual_identity"]),
            "portable_identity": str(files["portable_identity"]),
            "fitter_config": str(files["fitter_config"]),
            "identity_workspace": str(identity),
            "reconstruction": str(reconstruction),
            "package": str(package),
            "source_manifest": str(files["source_manifest"]),
        },
        "expensive_reconstruction_rerun": False,
        "production_activation": False,
    }
    plan_path = run_root / "interrupted-fit-recovery-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    authority = {
        "format": "bodyrig-one-command-production-authority",
        "version": 1,
        "started_at": "2026-09-07T12:00:00+00:00",
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER_ID,
        "requested_body_alias": BODY_ID,
        "session_report": str(session),
        "clone_output": str(clone_output),
        "acceptance_dir": str(clone_output / "acceptance"),
        "identity_workspace": str(identity),
        "interrupted_fit_recovery_plan": str(plan_path),
        "interrupted_fit_recovery_plan_sha256": _sha(plan_path),
        "recovery_mode": mode,
        "expensive_reconstruction_rerun": False,
        "fitter_rerun": mode == "resume-fit-only",
        "production_activation": False,
    }
    (run_root / "run-authority.json").write_text(json.dumps(authority), encoding="utf-8")
    return session, authority


def test_structural_fit_only_receipt_preserves_reconstruction_without_rerun(tmp_path: Path) -> None:
    session, _ = _fixture(tmp_path)
    status = recovery.inspect_one_command_recovery(session)
    assert status is not None
    assert status["recovery_mode"] == "resume-fit-only"
    assert status["progress_rank"] == 5
    assert status["expensive_reconstruction_rerun"] is False
    assert status["fitter_rerun"] is True


def test_structural_complete_package_receipt_preserves_package_and_fitter(tmp_path: Path) -> None:
    session, _ = _fixture(tmp_path, mode="adopt-complete-package")
    status = recovery.inspect_one_command_recovery(session)
    assert status is not None
    assert status["recovery_mode"] == "adopt-complete-package"
    assert status["progress_rank"] == 8
    assert status["fitter_rerun"] is False


def test_recovery_receipt_fails_closed_after_reconstruction_tamper(tmp_path: Path) -> None:
    session, authority = _fixture(tmp_path)
    reconstruction = Path(authority["identity_workspace"]) / "sith-input-v1" / "reconstruction.json"
    reconstruction.write_bytes(reconstruction.read_bytes() + b"tamper")
    with pytest.raises(recovery.OneCommandRecoveryError, match="reconstruction changed"):
        recovery.inspect_one_command_recovery(session)


def test_failed_one_command_session_without_recovery_receipt_is_not_promoted(tmp_path: Path) -> None:
    session, authority = _fixture(tmp_path)
    run_root = session.parent
    raw = json.loads((run_root / "run-authority.json").read_text(encoding="utf-8"))
    for key in ("identity_workspace", "interrupted_fit_recovery_plan", "interrupted_fit_recovery_plan_sha256", "recovery_mode"):
        raw.pop(key, None)
    (run_root / "run-authority.json").write_text(json.dumps(raw), encoding="utf-8")
    assert recovery.inspect_one_command_recovery(session) is None
    run = inspect_run_authority(run_root)
    assert candidate_from_run(run) is None


def test_automatic_run_discovery_ranks_failed_fit_receipt_as_reuse(tmp_path: Path) -> None:
    session, _ = _fixture(tmp_path)
    run = inspect_run_authority(session.parent)
    candidate = candidate_from_run(run)
    assert candidate is not None
    assert candidate["kind"] == "physical-session"
    assert candidate["gate"] == "interrupted-fit-recovery"
    assert candidate["rank"] == 5
    assert candidate["expensive_reconstruction_rerun"] is False
    assert candidate["fitter_rerun"] is True


def test_live_status_revalidates_producer_plan_and_emits_existing_recovery_command(tmp_path: Path, monkeypatch) -> None:
    session, _ = _fixture(tmp_path)

    class Result:
        def __init__(self, returncode: int, stdout: str):
            self.returncode = returncode
            self.stdout = stdout

    def fake_git(_root: Path, *args: str):
        if args == ("rev-parse", "HEAD"):
            return Result(0, REVISION + "\n")
        if args == ("status", "--porcelain"):
            return Result(0, "")
        raise AssertionError(args)

    monkeypatch.setattr(recovery, "_git", fake_git)
    monkeypatch.setattr(
        recovery,
        "build_recovery_plan",
        lambda **_kwargs: {"recovery_mode": "resume-fit-only"},
    )
    status = recovery.build_live_recovery_status(session, tmp_path)
    assert status is not None
    assert status["policy_scope"] == "producer-revision-one-command-recovery"
    assert "resume-interrupted-physical-fit.ps1" in status["next_command"]
    assert "-FailedSessionReport" in status["next_command"]
    assert status["expensive_reconstruction_rerun"] is False
