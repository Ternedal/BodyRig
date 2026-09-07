from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.automatic_run_discovery as discovery
import bodyrig.one_command_recovery as recovery
import bodyrig.one_command_recovery_advancement as advancement
from bodyrig.physical_session import mark_fail, mark_pass, mark_readiness_pass, start_session


REVISION = "a" * 40
PERFORMER = "42"
BODY_ID = "fixture-person"
CANONICAL_BODY = "bodyid-" + "b" * 24


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _completed_fixture(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    run_root = tmp_path / "automatic-production" / "fixture"
    clone_output = run_root / "clone-output"
    clone_dir = clone_output / "clone"
    clone_dir.mkdir(parents=True)
    identity = tmp_path / "identity-workspaces" / "fixture"
    reconstruction = identity / "sith-input-v1" / "reconstruction.json"
    reconstruction.parent.mkdir(parents=True)
    reconstruction.write_bytes(b"same-sith-reconstruction")

    failed = run_root / "bodyrig-physical-clone-session.json"
    start_session(
        failed,
        performer_id=PERFORMER,
        body_id=BODY_ID,
        bodyrig_revision=REVISION,
        bodyrig_checkout_clean=True,
        rig_setup_sha256="1" * 64,
    )
    failed_readiness = failed.with_suffix(".readiness.json")
    failed_readiness.write_bytes(b"failed-readiness")
    mark_readiness_pass(failed, readiness_sha256=_sha(failed_readiness))
    mark_fail(failed, stage="clone", message="interrupted fit")

    recovered = clone_output / "physical-session-recovered.json"
    start_session(
        recovered,
        performer_id=PERFORMER,
        body_id=BODY_ID,
        bodyrig_revision=REVISION,
        bodyrig_checkout_clean=True,
        rig_setup_sha256="1" * 64,
    )
    recovered_readiness = recovered.with_suffix(".readiness.json")
    recovered_readiness.write_bytes(b"recovered-readiness")
    mark_readiness_pass(recovered, readiness_sha256=_sha(recovered_readiness))
    mark_pass(recovered, clone_output=str(clone_output.resolve()))

    bound = {
        "recovery_proof_sha256": clone_dir / "bodyrig-recovery-proof.json",
        "visual_identity_sha256": clone_dir / "bodyrig-visual-identity.json",
        "portable_identity_sha256": clone_dir / "bodyrig-portable-identity.json",
        "fitter_config_sha256": clone_output / "bodyrig-sith-fitter-config.json",
        "source_manifest_sha256": clone_output / "bodyrig-stash-source-manifest.json",
    }
    for field, path in bound.items():
        path.write_bytes(field.encode("ascii"))

    package = clone_dir / f"{BODY_ID}.mrbody"
    package.write_bytes(b"recovered-package")
    failed_payload = json.loads(failed.read_text(encoding="utf-8"))
    recovered_payload = json.loads(recovered.read_text(encoding="utf-8"))
    receipt = {
        "format": "bodyrig-interrupted-physical-fit-recovery",
        "version": 1,
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER,
        "body_alias": BODY_ID,
        "recovery_mode": "resume-fit-only",
        "failed_session_id": failed_payload["session_id"],
        "failed_session_sha256": _sha(failed),
        "recovered_session_id": recovered_payload["session_id"],
        "recovered_session_sha256": _sha(recovered),
        "package_sha256": _sha(package),
        "canonical_body_id": CANONICAL_BODY,
        "reconstruction_authority_sha256": _sha(reconstruction),
        "expensive_reconstruction_rerun": False,
        "fitter_rerun": True,
        "resumed_fit_only": True,
        "adopted_complete_package": False,
        "production_activation": False,
    }
    for field, path in bound.items():
        receipt[field] = _sha(path)
    recovery_receipt = clone_output / "interrupted-fit-recovery.json"
    recovery_receipt.write_text(json.dumps(receipt), encoding="utf-8")

    structural = {
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER,
        "body_id": BODY_ID,
        "recovery_mode": "resume-fit-only",
        "session_report": str(failed),
        "clone_output": str(clone_output),
        "identity_workspace": str(identity),
        "run_root": str(run_root),
    }
    return structural, failed, recovered, recovered_readiness


def test_completed_recovery_rebinds_session_readiness_package_and_reconstruction(tmp_path: Path, monkeypatch) -> None:
    structural, _failed, recovered, _readiness = _completed_fixture(tmp_path)
    monkeypatch.setattr(advancement, "validate_package", lambda _path: SimpleNamespace(manifest={"id": CANONICAL_BODY}))
    result = advancement.inspect_completed_recovery(structural)
    assert result is not None
    assert result["recovered_session"] == str(recovered.resolve())
    assert result["recovery_mode"] == "resume-fit-only"
    assert result["expensive_reconstruction_rerun"] is False
    assert result["fitter_rerun"] is False


def test_completed_recovery_fails_closed_after_readiness_tamper(tmp_path: Path, monkeypatch) -> None:
    structural, _failed, _recovered, readiness = _completed_fixture(tmp_path)
    monkeypatch.setattr(advancement, "validate_package", lambda _path: SimpleNamespace(manifest={"id": CANONICAL_BODY}))
    readiness.write_bytes(readiness.read_bytes() + b"tamper")
    with pytest.raises(advancement.OneCommandRecoveryAdvancementError, match="recovered readiness bytes changed"):
        advancement.inspect_completed_recovery(structural)


def test_completed_recovery_requires_session_and_receipt_as_pair(tmp_path: Path, monkeypatch) -> None:
    structural, _failed, _recovered, _readiness = _completed_fixture(tmp_path)
    monkeypatch.setattr(advancement, "validate_package", lambda _path: SimpleNamespace(manifest={"id": CANONICAL_BODY}))
    (Path(structural["clone_output"]) / "interrupted-fit-recovery.json").unlink()
    with pytest.raises(advancement.OneCommandRecoveryAdvancementError, match="must exist together"):
        advancement.inspect_completed_recovery(structural)


def _git_ok(_root: Path, *args: str):
    if args == ("rev-parse", "HEAD"):
        return SimpleNamespace(returncode=0, stdout=REVISION + "\n")
    if args == ("status", "--porcelain"):
        return SimpleNamespace(returncode=0, stdout="")
    raise AssertionError(args)


def test_initial_recovery_command_chains_gate_a_and_resumable_automatic(tmp_path: Path, monkeypatch) -> None:
    structural = {
        "state": "ready",
        "gate": "interrupted-fit-recovery",
        "progress_rank": 5,
        "recovery_mode": "resume-fit-only",
        "fitter_rerun": True,
        "expensive_reconstruction_rerun": False,
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER,
        "body_id": BODY_ID,
        "run_root": str(tmp_path / "run"),
        "session_report": str(tmp_path / "run" / "bodyrig-physical-clone-session.json"),
        "clone_output": str(tmp_path / "run" / "clone-output"),
        "identity_workspace": str(tmp_path / "identity"),
    }
    monkeypatch.setattr(recovery, "inspect_one_command_recovery", lambda _path: structural)
    monkeypatch.setattr(recovery, "_git", _git_ok)
    monkeypatch.setattr(recovery, "inspect_completed_recovery", lambda _structural: None)
    monkeypatch.setattr(recovery, "build_recovery_plan", lambda **_kwargs: {"recovery_mode": "resume-fit-only"})
    status = recovery.build_live_recovery_status(structural["session_report"], tmp_path)
    assert status is not None
    command = str(status["next_command"])
    assert "resume-interrupted-physical-fit.ps1" in command
    assert "-GateAOutputDir" in command
    assert "run-automatic-production-activation.ps1" in command
    assert command.index("resume-interrupted-physical-fit.ps1") < command.index("run-automatic-production-activation.ps1")


def test_completed_recovery_without_gate_a_advances_instead_of_resuming_fit(tmp_path: Path, monkeypatch) -> None:
    structural = {
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER,
        "body_id": BODY_ID,
        "recovery_mode": "resume-fit-only",
        "run_root": str(tmp_path / "run"),
        "session_report": str(tmp_path / "run" / "bodyrig-physical-clone-session.json"),
        "clone_output": str(tmp_path / "run" / "clone-output"),
        "identity_workspace": str(tmp_path / "identity"),
    }
    completed = {
        "state": "complete",
        "gate": "physical-clone",
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER,
        "body_id": BODY_ID,
        "recovery_mode": "resume-fit-only",
        "recovered_session": str(tmp_path / "run" / "clone-output" / "physical-session-recovered.json"),
        "recovery_receipt": str(tmp_path / "run" / "clone-output" / "interrupted-fit-recovery.json"),
        "clone_output": str(tmp_path / "run" / "clone-output"),
        "acceptance_dir": str(tmp_path / "run" / "clone-output" / "acceptance"),
        "expensive_reconstruction_rerun": False,
        "fitter_rerun": False,
    }
    monkeypatch.setattr(recovery, "inspect_one_command_recovery", lambda _path: structural)
    monkeypatch.setattr(recovery, "_git", _git_ok)
    monkeypatch.setattr(recovery, "inspect_completed_recovery", lambda _structural: completed)
    status = recovery.build_live_recovery_status(structural["session_report"], tmp_path)
    assert status is not None
    assert status["gate"] == "gate-a"
    assert status["fitter_rerun"] is False
    assert "accept-physical-clone.ps1" in str(status["next_command"])
    assert "resume-interrupted-physical-fit.ps1" not in str(status["next_command"])


def test_discovery_uses_recovered_session_after_completed_fit_recovery(tmp_path: Path, monkeypatch) -> None:
    original = tmp_path / "bodyrig-physical-clone-session.json"
    original.write_text("{}\n", encoding="utf-8")
    recovered = tmp_path / "clone-output" / "physical-session-recovered.json"
    recovery_structural = {
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER,
        "body_id": BODY_ID,
        "recovery_mode": "resume-fit-only",
        "run_root": str(tmp_path),
        "session_report": str(original),
        "clone_output": str(tmp_path / "clone-output"),
        "identity_workspace": str(tmp_path / "identity"),
        "progress_rank": 5,
        "fitter_rerun": True,
    }
    completed = {
        "bodyrig_revision": REVISION,
        "performer_id": PERFORMER,
        "body_id": BODY_ID,
        "recovery_mode": "resume-fit-only",
        "recovered_session": str(recovered),
        "recovery_receipt": str(tmp_path / "clone-output" / "interrupted-fit-recovery.json"),
        "clone_output": str(tmp_path / "clone-output"),
        "acceptance_dir": str(tmp_path / "clone-output" / "acceptance"),
    }
    monkeypatch.setattr(
        discovery,
        "_session_status",
        lambda _path: SimpleNamespace(state="blocked", gate="physical-clone", bodyrig_revision=REVISION, body_id=BODY_ID),
    )
    monkeypatch.setattr(discovery, "inspect_one_command_recovery", lambda _path: recovery_structural)
    monkeypatch.setattr(discovery, "inspect_completed_recovery", lambda _recovery: completed)
    run = {
        "session_report": str(original),
        "revision": REVISION,
        "performer_id": PERFORMER,
        "body_id": BODY_ID,
        "started_at": "2026-09-07T12:00:00Z",
        "completed_at": "",
        "acceptance_dir": str(tmp_path / "clone-output" / "acceptance"),
    }
    candidate = discovery.candidate_from_run(run)
    assert candidate is not None
    assert candidate["rank"] == 10
    assert candidate["gate"] == "gate-a"
    assert candidate["session_report"] == str(recovered)
    assert candidate["original_failed_session_report"] == str(original.resolve())
    assert candidate["fitter_rerun"] is False
