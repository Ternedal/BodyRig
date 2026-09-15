from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "setup-photoreal-exavatar-wsl.ps1").read_text(encoding="utf-8")


def test_exavatar_runtime_pins_teacher_versions_and_pytorch3d_commit() -> None:
    assert '$torchVersion = "2.6.0"' in SCRIPT
    assert '$torchvisionVersion = "0.21.0"' in SCRIPT
    assert '$numpyVersion = "1.26.4"' in SCRIPT
    assert '$mmcvVersion = "2.1.0"' in SCRIPT
    assert '$pytorch3dCommit = "0a7d4c1a171e8b768c63f15b17564f9ad495f49b"' in SCRIPT
    assert 'https://download.pytorch.org/whl/cu124' in SCRIPT


def test_exavatar_runtime_requires_existing_nvcc_and_never_installs_legacy_ubuntu_toolkit() -> None:
    assert '/usr/bin/which nvcc' in SCRIPT
    assert "BodyRig will not install Ubuntu's legacy nvidia-cuda-toolkit automatically" in SCRIPT
    assert '"nvidia-cuda-toolkit"' not in SCRIPT


def test_exavatar_runtime_uses_public_chumpy_070_and_patches_numpy_aliases_fail_closed() -> None:
    assert '$chumpyVersion = "0.70"' in SCRIPT
    assert 'chumpy==0.71' not in SCRIPT
    assert '"--no-build-isolation", "chumpy==$chumpyVersion"' in SCRIPT
    assert 'marker = "from numpy import bool, int, float, complex, object, unicode, str, nan, inf"' in SCRIPT
    assert 'bodyrig-chumpy-0.70-numpy-alias-v1' in SCRIPT
    assert 'if raw.count(marker) != 1:' in SCRIPT
    assert 'import chumpy' in SCRIPT
    assert '"chumpy_smoke": True' in SCRIPT
    assert 'chumpy_patch = $chumpyPatch' in SCRIPT


def test_exavatar_runtime_applies_hand4whole_author_torchgeometry_patch() -> None:
    for fragment in (
        'mask_c0 = mask_d2.float() * mask_d0_d1.float()',
        'mask_c1 = mask_d2.float() * (1 - mask_d0_d1.float())',
        'mask_c2 = (1 - mask_d2.float()) * mask_d0_nd1.float()',
        'mask_c3 = (1 - mask_d2.float()) * (1 - mask_d0_nd1.float())',
    ):
        assert fragment in SCRIPT
    assert 'hand4whole-author-float-mask-v1' in SCRIPT
    assert 'torchgeometry_smoke' in SCRIPT


def test_exavatar_runtime_keeps_authority_false() -> None:
    assert 'photoreal_acceptance_authority = $false' in SCRIPT
    assert 'production_activation = $false' in SCRIPT
    assert 'Photoreal authority: FALSE' in SCRIPT
    assert 'Production:      FALSE' in SCRIPT
