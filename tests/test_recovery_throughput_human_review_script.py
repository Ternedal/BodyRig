from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "record-recovery-throughput-human-review.ps1").read_text(encoding="utf-8")


def test_wrapper_requires_explicit_four_criterion_review_and_note() -> None:
    for name in ("IdentityShape", "FaceIdentity", "SkinTextureAlignment", "GrossAnatomy"):
        assert f"[string]${name}" in SCRIPT
    assert SCRIPT.count('[ValidateSet("pass", "fail")]') == 4
    assert "[string]$Note" in SCRIPT
    assert "A human review note is required" in SCRIPT


def test_wrapper_defaults_receipt_outside_immutable_bundle() -> None:
    assert '$Out = "$BundleDir.human-review.json"' in SCRIPT
    assert 'Join-Path $BundleDir "review-bundle.json"' in SCRIPT
    assert 'Join-Path $BundleDir "machine-audit.json"' in SCRIPT
    assert "bodyrig.recovery_throughput_human_review" in SCRIPT


def test_wrapper_records_evidence_only_and_never_mutates_runtime_or_git() -> None:
    forbidden = (
        "git checkout",
        "git reset",
        "git clean",
        "git fetch",
        "Stop-Process",
        "Start-Process",
        "Remove-Item",
        "Set-Content",
        "Add-Content",
        "Move-Item",
        "Copy-Item",
        "/body/build",
        "/voice/",
        "/personality/",
    )
    for token in forbidden:
        assert token not in SCRIPT
    assert "cannot promote or activate anything" in SCRIPT
    assert "promotion/production remain false" in SCRIPT


def test_wrapper_forwards_every_review_dimension_to_python_receipt() -> None:
    assert "--identity-shape $IdentityShape" in SCRIPT
    assert "--face-identity $FaceIdentity" in SCRIPT
    assert "--skin-texture-alignment $SkinTextureAlignment" in SCRIPT
    assert "--gross-anatomy $GrossAnatomy" in SCRIPT
    assert "--reviewer $Reviewer" in SCRIPT
    assert "--note $Note" in SCRIPT
