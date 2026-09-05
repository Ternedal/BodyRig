from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from bodyrig.acceptance_status import AcceptanceStatus
import bodyrig.high_fidelity_physical_acceptance as physical


JOB_ID = "hfpreview-" + "a" * 32


def _package(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "promoted.mrbody"
    path.write_bytes(b"exact-promoted-package")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_missing_physical_acceptance_exposes_create_only_handoff(monkeypatch, tmp_path: Path) -> None:
    acceptance = tmp_path / "physical-acceptance"
    monkeypatch.setattr(physical, "physical_acceptance_dir", lambda _job: acceptance)

    package, package_sha = _package(tmp_path)
    result = physical.physical_acceptance_status(
        JOB_ID,
        package_path=package,
        package_sha256=package_sha,
    )

    assert result["state"] == "required"
    assert result["gate"] == "physical-gate-a"
    assert "prepare-high-fidelity-physical-acceptance.ps1" in result["next_command"]
    assert JOB_ID in result["next_command"]
    assert result["production_activation"] is False


def test_existing_non_directory_handoff_fails_closed(monkeypatch, tmp_path: Path) -> None:
    acceptance = tmp_path / "physical-acceptance"
    acceptance.write_text("not-a-directory", encoding="utf-8")
    monkeypatch.setattr(physical, "physical_acceptance_dir", lambda _job: acceptance)

    package, package_sha = _package(tmp_path)
    result = physical.physical_acceptance_status(
        JOB_ID,
        package_path=package,
        package_sha256=package_sha,
    )

    assert result["state"] == "invalid"
    assert result["gate"] == "physical-gate-a"
    assert result["next_command"] is None
    assert result["production_activation"] is False


def _mock_valid_committed_handoff(monkeypatch, tmp_path: Path, package_sha: str) -> Path:
    acceptance = tmp_path / "physical-acceptance"
    acceptance.mkdir()
    accepted = acceptance / ("bodyid-" + "1" * 24 + ".mrbody")
    accepted.write_bytes(b"exact-promoted-package")
    review = acceptance / "review.json"
    review.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(physical, "physical_acceptance_dir", lambda _job: acceptance)
    monkeypatch.setattr(
        physical,
        "_json",
        lambda *_args, **_kwargs: {
            "format": physical.FORMAT,
            "version": physical.VERSION,
            "previewJobId": JOB_ID,
            "canonicalBodyId": "bodyid-" + "1" * 24,
            "bodyrigRevision": "c" * 40,
            "promotedPackageSha256": package_sha,
            "highFidelityHumanReviewSha256": physical._hash(review),
            "physicalAcceptanceAuthority": False,
            "productionActivation": False,
        },
    )
    monkeypatch.setattr(physical, "human_review_path", lambda *_args, **_kwargs: review)
    monkeypatch.setattr(physical, "read_human_review", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        physical,
        "_validate_gate_a",
        lambda *_args, **_kwargs: SimpleNamespace(package_hash=package_sha, revision="c" * 40),
    )
    return acceptance


def test_valid_handoff_delegates_to_canonical_acceptance_state_machine(monkeypatch, tmp_path: Path) -> None:
    package, package_sha = _package(tmp_path)
    acceptance = _mock_valid_committed_handoff(monkeypatch, tmp_path, package_sha)
    monkeypatch.setattr(
        physical,
        "inspect_acceptance_dir",
        lambda _path: AcceptanceStatus(
            "ready",
            "windows-probe",
            str(acceptance),
            "bodyid-" + "1" * 24,
            "c" * 40,
            "fresh Gate A is ready for Windows",
            '.\\run-windows-renderer-probe.ps1 -AcceptanceDir "x"',
        ),
    )

    result = physical.physical_acceptance_status(
        JOB_ID,
        package_path=package,
        package_sha256=package_sha,
    )

    assert result["state"] == "ready"
    assert result["gate"] == "windows-probe"
    assert "run-windows-renderer-probe.ps1" in result["next_command"]
    assert result["production_activation"] is False


def test_complete_canonical_acceptance_is_the_only_activating_status(monkeypatch, tmp_path: Path) -> None:
    package, package_sha = _package(tmp_path)
    acceptance = _mock_valid_committed_handoff(monkeypatch, tmp_path, package_sha)
    monkeypatch.setattr(
        physical,
        "inspect_acceptance_dir",
        lambda _path: AcceptanceStatus(
            "complete",
            "release",
            str(acceptance),
            "bodyid-" + "1" * 24,
            "c" * 40,
            "canonical final release PASS",
            None,
        ),
    )

    result = physical.physical_acceptance_status(
        JOB_ID,
        package_path=package,
        package_sha256=package_sha,
    )

    assert result["state"] == "complete"
    assert result["gate"] == "release"
    assert result["next_command"] is None
    assert result["production_activation"] is True


def test_prepare_physical_acceptance_materializes_fresh_atomic_gate_a(monkeypatch, tmp_path: Path) -> None:
    package, package_sha = _package(tmp_path)
    body_id = "bodyid-" + "2" * 24
    review = {"human_review_complete": True, "production_activation": False}
    audit = {"canonical_body_id": body_id, "package_sha256": package_sha, "high_fidelity_ready": True, "components": {"body_anatomy": "complete"}}
    monkeypatch.setattr(physical, "_ready_package", lambda _job: (package, package_sha, audit, review))

    source = tmp_path / "source-gate-a"
    source.mkdir()
    session = source / "bodyrig-physical-clone-session.json"
    readiness = source / "bodyrig-rig-readiness.json"
    session.write_bytes(b"exact-session")
    readiness.write_bytes(b"exact-readiness")
    source_gate_path = source / "bodyrig-acceptance.json"
    source_gate_path.write_text("{}", encoding="utf-8")
    source_gate = SimpleNamespace(
        body_id=body_id,
        revision="b" * 40,
        package_hash="d" * 64,
        path=source_gate_path,
    )
    source_report = {
        "source_count": 1,
        "physical_clone": {
            "mode": "stash-sith-high-fidelity",
            "session_sha256": physical._hash(session),
            "readiness_sha256": physical._hash(readiness),
        },
    }
    monkeypatch.setattr(
        physical,
        "_source_gate",
        lambda _job: (
            {"canonical_body_id": body_id},
            {"job_id": "job-" + "3" * 32},
            source,
            source_gate,
            source_report,
        ),
    )

    source_review = tmp_path / "source-review.json"
    source_review.write_text("{}", encoding="utf-8")

    def review_path(path: str | Path, *, package_sha256: str | None = None) -> Path:
        resolved = Path(path).resolve()
        if resolved == package.resolve():
            return source_review
        return resolved.with_name(f"{resolved.stem}.{package_sha256}.review.json")

    monkeypatch.setattr(physical, "human_review_path", review_path)
    monkeypatch.setattr(physical, "read_human_review", lambda *_args, **_kwargs: review)
    monkeypatch.setattr(
        physical,
        "_fresh_qa",
        lambda _package: (
            {"package_sha256": package_sha, "structural_pass": True, "manual_review_required": True, "automated_assessment": "low-risk"},
            {"package_sha256": package_sha, "structural_pass": True, "manual_review_required": True, "automated_assessment": "pass"},
        ),
    )

    def materialize(_package: Path, runtime_dir: Path) -> SimpleNamespace:
        runtime_dir.mkdir()
        (runtime_dir / "runtime-manifest.json").write_text("{}\n", encoding="utf-8")
        return SimpleNamespace(manifest={"body_id": body_id, "package_sha256": package_sha})

    monkeypatch.setattr(physical, "materialize_runtime", materialize)
    monkeypatch.setattr(
        physical,
        "validate_package",
        lambda _package: SimpleNamespace(manifest={"name": "Promoted test body"}, payload_names=("avatar.vrm", "bodyprint.json")),
    )
    monkeypatch.setattr(
        physical,
        "_validate_gate_a",
        lambda *_args, **_kwargs: SimpleNamespace(package_hash=package_sha, body_id=body_id, revision="c" * 40),
    )
    monkeypatch.setattr(
        physical,
        "inspect_acceptance_dir",
        lambda path: AcceptanceStatus(
            "ready",
            "windows-probe",
            str(path),
            body_id,
            "c" * 40,
            "run exact Windows probe",
            f'.\\run-windows-renderer-probe.ps1 -AcceptanceDir "{path}"',
        ),
    )
    final = tmp_path / "physical-acceptance"
    monkeypatch.setattr(physical, "physical_acceptance_dir", lambda _job: final)

    result = physical.prepare_physical_acceptance(JOB_ID, bodyrig_revision="c" * 40)

    assert final.is_dir()
    assert not any(path.name.startswith(".physical-acceptance.partial-") for path in tmp_path.iterdir())
    assert (final / f"{body_id}.mrbody").read_bytes() == package.read_bytes()
    assert (final / "bodyrig-skin-qa.json").is_file()
    assert (final / "bodyrig-mesh-topology-qa.json").is_file()
    assert (final / "runtime" / "runtime-manifest.json").is_file()
    assert (final / physical.RECEIPT_NAME).is_file()
    assert (final / "bodyrig-acceptance.json").is_file()
    assert result["next_gate"] == "windows-probe"
    assert "run-windows-renderer-probe.ps1" in result["next_command"]
    assert result["package_sha256"] == package_sha
    assert result["production_activation"] is False


def test_operator_wrapper_is_clean_checkout_bound_and_non_activating() -> None:
    root = Path(__file__).resolve().parents[1]
    wrapper = (root / "prepare-high-fidelity-physical-acceptance.ps1").read_text(encoding="utf-8")
    source = (root / "bodyrig" / "high_fidelity_physical_acceptance.py").read_text(encoding="utf-8")

    assert "Assert-CheckoutAuthority" in wrapper
    assert "-ExpectedHead $head" in wrapper
    assert "Remove-Item -LiteralPath $createdAcceptance -Recurse -Force" in wrapper
    assert "high_fidelity_physical_acceptance" in wrapper
    assert 'if ([string]$result.next_gate -ne "windows-probe")' in wrapper
    assert "$result.production_activation -ne $false" in wrapper

    assert "skin, topology = _fresh_qa(accepted)" in source
    assert "analyze_skin(package)" in source
    assert "analyze_topology(package)" in source
    assert "materialize_runtime(accepted, runtime_dir)" in source
    assert '"sourceGateASha256"' in source
    assert '"highFidelityHumanReviewSha256"' in source
    assert '"physicalAcceptanceAuthority": False' in source
    assert '"productionActivation": False' in source
