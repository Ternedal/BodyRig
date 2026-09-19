from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bodyrig import photoreal_reference_vision_preflight as preflight


MODEL_SET_SHA = "c" * 64


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    adapter = tmp_path / "adapter.py"
    probe = tmp_path / "probe.py"
    model_root = tmp_path / "models"
    adapter.write_text("# adapter\n", encoding="utf-8")
    probe.write_text("# probe\n", encoding="utf-8")
    model_root.mkdir()
    revision = hashlib.sha256(adapter.read_bytes()).hexdigest()
    return adapter, probe, model_root, revision


def _probe_result(revision: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-reference-vision-probe",
        "version": 1,
        "adapter_revision": revision,
        "model_set_sha256": MODEL_SET_SHA,
        "device": "cuda:0",
        "identity_embedding_dimension": 512,
        "face_inference_executed": True,
        "pose_inference_executed": True,
        "face_execution_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
        "synthetic_face_count": 0,
        "synthetic_pose_count": 0,
        "synthetic_frame_sha256": "a" * 64,
        "synthetic_perceptual_hash": "0123456789abcdef",
        "source_media_accessed": False,
        "identity_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    value.update(overrides)
    return value


def _patch_transport(monkeypatch: pytest.MonkeyPatch, result: dict[str, object], calls: list[tuple[list[str], dict[str, object]]]) -> None:
    monkeypatch.setattr(preflight, "build_model_set", lambda _root: {"model_set_sha256": MODEL_SET_SHA})
    monkeypatch.setattr(
        preflight,
        "make_wsl_path_converter",
        lambda _exe, _distribution: (lambda path: f"/wsl/{Path(path).name}"),
    )

    def fake_run(invocation, **kwargs):
        calls.append((list(invocation), dict(kwargs)))
        return SimpleNamespace(returncode=0, stdout=json.dumps(result) + "\n", stderr="")

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)


def test_preflight_executes_pinned_probe_without_shell_or_source_media(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter, probe, model_root, revision = _fixture(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []
    _patch_transport(monkeypatch, _probe_result(revision), calls)

    result = preflight.run_reference_vision_preflight(
        adapter_path=adapter,
        probe_path=probe,
        model_root=model_root,
        distribution="Ubuntu-22.04",
        linux_python="/opt/bodyrig-photoreal/bin/python",
        device="cuda:0",
    )

    assert result["adapter_revision"] == revision
    assert result["model_set_sha256"] == MODEL_SET_SHA
    assert result["source_media_accessed"] is False
    assert result["identity_authority"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    assert len(calls) == 1
    invocation, kwargs = calls[0]
    assert invocation[:4] == ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
    assert "/wsl/adapter.py" in invocation
    assert "/wsl/probe.py" in invocation
    assert "/wsl/models" in invocation
    assert kwargs["shell"] is False
    assert kwargs["stdin"] is preflight.subprocess.DEVNULL


def test_preflight_rejects_probe_provenance_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter, probe, model_root, revision = _fixture(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []
    _patch_transport(monkeypatch, _probe_result(revision, model_set_sha256="d" * 64), calls)

    with pytest.raises(preflight.PhotorealReferenceVisionPreflightError, match="provenance mismatch"):
        preflight.run_reference_vision_preflight(
            adapter_path=adapter,
            probe_path=probe,
            model_root=model_root,
            distribution="Ubuntu-22.04",
            linux_python="/opt/bodyrig-photoreal/bin/python",
            device="cuda:0",
        )


def test_preflight_rejects_any_authority_claim_from_probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter, probe, model_root, revision = _fixture(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []
    _patch_transport(monkeypatch, _probe_result(revision, identity_authority=True), calls)

    with pytest.raises(preflight.PhotorealReferenceVisionPreflightError, match="source/identity authority"):
        preflight.run_reference_vision_preflight(
            adapter_path=adapter,
            probe_path=probe,
            model_root=model_root,
            distribution="Ubuntu-22.04",
            linux_python="/opt/bodyrig-photoreal/bin/python",
            device="cuda:0",
        )


def test_preflight_requires_both_inference_stacks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter, probe, model_root, revision = _fixture(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []
    _patch_transport(monkeypatch, _probe_result(revision, pose_inference_executed=False), calls)

    with pytest.raises(preflight.PhotorealReferenceVisionPreflightError, match="both inference stacks"):
        preflight.run_reference_vision_preflight(
            adapter_path=adapter,
            probe_path=probe,
            model_root=model_root,
            distribution="Ubuntu-22.04",
            linux_python="/opt/bodyrig-photoreal/bin/python",
            device="cuda:0",
        )
