from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "setup-photoreal-reference-wsl.ps1").read_text(encoding="utf-8")


def test_reference_wsl_setup_pins_published_onnxruntime_gpu_wheel() -> None:
    assert '$onnxruntimeVersion = "1.20.2"' in SCRIPT
    assert '$onnxruntimeVersion = "1.20.1"' not in SCRIPT
    assert '"onnxruntime-gpu==$onnxruntimeVersion"' in SCRIPT


def test_reference_wsl_force_repair_rebuilds_partial_environment() -> None:
    force_guard = SCRIPT.index("if ($Force)")
    remove_venv = SCRIPT.index('Invoke-Wsl -Root -Arguments @("/bin/rm", "-rf", $venvRoot)')
    create_venv = SCRIPT.index('Invoke-Wsl -Root -Arguments @("/usr/bin/python3", "-m", "venv", $venvRoot)')

    assert force_guard < remove_venv < create_venv
    assert 'Use -Force to rebuild.' in SCRIPT
