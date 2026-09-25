from pathlib import Path


def test_person_studio_exposes_photoreal_control_plane() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/photoreal_control_plane.js").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/photoreal_control_plane.css").read_text(encoding="utf-8")
    app = Path("bodyrig/app.py").read_text(encoding="utf-8")
    api = Path("bodyrig/photoreal_control_plane_ui_api.py").read_text(encoding="utf-8")
    core = Path("bodyrig/photoreal_control_plane_ui.py").read_text(encoding="utf-8")
    launcher = Path("bodyrig/operator_launch.py").read_text(encoding="utf-8")

    assert "/ui/photoreal_control_plane.css" in html
    assert "/ui/photoreal_control_plane.js" in html
    assert "photoreal_control_plane_ui_router" in app
    assert "app.include_router(photoreal_control_plane_ui_router)" in app
    assert "/body/photoreal-control-plane" in api
    assert "/body/photoreal-control-plane/action" in api
    assert "Photoreal V2 · Control Plane" in js
    assert "Kør næste sikre trin" in js
    assert "ExAvatar live" in js
    assert "Preprocess" in js
    assert "neutral renders" in js
    assert "setTimeout(() => void refresh(true)" in js
    assert "canonical_backend_command_only" in core
    assert "list_performer_runs" in core
    assert "_photoreal_run_history" in core
    assert '"historical_execution_authority": False' in core
    assert '"continuation_candidate": is_current' in core
    assert "current_teacher_root=teacher_root" in core
    assert "current_exavatar=exavatar" in core
    assert '"scope": "current-only"' in core
    assert '"live_evidence": (' in core
    assert "teacher_root_valid = teacher_root.is_dir() and not teacher_root.is_symlink()" in core
    assert "teacher_input = _read_json(teacher_input_path) if teacher_root_valid else None" in core
    assert "teacher_output_root.is_dir()" in core
    assert "not teacher_output_root.is_symlink()" in core
    assert "teacher_output_dir.is_dir()" in core
    assert "not teacher_output_dir.is_symlink()" in core
    assert 'teacher_input.get("format") == "bodyrig-photoreal-teacher-input"' in core
    assert "not isinstance(teacher_version, bool)" in core
    assert "not isinstance(calibration_version, bool)" in core
    assert "browser_command_authority" in core
    assert "ExAvatar ser aktiv ud" in core
    assert "_EXAVATAR_ACTIVITY_STALE_SECONDS = 1800.0" in core
    assert 'Path("/proc/uptime")' in core
    assert 'os.sysconf("SC_CLK_TCK")' in core
    assert "oldest_active_process_age_seconds" in core
    assert "_exavatar_activity" in core
    assert '"stalled_suspected": stalled' in core
    assert '"busy": busy' in core
    assert "stalled ? \"ExAvatar kører · mulig stall\" : \"ExAvatar kører\"" in js
    assert "next_command" in core
    assert "launch_canonical_operator(" in core
    assert "shell=False" in launcher
    assert ".photoreal-control-stages" in css


def test_control_plane_never_accepts_a_browser_shell_command() -> None:
    api = Path("bodyrig/photoreal_control_plane_ui_api.py").read_text(encoding="utf-8")
    core = Path("bodyrig/photoreal_control_plane_ui.py").read_text(encoding="utf-8")
    launcher = Path("bodyrig/operator_launch.py").read_text(encoding="utf-8")

    assert "command:" not in api
    assert 'action: str = Field(default="advance", pattern=r"^advance$")' in api
    assert "_ALLOWED_INPUTS" in core
    assert "command = pipeline.get(\"next_command\")" in core
    assert '["pwsh", "-Command"]' not in core
    assert "shell=False" in launcher
