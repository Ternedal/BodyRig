from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


PROBE_PATH = Path(__file__).resolve().parents[1] / "tools" / "photoreal_reference_vision_probe.py"
SPEC = importlib.util.spec_from_file_location("bodyrig_reference_vision_probe_test", PROBE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class _Session:
    def __init__(self, providers: list[str]) -> None:
        self._providers = providers

    def get_providers(self) -> list[str]:
        return list(self._providers)


def _face_app(*provider_sets: list[str]):
    return SimpleNamespace(
        models={
            f"model-{index}": SimpleNamespace(session=_Session(providers))
            for index, providers in enumerate(provider_sets)
        }
    )


def test_probe_reads_active_insightface_execution_providers() -> None:
    app = _face_app(
        ["CUDAExecutionProvider", "CPUExecutionProvider"],
        ["CPUExecutionProvider"],
    )

    assert probe._active_face_execution_providers(app) == [
        "CPUExecutionProvider",
        "CUDAExecutionProvider",
    ]


def test_probe_exposes_cpu_fallback_instead_of_requested_provider_list() -> None:
    app = _face_app(["CPUExecutionProvider"], ["CPUExecutionProvider"])

    assert probe._active_face_execution_providers(app) == ["CPUExecutionProvider"]


def test_probe_fails_closed_without_insightface_sessions() -> None:
    with pytest.raises(probe.VisionProbeError, match="no initialized model sessions"):
        probe._active_face_execution_providers(SimpleNamespace(models={}))
