from __future__ import annotations

from pathlib import Path

import bodyrig.high_fidelity_human_review_recovery_cli as recovery_cli


JOB_ID = "hfpreview-" + "9" * 32
ROOT = Path(__file__).resolve().parents[1]


def test_recovery_cli_refuses_after_fresh_gate_a_exists(monkeypatch, tmp_path: Path, capsys) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-package")
    acceptance = tmp_path / "physical-acceptance"
    acceptance.mkdir()

    monkeypatch.setattr(recovery_cli, "physical_acceptance_dir", lambda _job: acceptance)

    def must_not_archive(_package: Path):
        raise AssertionError("archive must not run after fresh Gate A exists")

    monkeypatch.setattr(recovery_cli, "archive_invalid_review", must_not_archive)

    code = recovery_cli.main(["--preview-job-id", JOB_ID, "--package", str(package)])

    assert code == 1
    assert "recovery is disabled after fresh Gate A exists" in capsys.readouterr().err


def test_recovery_wrapper_checks_gate_a_before_cli_mutation() -> None:
    wrapper = (ROOT / "archive-invalid-high-fidelity-human-review.ps1").read_text(encoding="utf-8")

    assert '[Parameter(Mandatory = $true)][string]$PreviewJobId' in wrapper
    assert "^hfpreview-[0-9a-f]{32}$" in wrapper
    assert "physical_acceptance_dir" in wrapper
    assert "Human-review recovery is disabled after fresh Gate A exists" in wrapper
    assert "--preview-job-id $PreviewJobId --package $PackagePath" in wrapper
    gate_check = wrapper.index("physical_acceptance_dir")
    cli_write = wrapper.index("bodyrig.high_fidelity_human_review_recovery_cli")
    assert gate_check < cli_write
