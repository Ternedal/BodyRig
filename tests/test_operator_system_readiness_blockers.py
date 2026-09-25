from __future__ import annotations

from bodyrig import operator_system_ui_api as ui


def _ready_wsl() -> dict:
    return {
        "available": True,
        "ready": True,
        "distribution": "Ubuntu-22.04",
        "reason": None,
        "gpu": {"ready": True, "summary": "RTX"},
        "cuda": {"ready": True, "version": "12.4", "required_version": "12.4"},
        "exavatar_runtime": True,
        "exavatar_runtime_marker": True,
        "exavatar_runtime_receipt": True,
        "exavatar_runtime_complete": True,
        "materializer_runtime": True,
        "public_dependencies": True,
        "active_exavatar_processes": [],
        "busy": False,
    }


def test_system_readiness_blockers_are_empty_only_for_required_ready_evidence() -> None:
    assert ui._system_readiness_blockers(_ready_wsl(), powershell_7=True) == []


def test_system_readiness_blockers_explain_each_required_missing_component() -> None:
    value = _ready_wsl()
    value["gpu"] = {"ready": False, "summary": None}
    value["cuda"] = {"ready": False, "version": "12.3", "required_version": "12.4"}
    value["exavatar_runtime"] = False
    value["exavatar_runtime_receipt"] = False
    value["exavatar_runtime_complete"] = False
    value["materializer_runtime"] = False
    value["public_dependencies"] = False

    blockers = ui._system_readiness_blockers(value, powershell_7=False)

    assert "PowerShell 7 (pwsh) is not available" in blockers
    assert "NVIDIA GPU is not visible inside the pinned WSL distribution" in blockers
    assert "CUDA toolkit mismatch: observed 12.3, required 12.4" in blockers
    assert any("/opt/bodyrig-exavatar/bin/python" in item for item in blockers)
    assert any("bodyrig-exavatar-runtime-setup.json" in item for item in blockers)
    assert any("/opt/bodyrig-photoreal/bin/python" in item for item in blockers)
    assert any("bodyrig-public-dependencies.json" in item for item in blockers)


def test_unavailable_wsl_reports_root_cause_without_component_noise() -> None:
    blockers = ui._system_readiness_blockers(
        {
            "available": False,
            "ready": False,
            "distribution": "Ubuntu-22.04",
            "reason": "distribution not found",
        },
        powershell_7=True,
    )

    assert blockers == ["distribution not found"]


def test_quest_is_advisory_not_global_system_readiness_authority(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ui, "_wsl_status", _ready_wsl)
    monkeypatch.setattr(ui.shutil, "which", lambda name: "pwsh.exe" if name in {"pwsh.exe", "pwsh"} else None)
    monkeypatch.setattr(
        ui,
        "_quest_status",
        lambda: {
            "ready": False,
            "reason": "No online Quest/Oculus adb device",
            "devices": [],
            "quest_device_count": 0,
        },
    )

    value = ui.operator_system_readiness()

    assert value["ready"] is True
    assert value["blockers"] == []
    assert value["quest"]["ready"] is False
    assert value["production_activation"] is False
