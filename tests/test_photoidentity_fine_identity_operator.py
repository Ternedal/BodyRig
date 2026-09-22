from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "record-photoidentity-fine-identity-attestation.ps1"


def test_operator_is_explicit_fail_closed_and_photoidentical() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    lowered = source.lower()
    for token in (
        "confirmoralteethphotoidentity",
        "confirmchestbreastshapephotoidentity",
        "confirmnippleareolaphotoidentity",
        "confirmintimateanatomyphotoidentity",
        "confirmdistinctivemarkersphotoidentity",
    ):
        assert token in lowered
    assert ".ispresent" in lowered
    assert "generic guessing: false" in lowered
    assert "production activation: false" in lowered
    assert "chest/breast shape" in lowered
    assert "nipple/areola" in lowered
    assert "intimate anatomy" in lowered
    assert "git -c $reporoot status --porcelain" in lowered
