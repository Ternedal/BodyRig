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
        "opencv": receipt._opencv_module_version(
            receipt.EXPECTED_REQUESTED_VERSIONS["opencv_python"]
        ),
        "smplx": receipt.EXPECTED_REQUESTED_VERSIONS["smplx"],
        "lpips": receipt.EXPECTED_REQUESTED_VERSIONS["lpips"],
        "pyopengl": receipt.EXPECTED_REQUESTED_VERSIONS["pyopengl"],
        "pyrender": receipt.EXPECTED_REQUESTED_VERSIONS["pyrender"],
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


def _pin_live_distribution_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    original = receipt.importlib.metadata.version

    def version(name: str) -> str:
        if name == "opencv-python":
            return receipt.EXPECTED_REQUESTED_VERSIONS["opencv_python"]
        return original(name)

    monkeypatch.setattr(receipt.importlib.metadata, "version", version)


def _pin_live_vcs_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        receipt,
        "_installed_pytorch3d_provenance",
        lambda *, runtime_root: {
            "url": (runtime_root / "sources" / f"pytorch3d-{receipt.PYTORCH3D_COMMIT[:12]}").as_uri(),
            "commit": receipt.PYTORCH3D_COMMIT,
            "source_path": str(runtime_root / "sources" / f"pytorch3d-{receipt.PYTORCH3D_COMMIT[:12]}"),
            "marker_path": str(runtime_root / "sources" / f"pytorch3d-{receipt.PYTORCH3D_COMMIT[:12]}" / ".bodyrig-pinned-commit"),
        },
    )
    monkeypatch.setattr(
        receipt,
        "_installed_mmcv_provenance",
        lambda: {"url": receipt.MMCV_REPOSITORY, "commit": receipt.MMCV_COMMIT},
    )


@LINUX_RUNTIME_ONLY
def test_runtime_setup_receipt_accepts_exact_pinned_provenance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, chumpy, torchgeometry = _runtime(tmp_path)
    _pin_live_vcs_provenance(monkeypatch)
    _pin_live_distribution_versions(monkeypatch)
    result = receipt.validate_runtime_setup_receipt(linux_python=python)

    assert result["pytorch3d_commit"] == receipt.PYTORCH3D_COMMIT
    assert result["expected_cuda_version"] == receipt.EXPECTED_CUDA_VERSION
    assert result["requested_versions"]["chumpy"] == "0.70"
    assert result["requested_versions"]["pyopengl"] == "3.1.0"
    assert result["requested_versions"]["pyrender"] == "0.1.45"
    assert result["requested_versions"]["mmcv_commit"] == receipt.MMCV_COMMIT
    assert result["chumpy_patch"]["patch"] == receipt.CHUMPY_PATCH
    assert result["torchgeometry_patch"]["patch"] == receipt.TORCHGEOMETRY_PATCH
    assert result["live_patch_bytes_verified"] is True
    assert result["chumpy_live_path"] == str(chumpy.resolve())
    assert result["torchgeometry_live_path"] == str(torchgeometry.resolve())
    assert result["pytorch3d_live_provenance"]["commit"] == receipt.PYTORCH3D_COMMIT
    assert result["mmcv_live_provenance"]["commit"] == receipt.MMCV_COMMIT
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_runtime_setup_receipt_rejects_changed_version_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_vcs_provenance(monkeypatch)
    _pin_live_distribution_versions(monkeypatch)
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
    _pin_live_vcs_provenance(monkeypatch)
    _pin_live_distribution_versions(monkeypatch)
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
    _pin_live_vcs_provenance(monkeypatch)
    _pin_live_distribution_versions(monkeypatch)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["nvcc"] = ["Cuda compilation tools, release 12.5, V12.5.82"]
    value["setup_sha256"] = _digest(value, "setup_sha256")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="nvcc/Torch CUDA parity"):
        receipt.validate_runtime_setup_receipt(linux_python=python)


def test_runtime_setup_receipt_rejects_wrong_patch_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_vcs_provenance(monkeypatch)
    _pin_live_distribution_versions(monkeypatch)
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
    _pin_live_vcs_provenance(monkeypatch)
    _pin_live_distribution_versions(monkeypatch)
    chumpy.write_bytes(b"changed-after-setup")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="Chumpy patched bytes changed after setup"):
        receipt.validate_runtime_setup_receipt(linux_python=python)


def test_runtime_setup_receipt_rejects_digest_tampering(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_vcs_provenance(monkeypatch)
    _pin_live_distribution_versions(monkeypatch)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["observed"]["chumpy"] = "tampered"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError):
        receipt.validate_runtime_setup_receipt(linux_python=python)


@LINUX_RUNTIME_ONLY
def test_runtime_setup_receipt_accepts_opencv_module_version_with_exact_wheel_pin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_vcs_provenance(monkeypatch)
    _pin_live_distribution_versions(monkeypatch)

    result = receipt.validate_runtime_setup_receipt(linux_python=python)

    assert result["observed"]["opencv"] == "4.10.0"
    assert result["requested_versions"]["opencv_python"] == "4.10.0.84"


@LINUX_RUNTIME_ONLY
def test_runtime_setup_receipt_rejects_live_opencv_distribution_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_vcs_provenance(monkeypatch)
    monkeypatch.setattr(
        receipt,
        "_installed_distribution_version",
        lambda name: "4.10.0.99" if name == "opencv-python" else "",
    )

    with pytest.raises(
        receipt.PhotorealExAvatarRuntimeSetupReceiptError,
        match="installed opencv-python distribution mismatch",
    ):
        receipt.validate_runtime_setup_receipt(linux_python=python)


@LINUX_RUNTIME_ONLY
def test_runtime_setup_receipt_rejects_observed_pyopengl_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    python, _chumpy, _torchgeometry = _runtime(tmp_path)
    _pin_live_vcs_provenance(monkeypatch)
    _pin_live_distribution_versions(monkeypatch)
    path = python.parent.parent / "bodyrig-exavatar-runtime-setup.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["observed"]["pyopengl"] = "9.9.9"
    value["setup_sha256"] = _digest(value, "setup_sha256")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="observed version mismatch for pyopengl"):
        receipt.validate_runtime_setup_receipt(linux_python=python)


def test_installed_mmcv_provenance_rejects_wrong_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDistribution:
        def read_text(self, filename: str) -> str | None:
            assert filename == "direct_url.json"
            return json.dumps(
                {
                    "url": receipt.MMCV_REPOSITORY,
                    "vcs_info": {"vcs": "git", "commit_id": "f" * 40},
                }
            )

    monkeypatch.setattr(receipt.importlib.metadata, "distribution", lambda _name: FakeDistribution())
    with pytest.raises(receipt.PhotorealExAvatarRuntimeSetupReceiptError, match="installed MMCV commit mismatch"):
        receipt._installed_mmcv_provenance()


@LINUX_RUNTIME_ONLY
def test_installed_pytorch3d_provenance_accepts_exact_local_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "bodyrig-exavatar"
    source = runtime_root / "sources" / f"pytorch3d-{receipt.PYTORCH3D_COMMIT[:12]}"
    source.mkdir(parents=True)
    (source / ".bodyrig-pinned-commit").write_text(
        receipt.PYTORCH3D_COMMIT + "\n",
        encoding="utf-8",
    )

    class FakeDistribution:
        def read_text(self, filename: str) -> str | None:
            assert filename == "direct_url.json"
            return json.dumps({"url": source.resolve().as_uri(), "dir_info": {}})

    monkeypatch.setattr(receipt.importlib.metadata, "distribution", lambda _name: FakeDistribution())
    result = receipt._installed_pytorch3d_provenance(runtime_root=runtime_root)

    assert result["commit"] == receipt.PYTORCH3D_COMMIT
    assert result["source_path"] == str(source.resolve())


@LINUX_RUNTIME_ONLY
def test_installed_pytorch3d_provenance_rejects_wrong_local_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "bodyrig-exavatar"
    source = tmp_path / "untrusted" / f"pytorch3d-{receipt.PYTORCH3D_COMMIT[:12]}"
    source.mkdir(parents=True)
    (source / ".bodyrig-pinned-commit").write_text(
        receipt.PYTORCH3D_COMMIT + "\n",
        encoding="utf-8",
    )

    class FakeDistribution:
        def read_text(self, filename: str) -> str | None:
            assert filename == "direct_url.json"
            return json.dumps({"url": source.resolve().as_uri(), "dir_info": {}})

    monkeypatch.setattr(receipt.importlib.metadata, "distribution", lambda _name: FakeDistribution())
    with pytest.raises(
        receipt.PhotorealExAvatarRuntimeSetupReceiptError,
        match="source path mismatch",
    ):
        receipt._installed_pytorch3d_provenance(runtime_root=runtime_root)


@LINUX_RUNTIME_ONLY
def test_installed_pytorch3d_provenance_rejects_wrong_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "bodyrig-exavatar"
    source = runtime_root / "sources" / f"pytorch3d-{receipt.PYTORCH3D_COMMIT[:12]}"
    source.mkdir(parents=True)
    (source / ".bodyrig-pinned-commit").write_text("f" * 40 + "\n", encoding="utf-8")

    class FakeDistribution:
        def read_text(self, filename: str) -> str | None:
            assert filename == "direct_url.json"
            return json.dumps({"url": source.resolve().as_uri(), "dir_info": {}})

    monkeypatch.setattr(receipt.importlib.metadata, "distribution", lambda _name: FakeDistribution())
    with pytest.raises(
        receipt.PhotorealExAvatarRuntimeSetupReceiptError,
        match="commit marker mismatch",
    ):
        receipt._installed_pytorch3d_provenance(runtime_root=runtime_root)
