from __future__ import annotations

import bodyrig.sith_status as status


def test_status_reports_missing_environment_without_running_preflight(monkeypatch):
    for name in status.ENVIRONMENT.values():
        monkeypatch.delenv(name, raising=False)
    called = []
    monkeypatch.setattr(status, "run_preflight", lambda **_: called.append("preflight"))

    result = status.collect_status()

    assert result["ready"] is False
    assert result["configured"] is False
    assert "BODYRIG_SITH_REPO" in result["missing_settings"]
    assert called == []


def test_status_ready_requires_preflight_and_exact_model_digest(monkeypatch):
    monkeypatch.setattr(
        status,
        "run_preflight",
        lambda **_: {
            "ok": True,
            "errors": [],
            "revision": "6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d",
            "environment": {"cuda_device": "RTX test"},
        },
    )
    monkeypatch.setattr(
        status,
        "digest_model_tree",
        lambda **_: {"sha256": "a" * 64, "file_count": 12, "byte_count": 12345},
    )

    result = status.collect_status(
        repo="/opt/sith",
        python="/opt/sith/.venv/bin/python",
        openpose="/opt/openpose/openpose.bin",
        diffusion_model="/opt/models/sith",
        diffusion_sha256="a" * 64,
    )

    assert result["ready"] is True
    assert result["preflight"]["cuda_device"] == "RTX test"
    assert result["diffusion_model"]["matches"] is True


def test_status_rejects_model_tree_drift(monkeypatch):
    monkeypatch.setattr(status, "run_preflight", lambda **_: {"ok": True, "errors": [], "revision": "x", "environment": {}})
    monkeypatch.setattr(
        status,
        "digest_model_tree",
        lambda **_: {"sha256": "b" * 64, "file_count": 2, "byte_count": 10},
    )

    result = status.collect_status(
        repo="/opt/sith",
        python="/opt/sith/.venv/bin/python",
        openpose="/opt/openpose/openpose.bin",
        diffusion_model="/opt/models/sith",
        diffusion_sha256="a" * 64,
    )

    assert result["ready"] is False
    assert result["diffusion_model"]["matches"] is False
    assert "SiTH diffusion model tree digest mismatch" in result["errors"]


def test_status_stops_on_preflight_errors_before_model_digest(monkeypatch):
    calls = []
    monkeypatch.setattr(
        status,
        "run_preflight",
        lambda **_: {"ok": False, "errors": ["missing OpenPose"], "revision": "x", "environment": {}},
    )
    monkeypatch.setattr(status, "digest_model_tree", lambda **_: calls.append("digest"))

    result = status.collect_status(
        repo="/opt/sith",
        python="/opt/sith/.venv/bin/python",
        openpose="/opt/openpose/openpose.bin",
        diffusion_model="/opt/models/sith",
        diffusion_sha256="a" * 64,
    )

    assert result["ready"] is False
    assert "missing OpenPose" in result["errors"]
    assert calls == []
