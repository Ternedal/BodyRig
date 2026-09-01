from pathlib import Path


def test_known_bad_baseline_wrapper_is_byte_and_renderer_revision_bound() -> None:
    text = Path("render-known-bad-fidelity-baseline.ps1").read_text(encoding="utf-8")
    assert "64aa10bf5b1ad45a1e5ffdd63328b751b33359b9" in text
    assert "8a8915658201eb8a391a3a2771b2e36bc4fe0e20d293259e015938d5aa6f1897" in text
    assert "status --porcelain" in text
    assert "validate_package" in text
    assert "avatar-fitting" in text
    assert "run-fidelity-windows-render-probe.ps1" in text
    assert "integration-64aa-8a891565" in text
    assert "front-full.png" in text
    assert "three-quarter-full.png" in text
    assert "side-full.png" in text
    assert "face-front.png" in text
    assert "fidelity-render-set.json" in text
    assert "$env:PYTHONPATH = $integration" in text
    assert "BodyRig Python resolved from a different checkout" in text
