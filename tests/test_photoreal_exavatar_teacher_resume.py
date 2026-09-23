from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_exavatar_teacher_adapter.py"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "bodyrig_test_exavatar_teacher_resume_adapter",
        ADAPTER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_snapshot_epochs_accepts_only_exact_nonempty_pinned_epochs(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "snapshot_0.pth").write_bytes(b"epoch-0")
    (model_dir / "snapshot_2.pth").write_bytes(b"epoch-2")

    assert adapter._snapshot_epochs(model_dir) == [0, 2]


def test_snapshot_epochs_returns_empty_for_missing_model_dir(tmp_path: Path) -> None:
    adapter = _load_adapter()

    assert adapter._snapshot_epochs(tmp_path / "missing") == []


@pytest.mark.parametrize(
    ("name", "payload", "match"),
    [
        ("notes.txt", b"x", "unexpected file"),
        ("snapshot_x.pth", b"x", "invalid ExAvatar snapshot name"),
        ("snapshot_5.pth", b"x", "unexpected ExAvatar snapshot epoch"),
        ("snapshot_1.pth", b"", "empty ExAvatar snapshot"),
    ],
)
def test_snapshot_epochs_fails_closed_on_ambiguous_model_state(
    tmp_path: Path,
    name: str,
    payload: bytes,
    match: str,
) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / name).write_bytes(payload)

    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match=match):
        adapter._snapshot_epochs(model_dir)


def test_training_resume_plan_starts_fresh_without_checkpoint(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    neutral_dir = tmp_path / "neutral"

    mode, argv, log_name = adapter._training_resume_plan(
        model_dir,
        neutral_dir,
        subject="subject-42",
    )

    assert mode == "fresh"
    assert argv == [sys.executable, "train.py", "--subject_id", "subject-42"]
    assert log_name == "train.log"


def test_training_resume_plan_uses_upstream_continue_from_partial_checkpoint(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "snapshot_2.pth").write_bytes(b"checkpoint")
    neutral_dir = tmp_path / "neutral"

    mode, argv, log_name = adapter._training_resume_plan(
        model_dir,
        neutral_dir,
        subject="subject-42",
    )

    assert mode == "resume-from-checkpoint"
    assert argv == [
        sys.executable,
        "train.py",
        "--subject_id",
        "subject-42",
        "--continue",
    ]
    assert log_name == "train-resume.log"


def test_training_resume_plan_skips_retraining_when_final_checkpoint_exists(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / f"snapshot_{adapter.FINAL_EPOCH}.pth").write_bytes(b"final-checkpoint")
    neutral_dir = tmp_path / "neutral"
    neutral_dir.mkdir()

    mode, argv, log_name = adapter._training_resume_plan(
        model_dir,
        neutral_dir,
        subject="subject-42",
    )

    assert mode == "reuse-final-checkpoint"
    assert argv is None
    assert log_name is None


def test_training_resume_plan_rejects_neutral_output_before_final_checkpoint(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "snapshot_1.pth").write_bytes(b"checkpoint")
    neutral_dir = tmp_path / "neutral"
    neutral_dir.mkdir()

    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="before final checkpoint"):
        adapter._training_resume_plan(
            model_dir,
            neutral_dir,
            subject="subject-42",
        )


def test_training_resume_plan_rejects_neutral_output_without_checkpoint(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    neutral_dir = tmp_path / "neutral"
    neutral_dir.mkdir()

    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="without any training checkpoint"):
        adapter._training_resume_plan(
            model_dir,
            neutral_dir,
            subject="subject-42",
        )


def test_training_resume_plan_removes_interrupted_atomic_checkpoint_temp(tmp_path: Path) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "snapshot_1.pth").write_bytes(b"checkpoint")
    temp = model_dir / "snapshot_2.pth.bodyrig-tmp"
    temp.write_bytes(b"partial")
    neutral_dir = tmp_path / "neutral"

    mode, argv, log_name = adapter._training_resume_plan(
        model_dir,
        neutral_dir,
        subject="subject-42",
    )

    assert temp.exists() is False
    assert mode == "resume-from-checkpoint"
    assert argv == [
        sys.executable,
        "train.py",
        "--subject_id",
        "subject-42",
        "--continue",
    ]
    assert log_name == "train-resume.log"


@pytest.mark.parametrize(
    "name",
    [
        "snapshot_x.pth.bodyrig-tmp",
        "snapshot_5.pth.bodyrig-tmp",
    ],
)
def test_checkpoint_temp_cleanup_fails_closed_on_invalid_temp_name(
    tmp_path: Path,
    name: str,
) -> None:
    adapter = _load_adapter()
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / name).write_bytes(b"partial")

    with pytest.raises(adapter.ExAvatarTeacherAdapterError):
        adapter._cleanup_atomic_checkpoint_temps(model_dir)


def _complete_neutral_render_set(adapter, neutral_dir: Path) -> None:
    neutral_dir.mkdir(parents=True)
    for index in range(adapter.NEUTRAL_RENDER_COUNT):
        (neutral_dir / f"{index}.png").write_bytes(f"render-{index}".encode("utf-8"))
    (neutral_dir / "rgb.txt").write_text("rgb\n", encoding="utf-8")


def test_prepare_neutral_render_reuses_complete_render_set(tmp_path: Path) -> None:
    adapter = _load_adapter()
    neutral_dir = tmp_path / "neutral"
    _complete_neutral_render_set(adapter, neutral_dir)

    assert adapter._prepare_neutral_render(neutral_dir) is False
    assert (neutral_dir / "0.png").is_file()
    assert (neutral_dir / "rgb.txt").is_file()


def test_prepare_neutral_render_discards_only_partial_derived_output(tmp_path: Path) -> None:
    adapter = _load_adapter()
    neutral_dir = tmp_path / "neutral"
    neutral_dir.mkdir()
    (neutral_dir / "0.png").write_bytes(b"partial")

    assert adapter._prepare_neutral_render(neutral_dir) is True
    assert neutral_dir.exists() is False


def test_prepare_output_stage_cleans_interrupted_stage_without_touching_output(tmp_path: Path) -> None:
    adapter = _load_adapter()
    output = tmp_path / "output"
    output.mkdir()
    stage = tmp_path / ".output.bodyrig-stage"
    stage.mkdir()
    (stage / "partial.txt").write_text("partial", encoding="utf-8")

    observed = adapter._prepare_output_stage(output)

    assert observed == stage
    assert observed.is_dir()
    assert list(observed.iterdir()) == []
    assert output.is_dir()
    assert list(output.iterdir()) == []


def test_publish_output_stage_moves_complete_tree_to_missing_target(tmp_path: Path) -> None:
    adapter = _load_adapter()
    output = tmp_path / "output"
    output.mkdir()
    stage = tmp_path / ".output.bodyrig-stage"
    stage.mkdir()
    (stage / "teacher-manifest.json").write_text("{}\n", encoding="utf-8")
    artifact = stage / "checkpoint" / "snapshot_4.pth"
    artifact.parent.mkdir()
    artifact.write_bytes(b"checkpoint")

    adapter._publish_output_stage(stage, output)

    assert stage.exists() is False
    assert (output / "teacher-manifest.json").is_file()
    assert (output / "checkpoint" / "snapshot_4.pth").read_bytes() == b"checkpoint"
