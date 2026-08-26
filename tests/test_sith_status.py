from __future__ import annotations

import bodyrig.sith_status as status


def _kwargs() -> dict:
    return {
        "repo": "/opt/sith",
        "python": "/opt/sith/.venv/bin/python",
        "openpose_repo": "/opt/openpose",
        "openpose": "/opt/openpose/build/examples/openpose/openpose.bin",
        "openpose_sha256": "b" * 64,
        "openpose_models_sha256": "c" * 64,
        "recon_checkpoint_sha256": "d" * 64,
        "smplerx_checkpoint_sha256": "e" * 64,
        "diffusion_model": "/opt/models/sith",
        "diffusion_sha256": "a" * 64,
    }


def _green_preflight(**_):
    return {
        "ok": True,
        "errors": [],
        "revision": "6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d",
        "environment": {"cuda_device": "RTX test"},
    }


def _green_file_digest(**kwargs):
    path = kwargs["path"]
    if path.endswith("/checkpoints/recon_model.pth"):
        return {"sha256": "d" * 64, "byte_count": 111}
    if path.endswith("/checkpoints/save_smplerx.pth"):
        return {"sha256": "e" * 64, "byte_count": 222}
    if path.endswith("/openpose.bin"):
        return {"sha256": "b" * 64, "byte_count": 2345}
    raise AssertionError(f"unexpected file digest path: {path}")


def test_status_reports_missing_environment_without_running_preflight(monkeypatch):
    for name in status.ENVIRONMENT.values():
        monkeypatch.delenv(name, raising=False)
    called = []
    monkeypatch.setattr(status, "run_preflight", lambda **_: called.append("preflight"))

    result = status.collect_status()

    assert result["ready"] is False
    assert result["configured"] is False
    assert "BODYRIG_SITH_REPO" in result["missing_settings"]
    assert "BODYRIG_SITH_OPENPOSE_SHA256" in result["missing_settings"]
    assert "BODYRIG_SITH_OPENPOSE_MODELS_SHA256" in result["missing_settings"]
    assert "BODYRIG_SITH_RECON_CHECKPOINT_SHA256" in result["missing_settings"]
    assert "BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256" in result["missing_settings"]
    assert called == []


def test_status_ready_requires_preflight_checkpoints_openpose_and_exact_model_digests(monkeypatch):
    monkeypatch.setattr(status, "run_preflight", _green_preflight)
    monkeypatch.setattr(status, "digest_wsl_file", _green_file_digest)
    monkeypatch.setattr(
        status,
        "digest_wsl_tree",
        lambda **_: {"sha256": "c" * 64, "file_count": 17, "byte_count": 4567},
    )
    monkeypatch.setattr(
        status,
        "digest_model_tree",
        lambda **_: {"sha256": "a" * 64, "file_count": 12, "byte_count": 12345},
    )

    result = status.collect_status(**_kwargs())

    assert result["version"] == 3
    assert result["ready"] is True
    assert result["preflight"]["cuda_device"] == "RTX test"
    assert result["checkpoints"]["recon_model"]["matches"] is True
    assert result["checkpoints"]["smplerx"]["matches"] is True
    assert result["openpose_binary"]["matches"] is True
    assert result["openpose_models"]["matches"] is True
    assert result["diffusion_model"]["matches"] is True


def test_status_rejects_checkpoint_drift_before_openpose_or_model_trees(monkeypatch):
    file_calls = []
    later_calls = []
    monkeypatch.setattr(status, "run_preflight", _green_preflight)

    def drifted_file(**kwargs):
        file_calls.append(kwargs["path"])
        if kwargs["path"].endswith("/checkpoints/recon_model.pth"):
            return {"sha256": "f" * 64, "byte_count": 111}
        return _green_file_digest(**kwargs)

    monkeypatch.setattr(status, "digest_wsl_file", drifted_file)
    monkeypatch.setattr(status, "digest_wsl_tree", lambda **_: later_calls.append("openpose-models"))
    monkeypatch.setattr(status, "digest_model_tree", lambda **_: later_calls.append("diffusion"))

    result = status.collect_status(**_kwargs())

    assert result["ready"] is False
    assert result["checkpoints"]["recon_model"]["matches"] is False
    assert "SiTH recon_model checkpoint digest mismatch" in result["errors"]
    assert result["openpose_binary"] is None
    assert file_calls == ["/opt/sith/checkpoints/recon_model.pth"]
    assert later_calls == []


def test_status_rejects_openpose_binary_drift_before_model_trees(monkeypatch):
    calls = []
    monkeypatch.setattr(status, "run_preflight", _green_preflight)

    def drifted_openpose(**kwargs):
        if kwargs["path"].endswith("/openpose.bin"):
            return {"sha256": "f" * 64, "byte_count": 2345}
        return _green_file_digest(**kwargs)

    monkeypatch.setattr(status, "digest_wsl_file", drifted_openpose)
    monkeypatch.setattr(status, "digest_wsl_tree", lambda **_: calls.append("openpose-models"))
    monkeypatch.setattr(status, "digest_model_tree", lambda **_: calls.append("diffusion"))

    result = status.collect_status(**_kwargs())

    assert result["ready"] is False
    assert result["checkpoints"]["recon_model"]["matches"] is True
    assert result["checkpoints"]["smplerx"]["matches"] is True
    assert result["openpose_binary"]["matches"] is False
    assert "OpenPose binary digest mismatch" in result["errors"]
    assert calls == []


def test_status_rejects_openpose_model_tree_drift_before_diffusion(monkeypatch):
    calls = []
    monkeypatch.setattr(status, "run_preflight", _green_preflight)
    monkeypatch.setattr(status, "digest_wsl_file", _green_file_digest)
    monkeypatch.setattr(
        status,
        "digest_wsl_tree",
        lambda **_: {"sha256": "f" * 64, "file_count": 17, "byte_count": 4567},
    )
    monkeypatch.setattr(status, "digest_model_tree", lambda **_: calls.append("diffusion"))

    result = status.collect_status(**_kwargs())

    assert result["ready"] is False
    assert result["openpose_models"]["matches"] is False
    assert "OpenPose model tree digest mismatch" in result["errors"]
    assert calls == []


def test_status_rejects_diffusion_model_tree_drift(monkeypatch):
    monkeypatch.setattr(status, "run_preflight", _green_preflight)
    monkeypatch.setattr(status, "digest_wsl_file", _green_file_digest)
    monkeypatch.setattr(status, "digest_wsl_tree", lambda **_: {"sha256": "c" * 64, "file_count": 17, "byte_count": 4567})
    monkeypatch.setattr(
        status,
        "digest_model_tree",
        lambda **_: {"sha256": "f" * 64, "file_count": 2, "byte_count": 10},
    )

    result = status.collect_status(**_kwargs())

    assert result["ready"] is False
    assert result["diffusion_model"]["matches"] is False
    assert "SiTH diffusion model tree digest mismatch" in result["errors"]


def test_status_stops_on_preflight_errors_before_any_digest(monkeypatch):
    calls = []
    monkeypatch.setattr(
        status,
        "run_preflight",
        lambda **_: {"ok": False, "errors": ["missing OpenPose"], "revision": "x", "environment": {}},
    )
    monkeypatch.setattr(status, "digest_wsl_file", lambda **_: calls.append("file"))
    monkeypatch.setattr(status, "digest_wsl_tree", lambda **_: calls.append("models"))
    monkeypatch.setattr(status, "digest_model_tree", lambda **_: calls.append("diffusion"))

    result = status.collect_status(**_kwargs())

    assert result["ready"] is False
    assert "missing OpenPose" in result["errors"]
    assert calls == []
