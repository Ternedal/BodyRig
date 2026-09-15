from __future__ import annotations

from bodyrig import photoreal_exavatar_runtime_preflight as runtime
from bodyrig import photoreal_exavatar_runtime_setup_receipt as setup


def test_runtime_accepts_pep440_local_cuda_suffix_only_when_base_version_matches() -> None:
    assert runtime._version_matches("2.6.0+cu124", "2.6.0") is True
    assert runtime._version_matches("0.21.0+cu124", "0.21.0") is True
    assert runtime._version_matches("2.6.1+cu124", "2.6.0") is False
    assert runtime._version_matches(None, "2.6.0") is False


def test_setup_receipt_uses_same_base_version_semantics() -> None:
    assert setup._version_matches("2.6.0+cu124", "2.6.0") is True
    assert setup._version_matches("0.21.0+cu124", "0.21.0") is True
    assert setup._version_matches("2.6.0+cu126", "2.6.0") is True
    # The local suffix is intentionally not CUDA authority. CUDA parity is a
    # separate exact gate through torch.version.cuda and nvcc.
    assert setup.EXPECTED_CUDA_VERSION == "12.4"
    assert runtime.EXPECTED_TORCH_CUDA_VERSION == "12.4"


def test_live_runtime_pins_mmpose_distribution_too() -> None:
    assert runtime.EXPECTED_VERSIONS["mmpose"] == "1.3.2"
