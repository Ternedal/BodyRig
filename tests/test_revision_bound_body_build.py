from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import bodyrig.app as app_module
import bodyrig.high_fidelity_preview_api as authority_api


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / "start-revision-bound-body-build.ps1").read_text(encoding="utf-8")


def _client(monkeypatch) -> TestClient:
    monkeypatch.setenv("BODYRIG_ALLOW_REMOTE", "1")
    return TestClient(app_module.app)


def test_operator_authority_exposes_exact_revision_without_local_paths(monkeypatch) -> None:
    revision = "a" * 40
    monkeypatch.setattr(
        authority_api,
        "operator_checkout_status",
        lambda: {
            "ok": True,
            "revision": revision,
            "root": r"C:\secret\BodyRig",
            "powershell": r"C:\Program Files\PowerShell\7\pwsh.exe",
            "powershell_major": 7,
        },
    )
    response = _client(monkeypatch).get("/api/v1/operator-authority")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "bodyrig_revision": revision,
        "reason": None,
    }
    assert "root" not in response.json()
    assert "powershell" not in response.json()


def test_operator_authority_fails_closed_when_ready_revision_is_invalid(monkeypatch) -> None:
    monkeypatch.setattr(
        authority_api,
        "operator_checkout_status",
        lambda: {"ok": True, "revision": "not-a-git-revision"},
    )
    response = _client(monkeypatch).get("/api/v1/operator-authority")
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["bodyrig_revision"] is None
    assert "without an exact Git revision" in response.json()["reason"]


def test_revision_bound_api_passes_exact_expected_revision(monkeypatch) -> None:
    revision = "c" * 40
    captured: dict[str, str] = {}

    def _start(person_id: str, *, expected_bodyrig_revision: str) -> dict:
        captured["person_id"] = person_id
        captured["revision"] = expected_bodyrig_revision
        return {
            "job_id": "job-" + "1" * 32,
            "kind": "body-build",
            "person_id": person_id,
            "status": "queued",
            "bodyrig_revision": expected_bodyrig_revision,
        }

    monkeypatch.setattr(authority_api, "start_revision_bound_body_build", _start)
    person_id = "person-" + "2" * 32
    response = _client(monkeypatch).post(
        f"/api/v1/people/{person_id}/body/build-revision-bound",
        json={"expected_bodyrig_revision": revision},
    )
    assert response.status_code == 200
    assert response.json()["bodyrig_revision"] == revision
    assert captured == {"person_id": person_id, "revision": revision}


def test_revision_bound_api_rejects_noncanonical_expected_revision(monkeypatch) -> None:
    response = _client(monkeypatch).post(
        "/api/v1/people/person-" + "3" * 32 + "/body/build-revision-bound",
        json={"expected_bodyrig_revision": "main"},
    )
    assert response.status_code == 422


def test_revision_bound_launcher_requires_clean_local_and_matching_service_authority() -> None:
    assert "$PSVersionTable.PSVersion.Major -lt 7" in LAUNCHER
    assert "git -C $repoRoot rev-parse HEAD" in LAUNCHER
    assert "git -C $repoRoot status --porcelain" in LAUNCHER
    assert '"$BaseUri/api/v1/operator-authority"' in LAUNCHER
    assert "$authority.ok -ne $true" in LAUNCHER
    assert "$serviceRevision -ne $head" in LAUNCHER
    assert "Revision-bound body builds require exact clean authority" in LAUNCHER


def test_revision_bound_launcher_resolves_person_and_rejects_competing_builds() -> None:
    assert "Pass exactly one of -PersonId or -PerformerId" in LAUNCHER
    assert '[string]$_.source.kind -eq "stash-performer"' in LAUNCHER
    assert '[string]$_.source.id -eq $PerformerId' in LAUNCHER
    assert "Multiple BodyRig Persons are bound to Stash performer" in LAUNCHER
    assert '[string]$_.kind -eq "body-build"' in LAUNCHER
    assert '[string]$_.status -in @("queued", "running")' in LAUNCHER


def test_revision_bound_launcher_binds_expected_revision_and_verifies_enqueued_job() -> None:
    assert "expected_bodyrig_revision = $head" in LAUNCHER
    assert '"$BaseUri/api/v1/people/$PersonId/body/build-revision-bound"' in LAUNCHER
    assert "$jobId -notmatch '^job-[0-9a-f]{32}$'" in LAUNCHER
    assert '[string]$started.kind -ne "body-build"' in LAUNCHER
    assert "$jobRevision -ne $head" in LAUNCHER
    assert '"Monitor:  .\\watch-body-build.ps1 -JobId \'$jobId\'"' in LAUNCHER
