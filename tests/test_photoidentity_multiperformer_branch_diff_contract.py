from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_human_review_surface_is_separate_from_recovery_contract() -> None:
    expected = {
        "bodyrig/photoidentity_multiperformer_source_discovery.py",
        "bodyrig/photoidentity_multiperformer_review_prepare.py",
        "bodyrig/photoidentity_multiperformer_track_attestation.py",
        "discover-photoidentity-multiperformer-sources.ps1",
        "prepare-photoidentity-multiperformer-track-review.ps1",
        "record-photoidentity-multiperformer-track-attestation.ps1",
    }
    for relative in expected:
        assert (ROOT / relative).is_file()

    # The new human-review path must consume the already-landed source-only
    # PHALP runner instead of modifying production recovery/bodyprint formats.
    prepare = (ROOT / "bodyrig" / "photoidentity_multiperformer_review_prepare.py").read_text(encoding="utf-8")
    assert "run_multiperformer_track_review" in prepare
    assert "bodyrig-recovery-result" not in prepare
    assert "bodyprint" not in prepare.lower()
