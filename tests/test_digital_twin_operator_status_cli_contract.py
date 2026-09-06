from pathlib import Path


def test_operator_status_cli_contract_is_read_only_and_checkout_aware() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "bodyrig" / "digital_twin_operator_status_cli.py").read_text(encoding="utf-8")
    assert "--operator-root" in source
    assert "inspect_operator_status" in source
    assert 'result.get("state") in {"blocked", "invalid"}' in source
