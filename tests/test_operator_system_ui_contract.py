from pathlib import Path


def test_operator_system_readiness_is_read_only_and_pinned() -> None:
    source = Path("bodyrig/operator_system_ui_api.py").read_text(encoding="utf-8")
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")

    assert "/api/v1/operator/system-readiness" in source
    assert "operator_system_ui_router" in app
    assert "app.include_router(operator_system_ui_router)" in app
    assert "Ubuntu-22.04" in source
    assert "/opt/bodyrig-exavatar/bin/python" in source
    assert "/opt/bodyrig-photoreal/bin/python" in source
    assert "required_version" in source and '"12.4"' in source
    assert "renderer-contract.json" in source
    assert "SDK" in source and "platform-tools" in source and "adb.exe" in source
    assert "Get-Command adb" not in source
    assert "read_only" in source
    assert "production_activation" in source
    assert "/api/v1/operator/system-readiness" in js
