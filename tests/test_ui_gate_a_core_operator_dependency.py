from pathlib import Path


def test_ui_operator_checkout_requires_transactional_gate_a_core() -> None:
    source = Path("bodyrig/ui_jobs.py").read_text(encoding="utf-8")
    function = source.split("def operator_checkout_status() -> dict[str, Any]:", 1)[1]
    function = function.split("\n\nclass UiJobManager:", 1)[0]
    assert 'root / "accept-physical-clone.ps1",' in function
    assert 'root / "accept-physical-clone-core.ps1",' in function
    assert function.index('root / "accept-physical-clone.ps1",') < function.index('root / "accept-physical-clone-core.ps1",')
