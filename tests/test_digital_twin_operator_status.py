from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.digital_twin_operator_status as operator
import bodyrig.digital_twin_operator_status_cli as operator_cli
from bodyrig.acceptance_status import AcceptanceStatus

PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
BODY_ID = "body-0123456789abcdef0123456789abcdef"
REVISION = "a" * 40
OTHER_REVISION = "b" * 40
AUTHORITY_ID = "dtcomp-0123456789abcdef0123456789abcdef"
RELEASE_ID = "dtrelease-0123456789abcdef0123456789abcdef"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    composition = tmp_path / "composition"
    acceptance = tmp_path / "acceptance"
    library = tmp_path / "library"
    repo = tmp_path / "repo"
    composition.mkdir()
    acceptance.mkdir()
    library.mkdir()
    repo.mkdir()
    _write_json(composition / "authority.json", {"body_id": BODY_ID})
    for name in (
        "person-assembly-receipt.json",
        "body-release-status.json",
        "hands-feet-nails-authority.json",
        "wardrobe-authority.json",
    ):
        _write_json(composition / name, {"fixture": name})
    (acceptance / f"{BODY_ID}.mrbody").write_bytes(b"fixture")
    return composition, acceptance, library, repo


def _composition() -> dict:
    return {
        "format": "bodyrig-digital-twin-composition-authority",
        "version": 1,
        "authority_id": AUTHORITY_ID,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "body_id": BODY_ID,
        "bodyrig_revision": REVISION,
    }


def _physical_complete(path: Path) -> AcceptanceStatus:
    return AcceptanceStatus(
        state="complete",
        gate="release",
        acceptance_dir=str(path),
        body_id=BODY_ID,
        bodyrig_revision=REVISION,
        message="physical complete",
        next_command=None,
    )


def _m5_required(platform: str = "windows-unity-univrm", *, state: str = "required", message: str = "missing") -> dict:
    other = "android-quest-class" if platform == "windows-unity-univrm" else "windows-unity-univrm"
    return {
        "format": "bodyrig-digital-twin-platform-status",
        "version": 1,
        "m5_ready": False,
        "digital_twin_ready": False,
        "production_activation": False,
        "platforms": {
            platform: {"ready": False, "state": state, "message": message, "next_command": None},
            other: {"ready": False, "state": "required", "message": "missing", "next_command": None},
        },
        "blockers": [],
        "next_gate": f"m5:{platform}",
        "message": "M5 requires real platform realization.",
    }


def _m5_complete() -> dict:
    return {
        "format": "bodyrig-digital-twin-platform-status",
        "version": 1,
        "m5_ready": True,
        "digital_twin_ready": False,
        "production_activation": False,
        "platforms": {
            "windows-unity-univrm": {"ready": True, "state": "complete", "realization_sha256": "1" * 64},
            "android-quest-class": {"ready": True, "state": "complete", "realization_sha256": "2" * 64},
        },
        "blockers": [],
        "next_gate": "digital_twin_final_release",
        "message": "M5 complete",
    }


def _twin(*, ready: bool, eligible: bool) -> dict:
    return {
        "digital_twin_release_eligible": eligible,
        "digital_twin_ready": ready,
        "production_activation": ready,
        "next_gate": "complete" if ready else "digital_twin_final_release",
        "message": "complete" if ready else "release required",
    }


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    *,
    acceptance: Path,
    repo: Path,
    m5_status: dict,
    twin_status: dict,
    checkout_revision: str = REVISION,
) -> None:
    monkeypatch.setattr(operator, "_composition_bundle", lambda *args, **kwargs: (_composition(), b"{}", {}, b"{}"))
    monkeypatch.setattr(operator, "inspect_digital_twin_platform_acceptance", lambda **kwargs: m5_status)
    monkeypatch.setattr(operator, "inspect_acceptance_dir", lambda path: _physical_complete(acceptance))
    monkeypatch.setattr(operator, "apply_reference_policy", lambda status: status)
    monkeypatch.setattr(operator, "inspect_digital_twin_status", lambda **kwargs: twin_status)
    monkeypatch.setattr(operator, "_operator_root", lambda value: repo)
    monkeypatch.setattr(operator, "_git_checkout_state", lambda root: (checkout_revision, True))


def test_m5_next_command_is_exact_checkout_bound_and_read_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    composition, acceptance, library, repo = _workspace(tmp_path)
    _patch_common(
        monkeypatch,
        acceptance=acceptance,
        repo=repo,
        m5_status=_m5_required(),
        twin_status=_twin(ready=False, eligible=False),
    )
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    status = operator.inspect_operator_status(
        composition_authority_dir=composition,
        acceptance_dir=acceptance,
        library_root=library,
        operator_root=repo,
    )

    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert before == after
    assert status["read_only"] is True
    assert status["state"] == "required"
    assert status["next_gate"] == "digital_twin_platform_acceptance"
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert str((repo / "run-windows-digital-twin-probe.ps1").resolve()) in status["next_command"]
    assert str(acceptance.resolve()) in status["next_command"]
    assert str(composition.resolve()) in status["next_command"]


def test_checkout_revision_mismatch_suppresses_executable_next_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    composition, acceptance, library, repo = _workspace(tmp_path)
    _patch_common(
        monkeypatch,
        acceptance=acceptance,
        repo=repo,
        m5_status=_m5_required(),
        twin_status=_twin(ready=False, eligible=False),
        checkout_revision=OTHER_REVISION,
    )

    status = operator.inspect_operator_status(
        composition_authority_dir=composition,
        acceptance_dir=acceptance,
        library_root=library,
        operator_root=repo,
    )

    assert status["state"] == "blocked"
    assert status["next_gate"] == "operator-checkout"
    assert status["next_command"] is None
    assert OTHER_REVISION in status["message"]
    assert REVISION in status["message"]


def test_invalid_m5_evidence_fails_closed_instead_of_recommending_rerun(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    composition, acceptance, library, repo = _workspace(tmp_path)
    _patch_common(
        monkeypatch,
        acceptance=acceptance,
        repo=repo,
        m5_status=_m5_required(state="invalid", message="frozen realization bytes were modified"),
        twin_status=_twin(ready=False, eligible=False),
    )

    status = operator.inspect_operator_status(
        composition_authority_dir=composition,
        acceptance_dir=acceptance,
        library_root=library,
        operator_root=repo,
    )

    assert status["state"] == "invalid"
    assert status["next_command"] is None
    assert "modified" in status["message"]


def test_complete_m5_points_to_exact_m6_finalizer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    composition, acceptance, library, repo = _workspace(tmp_path)
    _patch_common(
        monkeypatch,
        acceptance=acceptance,
        repo=repo,
        m5_status=_m5_complete(),
        twin_status=_twin(ready=False, eligible=True),
    )
    monkeypatch.setattr(operator, "_chain_evidence", lambda **kwargs: {"fixture": True})
    monkeypatch.setattr(
        operator,
        "_authority_from_chain",
        lambda chain: {
            "release_id": RELEASE_ID,
            "person_id": PERSON_ID,
            "person_revision": PERSON_REVISION,
        },
    )

    status = operator.inspect_operator_status(
        composition_authority_dir=composition,
        acceptance_dir=acceptance,
        library_root=library,
        operator_root=repo,
    )

    assert status["state"] == "required"
    assert status["next_gate"] == "digital_twin_final_release"
    assert status["expected_m6_release_id"] == RELEASE_ID
    assert str((repo / "finalize-digital-twin-release.ps1").resolve()) in status["next_command"]


def test_existing_matching_m6_is_read_back_before_ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    composition, acceptance, library, repo = _workspace(tmp_path)
    _patch_common(
        monkeypatch,
        acceptance=acceptance,
        repo=repo,
        m5_status=_m5_complete(),
        twin_status=_twin(ready=False, eligible=True),
    )
    monkeypatch.setattr(operator, "_chain_evidence", lambda **kwargs: {"fixture": True})
    monkeypatch.setattr(
        operator,
        "_authority_from_chain",
        lambda chain: {
            "release_id": RELEASE_ID,
            "person_id": PERSON_ID,
            "person_revision": PERSON_REVISION,
        },
    )
    candidate = operator.release_dir(
        library,
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        release_id=RELEASE_ID,
    )
    candidate.mkdir(parents=True)
    monkeypatch.setattr(operator, "read_release", lambda *args, **kwargs: {"release_id": RELEASE_ID})
    monkeypatch.setattr(
        operator,
        "inspect_digital_twin_status",
        lambda **kwargs: _twin(ready=kwargs.get("final_release_authority") is not None, eligible=True),
    )

    status = operator.inspect_operator_status(
        composition_authority_dir=composition,
        acceptance_dir=acceptance,
        library_root=library,
        operator_root=repo,
    )

    assert status["state"] == "complete"
    assert status["next_gate"] == "complete"
    assert status["next_command"] is None
    assert status["digital_twin_ready"] is True
    assert status["production_activation"] is True


def test_cli_uses_blocked_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        operator_cli,
        "inspect_operator_status",
        lambda **kwargs: {"state": "blocked", "read_only": True},
    )
    code = operator_cli.main(
        [
            "--composition-authority-dir",
            "composition",
            "--acceptance-dir",
            "acceptance",
            "--operator-root",
            "repo",
        ]
    )
    assert code == 3
    assert json.loads(capsys.readouterr().out)["state"] == "blocked"


def test_powershell_wrapper_is_checkout_bound_and_evidence_read_only() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "digital-twin-status.ps1").read_text(encoding="utf-8")
    assert "bodyrig.digital_twin_operator_status_cli" in source
    assert '"--operator-root", $repoRoot' in source
    assert "bodyrig.__file__" in source
    assert "$env:PYTHONPATH = $repoRoot" in source
    for mutation in ("Set-Content", "Out-File", "New-Item", "Move-Item", "Remove-Item", "Copy-Item"):
        assert mutation not in source
