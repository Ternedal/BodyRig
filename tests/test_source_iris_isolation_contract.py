from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_candidate_wrapper_is_clean_checkout_and_revision_bound() -> None:
    text = source("prepare-source-iris-isolation.ps1")
    assert "Windows-only" in text
    assert "PowerShell 7+" in text
    assert "status --porcelain" in text
    assert "--bodyrig-revision $head" in text
    assert "--left-cx $LeftCx --left-cy $LeftCy --left-radius $LeftRadius" in text
    assert "--right-cx $RightCx --right-cy $RightCy --right-radius $RightRadius" in text
    assert "$result.iris_identity_isolated -ne $false" in text
    assert "$result.human_review_required -ne $true" in text
    assert "$result.eye_component_authority -ne $false" in text
    assert "$result.production_activation -ne $false" in text
    assert "removed newly created candidate directory" in text


def test_review_wrapper_requires_explicit_visual_confirmation() -> None:
    text = source("record-source-iris-isolation-review.ps1")
    assert "[switch]$ConfirmIrisIsolationChecklist" in text
    assert "if (-not $ConfirmIrisIsolationChecklist)" in text
    assert "both exact source eye crops" in text
    assert "both iris boundaries" in text
    assert "pupil exclusion" in text
    assert "sclera exclusion" in text
    assert "bilateral consistency" in text
    assert "--confirm-iris-isolation-checklist" in text
    assert "--quality-note $QualityNote" in text


def test_review_wrapper_grants_only_narrow_iris_isolation_authority() -> None:
    text = source("record-source-iris-isolation-review.ps1")
    assert "$result.iris_identity_isolated -ne $true" in text
    assert '"source-isolated-review-pass"' in text
    assert "$result.eyes_promotion_eligible -ne $false" in text
    assert "$result.eye_component_authority -ne $false" in text
    assert "$result.production_activation -ne $false" in text
    assert "this receipt alone never makes eyes complete" in text


def test_review_wrapper_revalidates_checkout_and_removes_only_new_review_receipt() -> None:
    text = source("record-source-iris-isolation-review.ps1")
    assert "Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head" in text
    assert "Remove-Item -LiteralPath $reviewPath -Force" in text
    assert "removed only the newly created review receipt" in text
    assert "Remove-Item -LiteralPath $candidateRoot" not in text
    assert "Remove-Item -LiteralPath $sourceRoot" not in text


def test_cli_keeps_candidate_and_review_authority_separate() -> None:
    text = (ROOT / "bodyrig" / "source_iris_isolation_cli.py").read_text(encoding="utf-8")
    assert '"iris_identity_isolated": False' in text
    assert '"human_review_required": True' in text
    assert '"iris_identity_isolated": True' in text
    assert '"eyes_promotion_eligible": False' in text
    assert '"eye_component_authority": False' in text
    assert '"production_activation": False' in text
    assert "explicit --confirm-iris-isolation-checklist is required" in text
