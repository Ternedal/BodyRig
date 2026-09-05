from pathlib import Path


def test_rig_preflight_requires_human_review_and_recovery_wrappers() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "high-fidelity-rig-preflight.ps1").read_text(encoding="utf-8")

    assert '"record-high-fidelity-human-review.ps1"' in source
    assert '"archive-invalid-high-fidelity-human-review.ps1"' in source
    assert source.index('"record-high-fidelity-human-review.ps1"') < source.index('"prepare-high-fidelity-physical-acceptance.ps1"')
    assert source.index('"archive-invalid-high-fidelity-human-review.ps1"') < source.index('"prepare-high-fidelity-physical-acceptance.ps1"')
