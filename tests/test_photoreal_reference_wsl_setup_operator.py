from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "setup-photoreal-reference-wsl.ps1").read_text(encoding="utf-8")


def test_reference_wsl_setup_pins_published_onnxruntime_gpu_wheel() -> None:
    assert '$onnxruntimeVersion = "1.20.2"' in SCRIPT
    assert '$onnxruntimeVersion = "1.20.1"' not in SCRIPT
    assert '"onnxruntime-gpu==$onnxruntimeVersion"' in SCRIPT


def test_reference_wsl_setup_keeps_numpy1_compatible_opencv() -> None:
    assert '$numpyVersion = "1.26.4"' in SCRIPT
    assert '$opencvVersion = "4.9.0.80"' in SCRIPT
    assert '"opencv-python==$opencvVersion"' in SCRIPT
    assert '"opencv-python-headless"' not in SCRIPT


def test_reference_wsl_setup_avoids_shell_redirection_in_xtcocotools_requirement() -> None:
    assert '$xtcocotoolsVersion = "1.14.3"' in SCRIPT
    assert '"xtcocotools==$xtcocotoolsVersion"' in SCRIPT
    assert 'xtcocotools>=' not in SCRIPT
    assert 'xtcocotools = $xtcocotoolsVersion' in SCRIPT


def test_reference_wsl_openmmlab_versions_are_compatible_and_probed() -> None:
    assert '$mmposeVersion = "1.3.2"' in SCRIPT
    assert '$mmdetRevision = "fe3f809a0a514189baf889aa358c498d51ee36cd"' in SCRIPT
    assert '$mmdetVersion = "3.2.0"' in SCRIPT
    assert 'if ([string]$probe.mmdet -ne $mmdetVersion)' in SCRIPT
    assert 'if ([string]$probe.mmpose -ne $mmposeVersion)' in SCRIPT


def test_reference_wsl_mmdetection_build_sees_installed_torch() -> None:
    mmdet_url = '"git+https://github.com/open-mmlab/mmdetection.git@$mmdetRevision"'
    mmdet_install = SCRIPT.index(mmdet_url)
    no_isolation = SCRIPT.rindex('"--no-build-isolation"', 0, mmdet_install)
    pip_install = SCRIPT.rindex('"pip", "install"', 0, no_isolation)

    assert pip_install < no_isolation < mmdet_install


def test_reference_wsl_mmpose_bypasses_unused_legacy_chumpy_dependency() -> None:
    mmpose_url = '"git+https://github.com/open-mmlab/mmpose.git@$mmposeRevision"'
    mmpose_install = SCRIPT.index(mmpose_url)
    no_deps = SCRIPT.rindex('"--no-deps"', 0, mmpose_install)
    no_isolation = SCRIPT.rindex('"--no-build-isolation"', 0, no_deps)
    pip_install = SCRIPT.rindex('"pip", "install"', 0, no_isolation)

    assert pip_install < no_isolation < no_deps < mmpose_install
    assert '"chumpy"' not in SCRIPT


def test_reference_wsl_force_repair_rebuilds_partial_environment() -> None:
    force_guard = SCRIPT.index("if ($Force)")
    remove_venv = SCRIPT.index('Invoke-Wsl -Root -Arguments @("/bin/rm", "-rf", $venvRoot)')
    create_venv = SCRIPT.index('Invoke-Wsl -Root -Arguments @("/usr/bin/python3", "-m", "venv", $venvRoot)')

    assert force_guard < remove_venv < create_venv
    assert 'Use -Force to rebuild.' in SCRIPT
