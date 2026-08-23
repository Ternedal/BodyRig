from __future__ import annotations

import json
import subprocess

import bodyrig.sith_preflight as sith


def _probe(*, missing_asset: str | None = None, cuda: bool = True) -> dict:
    files = {name: True for name in sith.REQUIRED_CHECKPOINTS + sith.REQUIRED_SMPLX}
    if missing_asset is not None:
        files[missing_asset] = False
    return {
        "python": "3.10.14",
        "import_torch": True,
        "version_torch": "2.1.0+cu121",
        "import_torchvision": True,
        "version_torchvision": "0.16.0+cu121",
        "import_kaolin": True,
        "version_kaolin": "0.15.0",
        "import_numpy": True,
        "version_numpy": "1.24.1",
        "import_cv2": True,
        "import_PIL": True,
        "import_smplx": True,
        "import_diffusers": True,
        "import_transformers": True,
        "import_trimesh": True,
        "import_xatlas": True,
        "import_nvdiffrast": True,
        "cuda_available": cuda,
        "cuda_device": "Fixture CUDA GPU" if cuda else None,
        "files": files,
        "openpose_present": True,
    }


def _runner(
    *,
    head: str = sith.SITH_REVISION,
    missing_asset: str | None = None,
    cuda: bool = True,
    centralizer_blob: str = sith.SITH_CENTRALIZE_RGBA_BLOB,
):
    def run(*, wsl_exe: str, distribution: str, command):
        assert wsl_exe == "wsl.exe"
        assert distribution == "Ubuntu-22.04"
        command = list(command)
        if command[:4] == ["git", "-C", "/opt/sith", "rev-parse"]:
            return subprocess.CompletedProcess(command, 0, head + "\n", "")
        if command[:4] == ["git", "-C", "/opt/sith", "status"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:4] == ["git", "-C", "/opt/sith", "hash-object"]:
            target = command[-1]
            blobs = {
                "run.sh": sith.SITH_RUN_SH_BLOB,
                "requirements.txt": sith.SITH_REQUIREMENTS_BLOB,
                "tools/centralize_rgba.py": centralizer_blob,
            }
            if target not in blobs:
                raise AssertionError(f"unexpected SiTH blob target: {target}")
            return subprocess.CompletedProcess(command, 0, blobs[target] + "\n", "")
        if command[0] == "/opt/sith/.venv/bin/python":
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(_probe(missing_asset=missing_asset, cuda=cuda)),
                "",
            )
        raise AssertionError(f"unexpected WSL command: {command}")

    return run


def _run(monkeypatch, **runner_args):
    monkeypatch.setattr(sith, "_run_wsl", _runner(**runner_args))
    return sith.run_preflight(
        distribution="Ubuntu-22.04",
        repo="/opt/sith",
        python="/opt/sith/.venv/bin/python",
        openpose="/opt/openpose/openpose.bin",
    )


def test_sith_preflight_accepts_exact_pinned_environment(monkeypatch):
    result = _run(monkeypatch)
    assert result["ok"] is True
    assert result["revision"] == sith.SITH_REVISION
    assert result["tracked_clean"] is True
    assert result["environment"]["cuda_available"] is True
    assert result["blob_tools_centralize_rgba_py"] == sith.SITH_CENTRALIZE_RGBA_BLOB
    assert result["errors"] == []


def test_sith_preflight_rejects_revision_drift(monkeypatch):
    result = _run(monkeypatch, head="0" * 40)
    assert result["ok"] is False
    assert any("revision mismatch" in error for error in result["errors"])


def test_sith_preflight_rejects_centralizer_drift(monkeypatch):
    result = _run(monkeypatch, centralizer_blob="0" * 40)
    assert result["ok"] is False
    assert any("tools/centralize_rgba.py blob mismatch" in error for error in result["errors"])


def test_sith_preflight_rejects_missing_model_asset(monkeypatch):
    result = _run(monkeypatch, missing_asset="checkpoints/recon_model.pth")
    assert result["ok"] is False
    assert "SiTH required asset missing: checkpoints/recon_model.pth" in result["errors"]


def test_sith_preflight_rejects_no_cuda(monkeypatch):
    result = _run(monkeypatch, cuda=False)
    assert result["ok"] is False
    assert "SiTH CUDA is not available" in result["errors"]


def test_sith_preflight_requires_absolute_linux_paths():
    try:
        sith.run_preflight(
            distribution="Ubuntu-22.04",
            repo="relative/sith",
            python="/opt/sith/python",
            openpose="/opt/openpose/openpose.bin",
        )
    except sith.SithPreflightError as exc:
        assert "absolute Linux paths" in str(exc)
    else:
        raise AssertionError("relative SiTH path was accepted")
