from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
EXPECTED_READERS = {
    "check-reference-renderer-ready.ps1",
    "complete-reference-acceptance.ps1",
    "high-fidelity-rig-preflight.ps1",
    "prepare-photoreal-v2-p3-quest2-device-handoff.ps1",
    "record-reference-renderer-acceptance.ps1",
    "reference-renderer/build-reference-renderer.ps1",
    "run-fidelity-windows-render-probe.ps1",
    "run-photoreal-v2-p3-quest2-reference-probe.ps1",
    "run-quest-digital-twin-probe.ps1",
    "run-quest-renderer-probe.ps1",
    "run-reference-quest-renderer-probe.ps1",
    "run-reference-windows-renderer-probe.ps1",
    "run-windows-digital-twin-probe.ps1",
    "run-windows-renderer-probe.ps1",
}


def _renderer_contract_readers() -> dict[str, str]:
    readers: dict[str, str] = {}
    for path in REPO.rglob("*.ps1"):
        source = path.read_text(encoding="utf-8-sig")
        if "bodyrig-reference-renderer-contract" not in source or "$contract.version" not in source:
            continue
        readers[path.relative_to(REPO).as_posix()] = source
    return readers


def test_all_powershell_renderer_contract_readers_are_discovered() -> None:
    assert set(_renderer_contract_readers()) == EXPECTED_READERS


def test_powershell_renderer_contract_v1_rejects_boolean_and_string_coercion() -> None:
    for path, source in _renderer_contract_readers().items():
        assert "[int]$contract.version" not in source, path
        assert "$contractVersion = $contract.version" in source, path
        assert "$null -eq $contractVersion" in source, path
        assert "$contractVersion -is [bool]" in source, path
        assert "$contractVersion -isnot [ValueType]" in source, path
        assert "[decimal]$contractVersion -ne [decimal]1" in source, path
