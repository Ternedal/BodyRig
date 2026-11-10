"""Option B (Anders, 10 Nov 2026): an opt-in end of scene-Gaussian densification.

Off by default: without --densify-end-fraction, nothing reaches train.py and it behaves as the
pinned upstream. With it, the fraction travels PowerShell -> config CLI -> config -> bridge ->
adapter -> train.py, and a run resumes only with the setting it started with.
"""

from __future__ import annotations

import importlib.util
import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig import photoreal_exavatar_teacher_config_cli as cli
from bodyrig import photoreal_exavatar_teacher_wsl_bridge as bridge
from bodyrig.photoreal_exavatar_teacher_config import (
    PhotorealExAvatarTeacherConfigError,
    build_exavatar_teacher_config,
    build_exavatar_teacher_config_file,
    validate_exavatar_teacher_config_file,
)

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_exavatar_teacher_adapter.py"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("bodyrig_test_densify_end_adapter", ADAPTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _files(tmp_path: Path) -> dict[str, object]:
    python = tmp_path / "python.exe"
    bridge_file = tmp_path / "bridge.py"
    adapter = tmp_path / "adapter.py"
    python.write_bytes(b"python")
    bridge_file.write_bytes(b"bridge")
    adapter.write_bytes(b"adapter")
    return dict(
        windows_python=python,
        bridge_path=bridge_file,
        adapter_path=adapter,
        linux_workspace_root="/opt/bodyrig-exavatar/workspaces/bodyrig-42",
        linux_runtime_preflight="/opt/bodyrig-exavatar/workspaces/bodyrig-42/runtime-preflight.json",
    )


# --- one canonical value ----------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "  ", "0"])
def test_no_value_means_the_upstream_schedule(raw: object) -> None:
    assert bridge.canonical_densify_end_fraction(raw) is None


@pytest.mark.parametrize(("raw", "canonical"), [("0.5", "0.5000"), (0.5, "0.5000"), ("1", "1.0000"), ("0.05", "0.0500")])
def test_a_value_has_one_canonical_spelling(raw: object, canonical: str) -> None:
    assert bridge.canonical_densify_end_fraction(raw) == canonical


@pytest.mark.parametrize("raw", ["0.04", "1.01", "-0.5", "nan", "inf", "half", True])
def test_out_of_range_or_non_numbers_are_refused(raw: object) -> None:
    with pytest.raises(bridge.PhotorealExAvatarTeacherWslError):
        bridge.canonical_densify_end_fraction(raw)


# --- config -----------------------------------------------------------------------------------


def test_the_default_config_command_is_unchanged(tmp_path: Path) -> None:
    command = build_exavatar_teacher_config(**_files(tmp_path))["command"]
    assert len(command) == 14 and "--densify-end-fraction" not in command


def test_the_opt_in_adds_one_pair_to_the_command(tmp_path: Path) -> None:
    command = build_exavatar_teacher_config(**_files(tmp_path), densify_end_fraction="0.5")["command"]
    assert command[-2:] == ["--densify-end-fraction", "0.5000"] and len(command) == 16


def test_a_config_is_reused_only_with_the_same_setting(tmp_path: Path) -> None:
    files = _files(tmp_path)
    out = tmp_path / "config.json"
    build_exavatar_teacher_config_file(output_path=out, **files, densify_end_fraction="0.5")
    validate_exavatar_teacher_config_file(config_path=out, **files, densify_end_fraction="0.50")
    for other in (None, "0.6"):
        with pytest.raises(PhotorealExAvatarTeacherConfigError):
            validate_exavatar_teacher_config_file(config_path=out, **files, densify_end_fraction=other)
    with pytest.raises(PhotorealExAvatarTeacherConfigError):
        build_exavatar_teacher_config(**files, densify_end_fraction="2")


def _stale(command_tail: list[str]) -> dict[str, object]:
    return {
        "format": cli.FORMAT,
        "version": cli.VERSION,
        "adapter": cli.ADAPTER,
        "revision": "sha256:" + "1" * 64,
        "upstream_repository": cli.UPSTREAM_REPOSITORY,
        "upstream_commit": cli.UPSTREAM_COMMIT,
        "command": [
            "C:/Python/python.exe", "C:/BodyRig/bridge.py",
            "--distribution", "Ubuntu-22.04", "--wsl-exe", "wsl.exe",
            "--linux-python", "/opt/bodyrig-exavatar/bin/python",
            "--workspace-root", "/opt/w", "--runtime-preflight", "/opt/w/runtime-preflight.json",
            "--adapter-script", "C:/BodyRig/adapter.py", *command_tail,
        ],
        "timeout_seconds": cli.MAX_TIMEOUT_SECONDS,
    }


def test_a_stale_config_with_the_opt_in_is_still_replaceable_but_nothing_else_is(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    for tail, replaceable in (([], True), (["--densify-end-fraction", "0.5000"], True),
                              (["--something-else", "1"], False), (["--densify-end-fraction"], False)):
        path.write_text(json.dumps(_stale(tail)), encoding="utf-8")
        assert cli._is_replaceable_stale_config(path) is replaceable, tail


# --- bridge -----------------------------------------------------------------------------------


def _bridge_invocation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extra: list[str]) -> list[str]:
    adapter = tmp_path / "adapter.py"
    adapter.write_text("print('adapter')\n", encoding="utf-8")
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    output = tmp_path / "out"
    captured: dict[str, list[str]] = {}
    monkeypatch.setattr(bridge, "make_wsl_path_converter", lambda _exe, _dist: (lambda value: "/mnt/x/" + Path(value).name))
    monkeypatch.setattr(bridge, "_relay_child", lambda invocation: captured.setdefault("argv", list(invocation)) and 0)
    revision = bridge.build_teacher_transport_revision(bridge_path=Path(bridge.__file__), adapter_path=adapter)
    code = bridge.main([
        "--distribution", "Ubuntu-22.04", "--linux-python", "/opt/py", "--workspace-root", "/opt/w",
        "--runtime-preflight", "/opt/w/r.json", "--adapter-script", str(adapter), "--bodyrig-request", str(request),
        "--bodyrig-output", str(output), "--bodyrig-adapter", "exavatar-benchmark", "--bodyrig-revision", revision,
        "--bodyrig-upstream-commit", "d45268730c779fae4118f1a361cf9ff639bc4d1e", *extra,
    ])
    assert code == 0
    return captured["argv"]


def test_the_bridge_forwards_the_opt_in_and_nothing_without_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert "--bodyrig-densify-end-fraction" not in _bridge_invocation(monkeypatch, tmp_path, [])
    argv = _bridge_invocation(monkeypatch, tmp_path, ["--densify-end-fraction", "0.5"])
    assert argv[-2:] == ["--bodyrig-densify-end-fraction", "0.5000"]


# --- adapter: schedule binding ----------------------------------------------------------------


def test_the_adapter_validates_its_own_value() -> None:
    adapter = _load_adapter()
    assert adapter._densify_end_fraction(None) is None
    assert adapter._densify_end_fraction("0.5") == "0.5000"
    for bad in ("0.01", "1.5", "nan", "x"):
        with pytest.raises(adapter.ExAvatarTeacherAdapterError):
            adapter._densify_end_fraction(bad)


def test_a_run_resumes_only_with_the_schedule_it_started_with(tmp_path: Path) -> None:
    adapter = _load_adapter()
    record = tmp_path / "logs" / "teacher" / "training-schedule.json"
    started = adapter._bind_training_schedule(record, training_mode="fresh", fraction="0.5000")
    assert json.loads(record.read_text(encoding="utf-8"))["densify_end_fraction"] == "0.5000"
    assert started["upstream_densify_end_itr"] == 15000
    for mode in ("resume-from-checkpoint", "reuse-final-checkpoint"):
        assert adapter._bind_training_schedule(record, training_mode=mode, fraction="0.5000")["densify_end_fraction"] == "0.5000"
        for other in (None, "0.6000"):
            with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="started with densify end fraction 0.5000"):
                adapter._bind_training_schedule(record, training_mode=mode, fraction=other)


def test_a_run_from_before_the_record_counts_as_upstream(tmp_path: Path) -> None:
    adapter = _load_adapter()
    record = tmp_path / "training-schedule.json"
    assert adapter._bind_training_schedule(record, training_mode="resume-from-checkpoint", fraction=None)
    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="started with densify end fraction upstream"):
        adapter._bind_training_schedule(record, training_mode="resume-from-checkpoint", fraction="0.5000")
    assert not record.exists(), "a resume never writes the record"


def test_only_an_explicit_choice_reaches_train_py(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = _load_adapter()
    seen: list[dict[str, str]] = []
    monkeypatch.setattr(adapter, "run_watched_process", lambda argv, **kwargs: seen.append(dict(kwargs["env"])) or 0)
    monkeypatch.setenv("BODYRIG_DENSIFY_END_FRACTION", "0.1")  # inherited: must not leak through
    adapter._run(["x"], cwd=tmp_path, log_path=tmp_path / "train.log", label="t")
    adapter._run(["x"], cwd=tmp_path, log_path=tmp_path / "train.log", label="t",
                 extra_env={"BODYRIG_DENSIFY_END_FRACTION": "0.5000"})
    assert "BODYRIG_DENSIFY_END_FRACTION" not in seen[0]
    assert seen[1]["BODYRIG_DENSIFY_END_FRACTION"] == "0.5000"


# --- adapter: the train.py patch --------------------------------------------------------------


def test_the_patch_applies_once_and_refuses_changed_markers(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "train.py"
    path.write_text("a\n" + adapter.TRAIN_DENSIFY_END_ORIGINAL + "b\n", encoding="utf-8")
    assert adapter._ensure_training_densify_end_patch(path)["applied"] is True
    patched = path.read_text(encoding="utf-8")
    assert adapter._ensure_training_densify_end_patch(path)["applied"] is False
    assert path.read_text(encoding="utf-8") == patched
    path.write_text(adapter.TRAIN_DENSIFY_END_ORIGINAL * 2, encoding="utf-8")
    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="densification-end markers"):
        adapter._ensure_training_densify_end_patch(path)


def _densify_end(adapter, *, fraction: str | None, tot_itr: int, itr: int = 0) -> tuple[int, list[str]]:
    logged: list[str] = []
    code = textwrap.dedent(adapter.TRAIN_DENSIFY_END_PATCHED) + "    densified = True\n"
    namespace = {
        "cfg": SimpleNamespace(densify_end_itr=15000, fit_pose_to_test=False),
        "trainer": SimpleNamespace(logger=SimpleNamespace(info=logged.append)),
        "tot_itr": tot_itr,
        "itr": itr,
        "cur_itr": 0,
    }
    import os

    previous = os.environ.pop("BODYRIG_DENSIFY_END_FRACTION", None)
    try:
        if fraction is not None:
            os.environ["BODYRIG_DENSIFY_END_FRACTION"] = fraction
        exec(compile(code, "train.py", "exec"), namespace)
    finally:
        os.environ.pop("BODYRIG_DENSIFY_END_FRACTION", None)
        if previous is not None:
            os.environ["BODYRIG_DENSIFY_END_FRACTION"] = previous
    return namespace["bodyrig_densify_end_itr"], logged


def test_without_the_opt_in_train_py_keeps_upstreams_end() -> None:
    adapter = _load_adapter()
    end, logged = _densify_end(adapter, fraction=None, tot_itr=9000)
    assert end == 15000
    assert logged == ["BodyRig densify_end_itr 15000 of 9000 iterations (fraction upstream)"]


def test_with_the_opt_in_densification_ends_at_the_fraction_never_later_than_upstream() -> None:
    adapter = _load_adapter()
    assert _densify_end(adapter, fraction="0.5000", tot_itr=9000)[0] == 4500
    assert _densify_end(adapter, fraction="1.0000", tot_itr=40000)[0] == 15000
    assert _densify_end(adapter, fraction="0.5000", tot_itr=9000, itr=7)[1] == [], "logged once per epoch start"


def test_the_patched_condition_compiles_in_its_train_py_loop() -> None:
    adapter = _load_adapter()
    loop = "def main():\n    for epoch in range(1):\n        for itr in range(1):\n" + adapter.TRAIN_DENSIFY_END_PATCHED + "                pass\n"
    compile(loop, "train.py", "exec")


# --- the run's identity (Codex #1407 4523288345) -----------------------------------------------


def _runner_helpers():
    spec = importlib.util.spec_from_file_location(
        "bodyrig_test_densify_runner_helpers", ROOT / "tests" / "test_photoreal_teacher_runner.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_request_carries_the_opt_in_and_is_unchanged_without_it() -> None:
    from bodyrig.photoreal_teacher_runner import build_teacher_request

    helpers = _runner_helpers()
    teacher_input = helpers._teacher_input()
    plain = build_teacher_request(helpers._config(["python", "bridge.py"]), teacher_input)
    assert "training_schedule" not in plain, "requests of runs without the option stay byte-for-byte the same"
    opted = build_teacher_request(
        helpers._config(["python", "bridge.py", "--densify-end-fraction", "0.5000"]), teacher_input
    )
    assert opted["training_schedule"] == {"densify_end_fraction": "0.5000"}
    assert {k: v for k, v in opted.items() if k != "training_schedule"} == plain


def _completed_workspace(tmp_path: Path, request: dict) -> Path:
    workspace = tmp_path / "teacher"
    (workspace / "output").mkdir(parents=True)
    (workspace / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (workspace / "output" / "teacher-manifest.json").write_text("{}", encoding="utf-8")
    return workspace


def test_a_completed_result_is_never_reused_for_another_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bodyrig import photoreal_teacher_authority as authority
    from bodyrig.photoreal_teacher_runner import PhotorealTeacherRunnerError, build_teacher_request

    helpers = _runner_helpers()
    teacher_input = helpers._teacher_input()
    upstream_config = helpers._config(["python", "bridge.py"])
    opted_config = helpers._config(["python", "bridge.py", "--densify-end-fraction", "0.5000"])
    validated: list[dict] = []
    monkeypatch.setattr(authority, "validate_teacher_result", lambda manifest, request, output_dir: validated.append(request) or {"ok": True})
    monkeypatch.setattr(authority, "validate_teacher_input_document", lambda value: value)
    input_path = tmp_path / "teacher-input.json"
    input_path.write_text(json.dumps(teacher_input), encoding="utf-8")

    for index, (trained_with, asked) in enumerate(((upstream_config, opted_config), (opted_config, upstream_config))):
        workspace = _completed_workspace(tmp_path / f"case-{index}", build_teacher_request(trained_with, teacher_input))
        monkeypatch.setattr(authority, "load_teacher_config", lambda _path, config=asked: config)
        with pytest.raises(PhotorealTeacherRunnerError, match="different densification schedule"):
            authority.validate_external_teacher_files_strict("config.json", input_path, workspace)

    workspace = _completed_workspace(tmp_path / "same", build_teacher_request(opted_config, teacher_input))
    monkeypatch.setattr(authority, "load_teacher_config", lambda _path: opted_config)
    assert authority.validate_external_teacher_files_strict("config.json", input_path, workspace) == {"ok": True}


def test_a_resume_with_another_schedule_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import bodyrig.photoreal_teacher_runner as teacher_runner

    helpers = _runner_helpers()
    teacher_input = helpers._teacher_input()
    workspace = tmp_path / "resume"
    (workspace / "output").mkdir(parents=True)
    started = teacher_runner.build_teacher_request(helpers._config(["python", "bridge.py"]), teacher_input)
    (workspace / "request.json").write_text(json.dumps(started, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(teacher_runner, "_invoke_teacher_adapter", lambda *a, **k: pytest.fail("never invoked"))
    with pytest.raises(teacher_runner.PhotorealTeacherRunnerError, match="resume request differs"):
        teacher_runner.resume_external_teacher(
            helpers._config(["python", "bridge.py", "--densify-end-fraction", "0.5000"]), teacher_input, workspace=workspace
        )


def test_the_adapter_refuses_a_request_that_disagrees_with_its_argument() -> None:
    adapter = _load_adapter()
    adapter._check_request_schedule({}, None)
    adapter._check_request_schedule({"training_schedule": {"densify_end_fraction": "0.5000"}}, "0.5000")
    for request, fraction in (({}, "0.5000"), ({"training_schedule": {"densify_end_fraction": "0.5000"}}, None),
                              ({"training_schedule": {"densify_end_fraction": "0.5000"}}, "0.6000")):
        with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="disagree on the densification schedule"):
            adapter._check_request_schedule(request, fraction)
    for malformed in ("0.5", {"densify_end_fraction": "0.5000", "x": 1}):
        with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="malformed"):
            adapter._check_request_schedule({"training_schedule": malformed}, "0.5000")


def test_a_malformed_stored_schedule_is_a_controlled_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # ChatGPT #1407 6764422676: a truthy non-mapping schedule must not escape as AttributeError.
    from bodyrig import photoreal_teacher_authority as authority
    from bodyrig.photoreal_teacher_runner import PhotorealTeacherRunnerError, build_teacher_request

    helpers = _runner_helpers()
    teacher_input = helpers._teacher_input()
    config = helpers._config(["python", "bridge.py", "--densify-end-fraction", "0.5000"])
    monkeypatch.setattr(authority, "validate_teacher_result", lambda manifest, request, output_dir: {"ok": True})
    monkeypatch.setattr(authority, "validate_teacher_input_document", lambda value: value)
    monkeypatch.setattr(authority, "load_teacher_config", lambda _path: config)
    input_path = tmp_path / "teacher-input.json"
    input_path.write_text(json.dumps(teacher_input), encoding="utf-8")
    good = build_teacher_request(config, teacher_input)
    for index, bad in enumerate((["0.5000"], "0.5000", {"densify_end_fraction": 0.5}, {"densify_end_fraction": "x"},
                                 {"densify_end_fraction": "0.5000", "extra": 1})):
        workspace = _completed_workspace(tmp_path / f"bad-{index}", {**good, "training_schedule": bad})
        with pytest.raises(PhotorealTeacherRunnerError, match="malformed|must be in"):
            authority.validate_external_teacher_files_strict("config.json", input_path, workspace)


def test_equal_fractions_in_another_spelling_are_the_same_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from bodyrig import photoreal_teacher_authority as authority
    from bodyrig.photoreal_teacher_runner import build_teacher_request, canonical_schedule_fraction

    assert canonical_schedule_fraction("0.5", label="x") == canonical_schedule_fraction("0.50000", label="x") == "0.5000"
    helpers = _runner_helpers()
    teacher_input = helpers._teacher_input()
    noncanonical = helpers._config(["python", "bridge.py", "--densify-end-fraction", "0.5"])
    assert build_teacher_request(noncanonical, teacher_input)["training_schedule"] == {"densify_end_fraction": "0.5000"}
    monkeypatch.setattr(authority, "validate_teacher_result", lambda manifest, request, output_dir: {"ok": True})
    monkeypatch.setattr(authority, "validate_teacher_input_document", lambda value: value)
    monkeypatch.setattr(authority, "load_teacher_config", lambda _path: noncanonical)
    input_path = tmp_path / "teacher-input.json"
    input_path.write_text(json.dumps(teacher_input), encoding="utf-8")
    stored = {**build_teacher_request(noncanonical, teacher_input), "training_schedule": {"densify_end_fraction": "0.50"}}
    workspace = _completed_workspace(tmp_path / "same", stored)
    assert authority.validate_external_teacher_files_strict("config.json", input_path, workspace) == {"ok": True}
