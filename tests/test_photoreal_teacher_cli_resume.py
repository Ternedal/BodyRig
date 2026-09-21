from __future__ import annotations

from pathlib import Path

import bodyrig.photoreal_teacher_cli as teacher_cli


def _result() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-teacher-manifest",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "adapter": "exavatar-benchmark",
        "adapter_revision": "a" * 64,
        "upstream_repository": "https://github.com/mks0601/ExAvatar_RELEASE",
        "upstream_commit": "b" * 40,
        "training_complete": True,
        "artifacts": [{"relative_path": "teacher.bin"}],
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "production_activation": False,
    }


def test_reuse_existing_routes_incomplete_workspace_to_resume(tmp_path: Path, monkeypatch, capsys) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "output").mkdir(parents=True)
    calls: list[str] = []

    monkeypatch.setattr(
        teacher_cli,
        "resume_external_teacher_files_strict",
        lambda *_args: calls.append("resume") or _result(),
    )
    monkeypatch.setattr(
        teacher_cli,
        "validate_external_teacher_files_strict",
        lambda *_args: calls.append("validate") or _result(),
    )
    monkeypatch.setattr(
        teacher_cli,
        "run_external_teacher_files_strict",
        lambda *_args: calls.append("run") or _result(),
    )

    code = teacher_cli.main(
        [
            "--config",
            str(tmp_path / "config.json"),
            "--teacher-input",
            str(tmp_path / "teacher-input.json"),
            "--workspace",
            str(workspace),
            "--reuse-existing",
        ]
    )

    assert code == 0
    assert calls == ["resume"]
    assert '"training_complete":true' in capsys.readouterr().out


def test_reuse_existing_routes_completed_workspace_to_strict_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    output = workspace / "output"
    output.mkdir(parents=True)
    (output / "teacher-manifest.json").write_text("{}\n", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(
        teacher_cli,
        "resume_external_teacher_files_strict",
        lambda *_args: calls.append("resume") or _result(),
    )
    monkeypatch.setattr(
        teacher_cli,
        "validate_external_teacher_files_strict",
        lambda *_args: calls.append("validate") or _result(),
    )
    monkeypatch.setattr(
        teacher_cli,
        "run_external_teacher_files_strict",
        lambda *_args: calls.append("run") or _result(),
    )

    code = teacher_cli.main(
        [
            "--config",
            str(tmp_path / "config.json"),
            "--teacher-input",
            str(tmp_path / "teacher-input.json"),
            "--workspace",
            str(workspace),
            "--reuse-existing",
        ]
    )

    assert code == 0
    assert calls == ["validate"]


def test_new_workspace_routes_to_fresh_run_even_with_reuse_flag(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "missing-workspace"
    calls: list[str] = []

    monkeypatch.setattr(
        teacher_cli,
        "resume_external_teacher_files_strict",
        lambda *_args: calls.append("resume") or _result(),
    )
    monkeypatch.setattr(
        teacher_cli,
        "validate_external_teacher_files_strict",
        lambda *_args: calls.append("validate") or _result(),
    )
    monkeypatch.setattr(
        teacher_cli,
        "run_external_teacher_files_strict",
        lambda *_args: calls.append("run") or _result(),
    )

    code = teacher_cli.main(
        [
            "--config",
            str(tmp_path / "config.json"),
            "--teacher-input",
            str(tmp_path / "teacher-input.json"),
            "--workspace",
            str(workspace),
            "--reuse-existing",
        ]
    )

    assert code == 0
    assert calls == ["run"]
