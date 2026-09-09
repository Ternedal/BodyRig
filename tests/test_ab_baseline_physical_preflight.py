from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import bodyrig.ab_baseline_physical_preflight as preflight_module
import bodyrig.app as app_module
import bodyrig.high_fidelity_preview_api as authority_api


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_SCRIPT = (ROOT / "preflight-ab-baseline.ps1").read_text(encoding="utf-8")
START_SCRIPT = (ROOT / "start-ab-baseline.ps1").read_text(encoding="utf-8")
REVISION = "a" * 40
PERSON_ID = "person-" + "1" * 32
PERFORMER_ID = "42"


def _authority(revision: str = REVISION) -> dict:
    return {
        "ok": True,
        "revision": revision,
        "powershell": r"C:\Program Files\PowerShell\7\pwsh.exe",
        "powershell_major": 7,
    }


def _profile() -> dict:
    return {
        "person_id": PERSON_ID,
        "source": {
            "kind": "stash-performer",
            "performer_id": PERFORMER_ID,
        },
    }


def _environment() -> dict[str, str]:
    return {
        "STASH_URL": "http://127.0.0.1:9999",
        "STASH_API_KEY": "local-secret-never-returned",
    }


def _install_common(monkeypatch) -> None:
    monkeypatch.setattr(preflight_module, "operator_checkout_status", lambda: _authority())
    monkeypatch.setattr(preflight_module, "person_library", lambda: Path("unused-person-library"))
    monkeypatch.setattr(preflight_module, "load_profile", lambda _root, _person_id: _profile())
    monkeypatch.setattr(preflight_module.manager, "list", lambda *, person_id=None: [])


def _successful_process(args, *, usable_source_count: int = 3) -> subprocess.CompletedProcess[str]:
    joined = " ".join(str(item) for item in args)
    if "check-reference-renderer-ready.ps1" in joined:
        return subprocess.CompletedProcess(args, 0, "BodyRig reference renderer toolchain: READY\n", "")
    if "check-rig-ready.ps1" in joined:
        return subprocess.CompletedProcess(args, 0, "BodyRig rig readiness: READY\n", "")
    return subprocess.CompletedProcess(
        args,
        0,
        json.dumps(
            {
                "ok": True,
                "performer": {"id": PERFORMER_ID, "name": "Example"},
                "decode_gate": "ffmpeg-one-frame-v1",
                "usable_source_count": usable_source_count,
            }
        ),
        "",
    )


def test_service_bound_preflight_uses_service_environment_and_persists_nothing(monkeypatch) -> None:
    _install_common(monkeypatch)
    calls: list[list[str]] = []

    def runner(args, *, check, capture_output, text, timeout):
        calls.append(list(args))
        assert check is False
        assert capture_output is True
        assert text is True
        assert timeout > 0
        return _successful_process(args)

    result = preflight_module.run_ab_baseline_physical_preflight(
        PERSON_ID,
        expected_bodyrig_revision=REVISION,
        runner=runner,
        environ=_environment(),
    )

    assert result == {
        "format": "bodyrig-ab-baseline-physical-preflight",
        "version": 1,
        "ready": True,
        "person_id": PERSON_ID,
        "performer_id": PERFORMER_ID,
        "bodyrig_revision": REVISION,
        "renderer_ready": True,
        "decode_gate": "ffmpeg-one-frame-v1",
        "usable_source_count": 3,
        "service_environment_bound": True,
        "readiness_output_persisted": False,
        "physical_acceptance_authority": False,
        "promotion_authority": False,
        "production_activation": False,
    }
    assert len(calls) == 3
    renderer, readiness, probe = calls
    assert "check-reference-renderer-ready.ps1" in " ".join(renderer)
    assert "check-rig-ready.ps1" in " ".join(readiness)
    assert "-BodyRigPython" in readiness
    assert "-StashUrl" in readiness
    assert "http://127.0.0.1:9999" in readiness
    assert "-ApiKeyEnv" in readiness and "STASH_API_KEY" in readiness
    assert "-WslExe" in readiness and "wsl.exe" in readiness
    assert "-Out" not in readiness
    assert "bodyrig.stash_cli" in probe
    assert "probe" in probe
    assert "--performer-id" in probe and PERFORMER_ID in probe
    assert "--ffmpeg" in probe and "ffmpeg" in probe
    assert "local-secret-never-returned" not in json.dumps(result)


def test_service_bound_preflight_requires_same_environment_as_body_build(monkeypatch) -> None:
    _install_common(monkeypatch)

    with pytest.raises(preflight_module.AbBaselinePhysicalPreflightError, match="STASH_API_KEY"):
        preflight_module.run_ab_baseline_physical_preflight(
            PERSON_ID,
            expected_bodyrig_revision=REVISION,
            runner=lambda *args, **kwargs: pytest.fail("runner must not start without service transport authority"),
            environ={"STASH_URL": "http://127.0.0.1:9999"},
        )


def test_service_bound_preflight_rejects_open_job_before_physical_probe(monkeypatch) -> None:
    _install_common(monkeypatch)
    monkeypatch.setattr(
        preflight_module.manager,
        "list",
        lambda *, person_id=None: [{"job_id": "job-" + "2" * 32, "status": "running"}],
    )

    with pytest.raises(preflight_module.AbBaselinePhysicalPreflightError, match="already open"):
        preflight_module.run_ab_baseline_physical_preflight(
            PERSON_ID,
            expected_bodyrig_revision=REVISION,
            runner=lambda *args, **kwargs: pytest.fail("runner must not start with competing job"),
            environ=_environment(),
        )


def test_service_bound_preflight_rejects_missing_renderer_ready_marker(monkeypatch) -> None:
    _install_common(monkeypatch)

    def runner(args, **_kwargs):
        return subprocess.CompletedProcess(args, 0, "completed without canonical marker\n", "")

    with pytest.raises(preflight_module.AbBaselinePhysicalPreflightError, match="reference-renderer.*READY marker"):
        preflight_module.run_ab_baseline_physical_preflight(
            PERSON_ID,
            expected_bodyrig_revision=REVISION,
            runner=runner,
            environ=_environment(),
        )


def test_service_bound_preflight_rejects_missing_rig_ready_marker(monkeypatch) -> None:
    _install_common(monkeypatch)

    def runner(args, **_kwargs):
        joined = " ".join(str(item) for item in args)
        if "check-reference-renderer-ready.ps1" in joined:
            return subprocess.CompletedProcess(args, 0, "BodyRig reference renderer toolchain: READY\n", "")
        return subprocess.CompletedProcess(args, 0, "completed without canonical marker\n", "")

    with pytest.raises(preflight_module.AbBaselinePhysicalPreflightError, match="live readiness.*READY marker"):
        preflight_module.run_ab_baseline_physical_preflight(
            PERSON_ID,
            expected_bodyrig_revision=REVISION,
            runner=runner,
            environ=_environment(),
        )


def test_service_bound_preflight_rejects_no_decodable_source(monkeypatch) -> None:
    _install_common(monkeypatch)

    def runner(args, **_kwargs):
        return _successful_process(args, usable_source_count=0)

    with pytest.raises(preflight_module.AbBaselinePhysicalPreflightError, match="no locally decodable source"):
        preflight_module.run_ab_baseline_physical_preflight(
            PERSON_ID,
            expected_bodyrig_revision=REVISION,
            runner=runner,
            environ=_environment(),
        )


def test_service_bound_preflight_rejects_checkout_drift_after_live_checks(monkeypatch) -> None:
    authorities = iter([_authority(REVISION), _authority("b" * 40)])
    monkeypatch.setattr(preflight_module, "operator_checkout_status", lambda: next(authorities))
    monkeypatch.setattr(preflight_module, "person_library", lambda: Path("unused-person-library"))
    monkeypatch.setattr(preflight_module, "load_profile", lambda _root, _person_id: _profile())
    monkeypatch.setattr(preflight_module.manager, "list", lambda *, person_id=None: [])

    def runner(args, **_kwargs):
        return _successful_process(args, usable_source_count=1)

    with pytest.raises(preflight_module.AbBaselinePhysicalPreflightError, match="moved during physical preflight"):
        preflight_module.run_ab_baseline_physical_preflight(
            PERSON_ID,
            expected_bodyrig_revision=REVISION,
            runner=runner,
            environ=_environment(),
        )


def test_ab_preflight_api_forwards_exact_revision(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def run(person_id: str, *, expected_bodyrig_revision: str) -> dict:
        captured.update(person_id=person_id, revision=expected_bodyrig_revision)
        return {
            "format": "bodyrig-ab-baseline-physical-preflight",
            "version": 1,
            "ready": True,
            "person_id": person_id,
            "performer_id": PERFORMER_ID,
            "bodyrig_revision": expected_bodyrig_revision,
            "renderer_ready": True,
            "decode_gate": "ffmpeg-one-frame-v1",
            "usable_source_count": 1,
            "service_environment_bound": True,
            "readiness_output_persisted": False,
            "physical_acceptance_authority": False,
            "promotion_authority": False,
            "production_activation": False,
        }

    monkeypatch.setattr(authority_api, "run_ab_baseline_physical_preflight", run)
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    response = TestClient(app_module.app).post(
        f"/api/v1/people/{PERSON_ID}/body/ab-baseline-preflight",
        json={"expected_bodyrig_revision": REVISION},
    )
    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["renderer_ready"] is True
    assert captured == {"person_id": PERSON_ID, "revision": REVISION}


def test_ab_preflight_api_rejects_noncanonical_revision(monkeypatch) -> None:
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    response = TestClient(app_module.app).post(
        f"/api/v1/people/{PERSON_ID}/body/ab-baseline-preflight",
        json={"expected_bodyrig_revision": "main"},
    )
    assert response.status_code == 422


def test_powershell_preflight_binds_candidates_to_service_side_physical_readiness() -> None:
    assert "bodyrig.ab_baseline_candidates" in PREFLIGHT_SCRIPT
    assert "/api/v1/operator-authority" in PREFLIGHT_SCRIPT
    assert "/api/v1/people/$resolvedPersonId/body/ab-baseline-preflight" in PREFLIGHT_SCRIPT
    assert "renderer_ready -ne $true" in PREFLIGHT_SCRIPT
    assert "service_environment_bound -ne $true" in PREFLIGHT_SCRIPT
    assert "readiness_output_persisted -ne $false" in PREFLIGHT_SCRIPT
    assert "ffmpeg-one-frame-v1" in PREFLIGHT_SCRIPT
    assert "-ExpectedMainRevision $mainRevision" in PREFLIGHT_SCRIPT
    assert "-ExpectedPbrRevision $pbrRevision" in PREFLIGHT_SCRIPT
    assert "-ExpectedThroughputRevision $throughputRevision" in PREFLIGHT_SCRIPT
    assert "physical_acceptance_authority = $false" in PREFLIGHT_SCRIPT
    assert "promotion_authority = $false" in PREFLIGHT_SCRIPT
    assert "production_activation = $false" in PREFLIGHT_SCRIPT


def test_start_launcher_runs_read_only_preflight_before_enqueue() -> None:
    assert "preflight-ab-baseline.ps1" in START_SCRIPT
    assert "No baseline job was enqueued" in START_SCRIPT
    assert START_SCRIPT.index("preflight-ab-baseline.ps1") < START_SCRIPT.index("start-revision-bound-body-build.ps1")
