from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "aggregate-photoidentity-multiperformer-detail-evidence.ps1"


def test_multiperformer_detail_aggregation_operator_is_source_only_and_revision_bound() -> None:
    text = SCRIPT.read_text(encoding="utf-8").lower()
    assert "git -c $reporoot rev-parse head" in text
    assert "git -c $reporoot status --porcelain" in text
    assert "bodyrig.photoidentity_multiperformer_detail_aggregate" in text
    assert "bodyrig\\__init__.py" in text
    assert "human-parsing-evidence\\photoidentity-observations.json" in text
    assert "photoidentity-multiperformer-detail-aggregation.json" in text
    assert "[parameter(mandatory = $true)][string[]]$candidateroot" in text
    assert "$candidateroot.count -ne $qualityreceipt.count" in text
    assert '"--candidate-root"' in text
    assert "photoidentity-multiperformer-target-isolation-attestation.json" in text
    assert "nail/anatomy authority: not changed" in text
    assert "production activation: false" in text
    for forbidden in ("run-windows", "run-quest", "manager.start", "clone-body", "run-subject-anatomy"):
        assert forbidden not in text


def test_nail_attestation_preserves_optional_multiperformer_detail_prior() -> None:
    text = (ROOT / "bodyrig" / "photoidentity_nail_source_attestation.py").read_text(encoding="utf-8")
    assert "resolve_pre_nail_bundle(sweep_root)" in text
    assert '"prior_stage": prior_stage' in text
    assert '"base_observation_evidence_sha256"' in text
    assert '"base_sufficiency_report_sha256"' in text
