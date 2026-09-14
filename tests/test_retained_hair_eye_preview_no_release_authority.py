from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-retained-hair-eye-preview.ps1"


def test_retained_preview_never_calls_release_or_promotion_operators() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    forbidden = (
        "promote-high-fidelity-hair.ps1",
        "promote-high-fidelity-eyes.ps1",
        "prepare-high-fidelity-physical-acceptance.ps1",
        "finalize-digital-twin-release.ps1",
        "run-automatic-production-activation.ps1",
        "record-renderer-acceptance.ps1",
    )
    for token in forbidden:
        assert token not in text
