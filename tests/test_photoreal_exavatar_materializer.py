from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig import photoreal_exavatar_materializer as materializer
from bodyrig.photoreal_teacher_benchmark_plan import build_teacher_benchmark_plan


def _teacher_input() -> dict[str, object]:
    key = "scene:scan:E:/scan.mp4"
    observations = [
        {
            "source_key": key,
            "group_id": "scene:scan",
            "split": "train",
            "frame_sha256": "1" * 64,
            "timestamp_seconds": 1.25,
            "eye": "mono",
            "view_bin": "front",
            "coverage": ["face-front", "full-body-front"],
        },
        {
            "source_key": key,
            "group_id": "scene:scan",
            "split": "train",
            "frame_sha256": "2" * 64,
            "timestamp_seconds": 2.5,
            "eye": "mono",
            "view_bin": "three-quarter-left",
            "coverage": ["face-three-quarter", "full-body-three-quarter"],
        },
    ]
    return {
        "format": "bodyrig-photoreal-teacher-input",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "d" * 64,
        "training_sources": [
            {
                "source_key": key,
                "group_id": "scene:scan",
                "kind": "video",
                "resolved_path": r"\\stash\VR_E\scan.mp4",
                "size_bytes": 1000,
                "sha256": "a" * 64,
                "information_score": 100.0,
                "width": 3840,
                "height": 2160,
                "projection": "flat",
                "stereo_layout": "mono",
            }
        ],
        "training_observations": observations,
        "training_source_count": 1,
        "training_observation_count": 2,
        "held_out_evaluation_sources": [{"source_key": "scene:e:E:/secret.mp4"}],
        "held_out_evaluation_observations": [{"frame_sha256": "e" * 64}],
        "held_out_view_coverage_missing": [],
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _write_fake_dataset(dataset: Path, plan: dict[str, object], *, wrong_frame_sha: bool = False) -> None:
    dataset.mkdir(exist_ok=True)
    frames_dir = dataset / "frames"
    frames_dir.mkdir()
    mappings = []
    for index, observation in enumerate(plan["selected_observations"]):
        frame = frames_dir / f"{index}.png"
        frame.write_bytes(f"png-{index}".encode())
        staged_sha = hashlib.sha256(frame.read_bytes()).hexdigest()
        mappings.append(
            {
                "exavatar_frame_index": index,
                "source_key": plan["selected_source_key"],
                "source_frame_sha256": ("f" * 64 if wrong_frame_sha and index == 0 else observation["frame_sha256"]),
                "timestamp_seconds": observation["timestamp_seconds"],
                "eye": "mono",
                "relative_path": f"frames/{index}.png",
                "staged_png_sha256": staged_sha,
                "width": 3840,
                "height": 2160,
            }
        )
    indices = "".join(f"{index}\n" for index in range(len(mappings)))
    (dataset / "frame_list_all.txt").write_text(indices, encoding="utf-8")
    (dataset / "frame_list_train.txt").write_text(indices, encoding="utf-8")
    (dataset / "frame_list_test.txt").write_text("", encoding="utf-8")
    source_map = {
        "format": "bodyrig-photoreal-exavatar-source-map",
        "version": 1,
        "benchmark_plan_sha256": plan["benchmark_plan_sha256"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "source_key": plan["selected_source_key"],
        "source_sha256": plan["selected_source_sha256"],
        "frames": mappings,
        "held_out_evaluation_disclosed": False,
        "build_only": True,
        "production_activation": False,
    }
    (dataset / "bodyrig-source-map.json").write_text(json.dumps(source_map), encoding="utf-8")
    receipt = {
        "format": "bodyrig-photoreal-exavatar-materialization-receipt",
        "version": 1,
        "benchmark_plan_sha256": plan["benchmark_plan_sha256"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "upstream_commit": plan["upstream_commit"],
        "source_key": plan["selected_source_key"],
        "source_sha256": plan["selected_source_sha256"],
        "frame_count": len(mappings),
        "frames": mappings,
        "frame_lists_are_training_only": True,
        "bodyrig_held_out_evaluation_is_external": True,
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "exact_p0_frame_hashes_reproduced": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }
    (dataset / "materialization-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


def _patch_transport(monkeypatch: pytest.MonkeyPatch, workspace: Path, plan: dict[str, object], *, wrong_frame_sha: bool = False) -> list[list[str]]:
    calls: list[list[str]] = []

    def converter(path: str) -> str:
        return "/bodyrig/" + Path(path.replace("\\", "/")).name

    monkeypatch.setattr(materializer, "make_wsl_path_converter", lambda _exe, _distribution: converter)

    def fake_run(invocation, **kwargs):
        calls.append(list(invocation))
        assert kwargs["shell"] is False
        assert kwargs["stdin"] is materializer.subprocess.DEVNULL
        _write_fake_dataset(workspace / "dataset", plan, wrong_frame_sha=wrong_frame_sha)
        return SimpleNamespace(returncode=0, stdout="materialized\n")

    monkeypatch.setattr(materializer.subprocess, "run", fake_run)
    return calls


def test_materializer_accepts_exact_authorized_frame_universe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plan = build_teacher_benchmark_plan(_teacher_input())
    workspace = tmp_path / "workspace"
    tool = tmp_path / "materialize.py"
    tool.write_text("# tool\n", encoding="utf-8")
    calls = _patch_transport(monkeypatch, workspace, plan)

    result = materializer.materialize_exavatar_benchmark(
        plan,
        workspace=workspace,
        tool_path=tool,
        distribution="Ubuntu-22.04",
        linux_python="/opt/bodyrig-photoreal/bin/python",
    )

    assert result["frame_count"] == 2
    assert result["exact_p0_frame_hashes_reproduced"] is True
    assert result["held_out_evaluation_disclosed"] is False
    assert result["original_video_copied"] is False
    assert (workspace / "dataset" / "frame_list_test.txt").read_text(encoding="utf-8") == ""
    assert len(calls) == 1
    assert calls[0][:4] == ["wsl.exe", "-d", "Ubuntu-22.04", "--"]


def test_materializer_rejects_tampered_benchmark_plan_before_transport(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plan = build_teacher_benchmark_plan(_teacher_input())
    plan["selected_source_sha256"] = "f" * 64
    tool = tmp_path / "materialize.py"
    tool.write_text("# tool\n", encoding="utf-8")

    with pytest.raises(materializer.PhotorealExAvatarMaterializerError, match="digest mismatch"):
        materializer.materialize_exavatar_benchmark(
            plan,
            workspace=tmp_path / "workspace",
            tool_path=tool,
        )


def test_materializer_rejects_staged_frame_that_does_not_match_p0_observation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plan = build_teacher_benchmark_plan(_teacher_input())
    workspace = tmp_path / "workspace"
    tool = tmp_path / "materialize.py"
    tool.write_text("# tool\n", encoding="utf-8")
    _patch_transport(monkeypatch, workspace, plan, wrong_frame_sha=True)

    with pytest.raises(materializer.PhotorealExAvatarMaterializerError, match="source frame SHA mismatch"):
        materializer.materialize_exavatar_benchmark(
            plan,
            workspace=workspace,
            tool_path=tool,
        )


def test_materializer_request_contains_no_held_out_evaluation_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plan = build_teacher_benchmark_plan(_teacher_input())
    workspace = tmp_path / "workspace"
    tool = tmp_path / "materialize.py"
    tool.write_text("# tool\n", encoding="utf-8")
    captured_request: dict[str, object] = {}

    def converter(path: str) -> str:
        return "/bodyrig/" + Path(path.replace("\\", "/")).name

    monkeypatch.setattr(materializer, "make_wsl_path_converter", lambda _exe, _distribution: converter)

    def fake_run(invocation, **_kwargs):
        request_paths = list((Path(materializer.tempfile.gettempdir())).glob("bodyrig-exavatar-materialize-*/request.json"))
        assert request_paths
        captured_request.update(json.loads(request_paths[-1].read_text(encoding="utf-8")))
        _write_fake_dataset(workspace / "dataset", plan)
        return SimpleNamespace(returncode=0, stdout="ok\n")

    monkeypatch.setattr(materializer.subprocess, "run", fake_run)
    materializer.materialize_exavatar_benchmark(plan, workspace=workspace, tool_path=tool)

    encoded = json.dumps(captured_request, sort_keys=True)
    assert "secret.mp4" not in encoded
    assert "held_out_evaluation_sources" not in encoded
    assert captured_request["held_out_evaluation_disclosed"] is False
