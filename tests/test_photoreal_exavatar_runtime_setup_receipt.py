from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_runtime_setup_receipt as receipt


LINUX_RUNTIME_ONLY = pytest.mark.skipif(
    os.name == "nt",
    reason="ExAvatar runtime receipt paths are authoritative Linux venv paths",
)


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "bodyrig-exavatar"
    python = root / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python-placeholder")

    site = root / "lib" / "python3.10" / "site-packages"
    chumpy = site / "chumpy" / "__init__.py"
    torchgeometry = site / "torchgeometry" / "core" / "conversions.py"
    chumpy.parent.mkdir(parents=True)
    torchgeometry.parent.mkdir(parents=True)
    chumpy.write_bytes(b"bodyrig-patched-chumpy")
    torchgeometry.write_bytes(b"bodyrig-patched-torchgeometry")

    observed = {
        "torch": receipt.EXPECTED_REQUESTED_VERSIONS["torch"],
        "torchvision": receipt.EXPECTED_REQUESTED_VERSIONS["torchvision"],
        "torch_cuda": receipt.EXPECTED_CUDA_VERSION,
        "numpy": receipt.EXPECTED_REQUESTED_VERSIONS["numpy"],
        "scipy": receipt.EXPECTED_REQUESTED_VERSIONS["scipy"],
        "opencv": receipt.EXPECTED_REQUESTED_VERSIONS["opencv_python"],
        "smplx": receipt.EXPECTED_REQUESTED_VERSIONS["smplx"],
        "lpips": receipt.EXPECTED_REQUESTED_VERSIONS["lpips"],
        "chumpy": receipt.EXPECTED_REQUESTED_VERSIONS["chumpy"],
        "mmcv": receipt.EXPECTED_REQUESTED_VERSIONS["mmcv"],
        "mmengine": receipt.EXPECTED_REQUESTED_VERSIONS["mmengine"],
        "mmdet": receipt.EXPECTED_REQUESTED_VERSIONS["mmdet"],
        "mmpose": receipt.EXPECTED_REQUESTED_VERSIONS["mmpose"],
        "cuda_smoke": True,
        "chumpy_smoke": True,
        "torchgeometry_smoke": True,
    }
    value: dict[str, object] = {
        "format": receipt.FORMAT,
        "version": receipt.VERSION,
        "distribution": "Ubuntu-22.04",
        "linux_python": str(python.absolute()),
        "pytorch3d_commit": receipt.PYTORCH3D_COMMIT,
        "expected_cuda_version": receipt.EXPECTED_CUDA_VERSION,
        "requested_versions": dict(receipt.EXPECTED_REQUESTED_VERSIONS),
        "chumpy_patch": {
            "path": str(chumpy.absolute()),
            "before_sha256": "a" * 64,
            "sha256": _sha(chumpy),
            "patch": receipt.CHUMPY_PATCH,
        },
        "torchgeometry_patch": {
            "path": str(torchgeometry.absolute()),
            "sha256": _sha(torchgeometry),
            "patch": receipt.TORCHGEOMETRY_PATCH,
        },
        "observed": observed,
        "nvcc": [f"Cuda compilation tools, release {receipt.EXPECTED_CUDA_VERSION}, V12.4.131"],
        "nvidia_smi": ["NVIDIA GeForce RTX 3060, driver, 12288 MiB"],
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }
    value["setup_sha256"] = _digest(value, "setup_sha256")
    (root / "bodyrig-exavatar-runtime-setup.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return python, chumpy, torchgeometry


def _pin_live_pytorch3d(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        receipt,
        "_installed_pytorch3d_provenance",
        lambda: {"url": receipt.PYTORCH3D_REPOSITORY, "commit": receipt.PYTORCH3D_COMMIT},
    )


@LINUX_RUNTIME_ONLY
def test_runtime_setup_receipt_accepts_exact_pinned_provenance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, chumpy, torchgeometry = _runtime(tmp_path)
    _pin_live_pytorch3d(monkeypatch)
    result = receipt.validate_runtime_setup_receipt(linux_python=python)

    assert result["pytorch3d_commit"] == receipt.PYTORCH3D_COMMIT
    assert result["expected_cuda_version"] == receipt.EXPECTED_CUDA_VERSION
    assert result["requested_versions"]["chumpy"] == "0.70"
    assert result["chumpy_patch"]["patch"] == receipt.CHUMPY_PATCH
    assert result["torchgeometry_patch"]["patch"] == receipt.TORCHGEOMETRY_PATCH
    assert result["live_patch_bytes_verified"] is True
    assert result["chumpy_live_path"] == str(chumpy.resolve())
    assert result["torchgeometry_live_path"] == str(torchgeometry.resolve())
    assert result["pytorch3d_live_provenance"]["commit"] == receipt.PYTORCH3D_COMMIT
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_runtime_setup_receipt_rejects_changed_version_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_pytorch3d(monkeypatch)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["requested_versions"]["chumpy"] = "0.71"
    value["setup_sha256"] = _digest(value, "setup_sha256")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="requested-version set mismatch"):
        receipt.validate_runtime_setup_receipt(linux_python=python)


@LINUX_RUNTIME_ONLY
def test_runtime_setup_receipt_rejects_observed_version_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_pytorch3d(monkeypatch)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["observed"]["mmpose"] = "9.9.9"
    value["setup_sha256"] = _digest(value, "setup_sha256")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="observed version mismatch for mmpose"):
        receipt.validate_runtime_setup_receipt(linux_python=python)


@LINUX_RUNTIME_ONLY
def test_runtime_setup_receipt_rejects_cuda_compiler_runtime_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_pytorch3d(monkeypatch)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["nvcc"] = ["Cuda compilation tools, release 12.5, V12.5.82"]
    value["setup_sha256"] = _digest(value, "setup_sha256")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="nvcc/Torch CUDA parity"):
        receipt.validate_runtime_setup_receipt(linux_python=python)


def test_runtime_setup_receipt_rejects_wrong_patch_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_pytorch3d(monkeypatch)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["chumpy_patch"]["patch"] = "unknown"
    value["setup_sha256"] = _digest(value, "setup_sha256")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="Chumpy patch identity mismatch"):
        receipt.validate_runtime_setup_receipt(linux_python=python)


@LINUX_RUNTIME_ONLY
def test_runtime_setup_receipt_rejects_live_patch_byte_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_pytorch3d(monkeypatch)
    chumpy.write_bytes(b"changed-after-setup")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="Chumpy patched bytes changed after setup"):
        receipt.validate_runtime_setup_receipt(linux_python=python)


def test_runtime_setup_receipt_rejects_digest_tampering(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_pytorch3d(monkeypatch)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["observed"]["chumpy"] = "tampered"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError):
        receipt.validate_runtime_setup_receipt(linux_python=python)


def test_installed_pytorch3d_provenance_rejects_wrong_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDistribution:
        def read_text(self, filename: str) -> str | None:
            assert filename == "direct_url.json"
            return json.dumps(
                {
                    "url": receipt.PYTORCH3D_REPOSITORY,
                    "vcs_info": {"vcs": "git", "commit_id": "f" * 40},
                }
            )

    monkeypatch.setattr(receipt.importlib.metadata, "distribution", lambda _name: FakeDistribution())
    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="installed PyTorch3D commit mismatch"):
        receipt._installed_pytorch3d_provenance()
