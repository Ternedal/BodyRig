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
