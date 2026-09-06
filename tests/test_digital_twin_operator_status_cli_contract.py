from pathlib import Path

from bodyrig.digital_twin_operator_status_cli import _public_result


def test_operator_status_cli_contract_is_read_only_and_checkout_aware() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "bodyrig" / "digital_twin_operator_status_cli.py").read_text(encoding="utf-8")
    assert "--operator-root" in source
    assert "inspect_operator_status" in source
    assert 'result.get("state") in {"blocked", "invalid"}' in source


def test_public_status_exposes_only_top_level_checkout_authorized_command() -> None:
    result = {
        "state": "blocked",
        "next_command": None,
        "physical_acceptance": {"next_command": ".\\complete-reference-acceptance.ps1"},
        "m5": {
            "platforms": {
                "windows-unity-univrm": {"next_command": ".\\run-windows-digital-twin-probe.ps1"},
                "android-quest-class": {"next_command": ".\\run-quest-digital-twin-probe.ps1"},
            }
        },
    }
    public = _public_result(result)
    assert public["next_command"] is None
    assert public["physical_acceptance"]["next_command"] is None
    assert public["m5"]["platforms"]["windows-unity-univrm"]["next_command"] is None
    assert public["m5"]["platforms"]["android-quest-class"]["next_command"] is None
    assert result["m5"]["platforms"]["windows-unity-univrm"]["next_command"] is not None
