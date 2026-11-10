from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig import photoreal_stage_watch as watch

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_exavatar_teacher_adapter.py"


def _load_adapter():
    spec = importlib.util.spec_from_file_location("bodyrig_test_train_telemetry_adapter", ADAPTER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _loop(snippet: str) -> str:
    # The pinned train.py runs the snippet inside main(): for epoch: for itr:
    return "def main():\n    for epoch in range(1):\n        for itr in range(1):\n" + snippet


def test_telemetry_patch_applies_once_and_is_idempotent(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "train.py"
    path.write_text("before\n" + adapter.TRAIN_TELEMETRY_ORIGINAL + "after\n", encoding="utf-8")
    first = adapter._ensure_training_telemetry_patch(path)
    patched = path.read_text(encoding="utf-8")
    assert first["applied"] is True and first["before_sha256"] != first["after_sha256"]
    assert patched.count("BodyRig telemetry itr") == 1
    second = adapter._ensure_training_telemetry_patch(path)
    assert second["applied"] is False and path.read_text(encoding="utf-8") == patched
    assert second["after_sha256"] == first["after_sha256"]


def test_telemetry_patch_refuses_changed_or_ambiguous_markers(tmp_path: Path) -> None:
    adapter = _load_adapter()
    path = tmp_path / "train.py"
    path.write_text(adapter.TRAIN_TELEMETRY_ORIGINAL * 2, encoding="utf-8")
    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="telemetry markers"):
        adapter._ensure_training_telemetry_patch(path)
    path.write_text("trainer.logger.info(x)\n", encoding="utf-8")
    with pytest.raises(adapter.ExAvatarTeacherAdapterError, match="telemetry markers"):
        adapter._ensure_training_telemetry_patch(path)


def _run_snippet(adapter, *, cur_itr: int, cuda) -> list[str]:
    logged: list[str] = []
    mean = SimpleNamespace(shape=(123456, 3))
    trainer = SimpleNamespace(
        logger=SimpleNamespace(info=logged.append),
        model=SimpleNamespace(module=SimpleNamespace(scene_gaussian=SimpleNamespace(mean=mean))),
    )
    namespace = {
        "trainer": trainer,
        "screen": ["Epoch 0/5 itr 0/10:"],
        "cfg": SimpleNamespace(model_dir="/x"),
        "torch": SimpleNamespace(cuda=cuda),
        "cur_itr": cur_itr,
        "print": lambda *args: None,
    }
    exec(compile(textwrap.dedent(adapter.TRAIN_TELEMETRY_PATCHED), "train.py", "exec"), namespace)
    return logged


def test_the_patched_loop_compiles_in_its_train_py_context() -> None:
    adapter = _load_adapter()
    compile(_loop(adapter.TRAIN_TELEMETRY_PATCHED), "train.py", "exec")


def test_the_line_the_patch_writes_is_the_line_the_watcher_reads() -> None:
    adapter = _load_adapter()
    mib = 1048576
    cuda = SimpleNamespace(
        memory_allocated=lambda: 7000 * mib + 5,
        memory_reserved=lambda: 9000 * mib,
        max_memory_allocated=lambda: 11500 * mib,
    )
    logged = _run_snippet(adapter, cur_itr=100, cuda=cuda)
    assert logged[0] == "Epoch 0/5 itr 0/10:"
    progress = watch.StageProgress(
        stage="teacher-train", parser=watch.parse_exavatar_train_line, stall_seconds=60, started=0.0, started_wall=0.0
    )
    progress.feed(("\x1b[92m11-10 06:00:00\x1b[0m " + logged[1] + "\n").encode(), 1.0)
    snapshot = progress.snapshot(1.0, 1.0)
    assert snapshot["telemetry_itr"] == 100
    assert snapshot["scene_gaussians"] == 123456
    assert (snapshot["vram_allocated_mib"], snapshot["vram_reserved_mib"], snapshot["vram_peak_mib"]) == (7000, 9000, 11500)


def test_telemetry_runs_only_every_50_iterations_and_never_raises() -> None:
    adapter = _load_adapter()
    quiet = _run_snippet(adapter, cur_itr=51, cuda=SimpleNamespace())
    assert len(quiet) == 1, "no telemetry line between the 50-iteration marks"

    def broken():
        raise RuntimeError("no CUDA")

    logged = _run_snippet(adapter, cur_itr=150, cuda=SimpleNamespace(memory_allocated=broken))
    assert logged[1] == "BodyRig telemetry unavailable: RuntimeError"


def test_telemetry_reaches_the_timing_record(tmp_path: Path) -> None:
    progress = watch.StageProgress(
        stage="teacher-train", parser=watch.parse_exavatar_train_line, stall_seconds=60, started=0.0, started_wall=0.0
    )
    progress.feed(b"BodyRig telemetry itr 50: scene_gaussians 99 vram_allocated_mib 1 vram_reserved_mib 2 vram_peak_mib 3\n", 1.0)
    progress.state = "finished"
    path = tmp_path / "stage-timing.jsonl"
    assert watch.append_stage_timing(path, progress, log_name="train.log", now=2.0, wall_now=2.0)
    import json

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["scene_gaussians"] == 99 and record["vram_peak_mib"] == 3
