from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from bodyrig.acceptance_status import AcceptanceStatus
import bodyrig.high_fidelity_physical_acceptance as physical


JOB_ID = "hfpreview-" + "b" * 32
BODY_ID = "bodyid-" + "4" * 24
REVISION = "c" * 40


def _package(tmp_path: Path) -> tuple[Path, str]:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-promoted-package")
    return package, hashlib.sha256(package.read_bytes()).hexdigest()


def _write_receipt(acceptance: Path, package_sha: str, *, version: object) -> Path:
    receipt = acceptance / physical.RECEIPT_NAME
    receipt.write_text(
        json.dumps(
            {
                "format": physical.FORMAT,
                "version": version,
                "previewJobId": JOB_ID,
                "canonicalBodyId": BODY_ID,
                "bodyrigRevision": REVISION,
                "promotedPackageSha256": package_sha,
                "highFidelityHumanReviewSha256": "0" * 64,
                "physicalAcceptanceAuthority": False,
                "productionActivation": False,
            }
        ),
        encoding="utf-8",
    )
    return receipt


def test_boolean_handoff_version_fails_before_canonical_acceptance(monkeypatch, tmp_path: Path) -> None:
    package, package_sha = _package(tmp_path)
    acceptance = tmp_path / "physical-acceptance"
    acceptance.mkdir()
    _write_receipt(acceptance, package_sha, version=True)
    monkeypatch.setattr(physical, "physical_acceptance_dir", lambda _job: acceptance)
    monkeypatch.setattr(
        physical,
        "_validate_gate_a",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gate A must not be read for boolean version")),
    )
    monkeypatch.setattr(
        physical,
        "inspect_acceptance_dir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("canonical acceptance must not run")),
    )

    result = physical.physical_acceptance_status(
        JOB_ID,
        package_path=package,
        package_sha256=package_sha,
    )

    assert result["state"] == "invalid"
    assert result["gate"] == "physical-gate-a"
    assert result["next_command"] is None
    assert result["production_activation"] is False
    assert "stale or non-canonical" in result["message"]


def test_numeric_float_v1_handoff_preserves_canonical_windows_probe(monkeypatch, tmp_path: Path) -> None:
    package, package_sha = _package(tmp_path)
    acceptance = tmp_path / "physical-acceptance"
    acceptance.mkdir()
    accepted = acceptance / f"{BODY_ID}.mrbody"
    accepted.write_bytes(package.read_bytes())
    review = acceptance / "review.json"
    review.write_text("{}", encoding="utf-8")
    receipt = json.loads(_write_receipt(acceptance, package_sha, version=1.0).read_text(encoding="utf-8"))
    receipt["highFidelityHumanReviewSha256"] = physical._hash(review)
    (acceptance / physical.RECEIPT_NAME).write_text(json.dumps(receipt), encoding="utf-8")

    monkeypatch.setattr(physical, "physical_acceptance_dir", lambda _job: acceptance)
    monkeypatch.setattr(physical, "human_review_path", lambda *_args, **_kwargs: review)
    monkeypatch.setattr(physical, "read_human_review", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        physical,
        "_validate_gate_a",
        lambda *_args, **_kwargs: SimpleNamespace(package_hash=package_sha, revision=REVISION),
    )
    monkeypatch.setattr(
        physical,
        "inspect_acceptance_dir",
        lambda _path: AcceptanceStatus(
            "ready",
            "windows-probe",
            str(acceptance),
            BODY_ID,
            REVISION,
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
