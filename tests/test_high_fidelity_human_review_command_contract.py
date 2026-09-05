from pathlib import Path

import bodyrig.high_fidelity_release_readiness as readiness


def test_generated_human_review_command_quotes_but_does_not_preapprove_placeholder(tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    command = readiness._review_command(package.resolve())

    assert "record-high-fidelity-human-review.ps1" in command
    assert f"-PackagePath '{package.resolve()}'" in command
    assert "-ConfirmQualityChecklist" in command
    assert "-QualityNote '<QUALITY_NOTE>'" in command
    assert "-QualityNote <QUALITY_NOTE>" not in command
