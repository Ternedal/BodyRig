from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_human_review_operator_accepts_installed_body_or_exact_package_but_not_both() -> None:
    wrapper = (ROOT / "record-high-fidelity-human-review.ps1").read_text(encoding="utf-8")

    assert '[string]$BodyId = ""' in wrapper
    assert '[string]$PackagePath = ""' in wrapper
    assert "$hasBodyId -eq $hasPackage" in wrapper
    assert "Specify exactly one high-fidelity review source" in wrapper
    assert '@("--body-id", $BodyId)' in wrapper
    assert '@("--package", $PackagePath)' in wrapper


def test_package_review_is_hash_checked_before_and_after_receipt_creation() -> None:
    wrapper = (ROOT / "record-high-fidelity-human-review.ps1").read_text(encoding="utf-8")

    assert "Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256" in wrapper
    assert "reviewed different package bytes" in wrapper
    assert "Reviewed high-fidelity package bytes changed after receipt creation" in wrapper
    assert "Remove-Item -LiteralPath $reviewPath -Force" in wrapper
    assert "production_activation=false" in wrapper


def test_human_review_cli_still_supports_package_bound_review() -> None:
    cli = (ROOT / "bodyrig" / "high_fidelity_human_review_cli.py").read_text(encoding="utf-8")

    assert 'source.add_argument("--package"' in cli
    assert "write_review(" in cli
    assert "read_review(package)" in cli
    assert '"production_activation": False' in cli
