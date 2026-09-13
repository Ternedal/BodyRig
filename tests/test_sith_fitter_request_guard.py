from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.bridges import sith_fitter_request_guard as guard


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "bodyrig" / "sith_fitter_orchestrator.py"


def _request(*, request_version: object = 1, identity_version: object = 1) -> dict:
    return {
        "format": "bodyrig-avatar-fit-request",
        "version": request_version,
        "name": "Bridge Fixture",
        "bodyprint": {"format": "modelrig-bodyprint", "version": 1},
        "visual_identity": {
            "format": "bodyrig-visual-identity",
            "version": identity_version,
            "subject_track_id": "subject-1",
            "privacy": {
                "contains_source_media": False,
                "contains_biometric_template": False,
            },
        },
    }


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.mark.parametrize("version", [True, False, "1", None, 2])
def test_guard_rejects_non_numeric_request_v1(tmp_path: Path, version: object) -> None:
    path = _write(tmp_path / "request.json", _request(request_version=version))
    with pytest.raises(guard.SithFitterRequestGuardError, match="request format/version"):
        guard.validate_request(path)


@pytest.mark.parametrize("version", [True, False, "1", None, 2])
def test_guard_rejects_non_numeric_visual_identity_v1(tmp_path: Path, version: object) -> None:
    path = _write(tmp_path / "request.json", _request(identity_version=version))
    with pytest.raises(guard.SithFitterRequestGuardError, match="identity format/version"):
        guard.validate_request(path)


def test_guard_preserves_numeric_one_point_zero_compatibility(tmp_path: Path) -> None:
    value = _request(request_version=1.0, identity_version=1.0)
    path = _write(tmp_path / "request.json", value)
    validated = guard.validate_request(path)
    assert validated["version"] == 1.0
    assert validated["visual_identity"]["version"] == 1.0


def test_guard_rejects_before_gender_wrapper_delegation(monkeypatch, tmp_path: Path) -> None:
    path = _write(tmp_path / "request.json", _request(request_version=True))

    def forbidden_run_path(*_args, **_kwargs):
        raise AssertionError("gender wrapper executed before request authority validation")

    monkeypatch.setattr(guard.runpy, "run_path", forbidden_run_path)
    assert guard.main(["--bodyrig-request", str(path)]) == 1


def test_guard_delegates_valid_request_to_unchanged_gender_wrapper(monkeypatch, tmp_path: Path) -> None:
    path = _write(tmp_path / "request.json", _request())
    called: dict[str, object] = {}

    def fake_run_path(target: str, *, run_name: str):
        called["target"] = target
        called["run_name"] = run_name
        return {}

    monkeypatch.setattr(guard.runpy, "run_path", fake_run_path)
    assert guard.main(["--bodyrig-request", str(path), "--bodyrig-smplx-gender", "female"]) == 0
    assert Path(str(called["target"])).name == "sith_smplx_vrm_fitter_gender.py"
    assert called["run_name"] == "__main__"


def test_orchestrator_routes_builtin_wsl_fit_through_request_guard() -> None:
    source = ORCHESTRATOR.read_text(encoding="utf-8")
    guard_path = '"sith_fitter_request_guard.py"'
    gender_path = '"sith_smplx_vrm_fitter_gender.py"'
    assert guard_path in source
    assert gender_path in source
    assert "linux_bridge = _wsl_path(bridge" in source
    assert "builtin SiTH fitter request guard is missing" in source
    assert source.index(gender_path) < source.index("linux_bridge = _wsl_path(bridge")
