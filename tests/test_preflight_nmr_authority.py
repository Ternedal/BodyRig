from __future__ import annotations

from bodyrig.preflight_cli import _validate_probe


def _probe() -> dict:
    return {
        "import_torch": True,
        "import_cv2": True,
        "import_joblib": True,
        "import_hmr2": True,
        "import_phalp": True,
        "import_neural_renderer": True,
        "phalp_root": "/opt/PHALP/phalp",
        "phalp_tracker_match": True,
        "nmr_authority_match": True,
        "nmr_url": "https://github.com/shubham-goel/NMR.git",
        "nmr_commit": "e990b3c70f48d39231f607c79d76ce3db4bf7483",
        "cuda_available": True,
        "load_libcuda": True,
        "load_libcudnn_cnn_infer": True,
    }


def test_preflight_accepts_pinned_nmr_authority() -> None:
    errors: list[str] = []
    _validate_probe(
        _probe(),
        errors,
        phalp_repo="/opt/PHALP",
        linux=True,
        allow_cpu=False,
    )
    assert errors == []


def test_preflight_rejects_missing_or_untrusted_nmr() -> None:
    probe = _probe()
    probe["import_neural_renderer"] = False
    probe["error_neural_renderer"] = "ModuleNotFoundError: No module named 'neural_renderer'"
    probe["nmr_authority_match"] = False
    probe["nmr_commit"] = "wrong"

    errors: list[str] = []
    _validate_probe(
        probe,
        errors,
        phalp_repo="/opt/PHALP",
        linux=True,
        allow_cpu=False,
    )

    assert any("external import failed: neural_renderer" in error for error in errors)
    assert any("does not match pinned BodyRig NMR authority" in error for error in errors)


def test_preflight_rejects_unloadable_wsl_cuda_or_cudnn() -> None:
    probe = _probe()
    probe["load_libcuda"] = False
    probe["error_load_libcuda"] = "OSError: libcuda.so not found"
    probe["load_libcudnn_cnn_infer"] = False
    probe["error_load_libcudnn_cnn_infer"] = "OSError: libcudnn_cnn_infer.so.8 not found"

    errors: list[str] = []
    _validate_probe(
        probe,
        errors,
        phalp_repo="/opt/PHALP",
        linux=True,
        allow_cpu=False,
    )

    assert any("cannot open libcuda.so" in error for error in errors)
    assert any("cannot open libcudnn_cnn_infer.so.8" in error for error in errors)


def test_allow_cpu_diagnostic_skips_wsl_loader_gate() -> None:
    probe = _probe()
    probe["cuda_available"] = False
    probe["load_libcuda"] = False
    probe["load_libcudnn_cnn_infer"] = False

    errors: list[str] = []
    _validate_probe(
        probe,
        errors,
        phalp_repo="/opt/PHALP",
        linux=True,
        allow_cpu=True,
    )

    assert errors == []
