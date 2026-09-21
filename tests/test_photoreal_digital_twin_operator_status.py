from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.photoreal_digital_twin_operator_status as status
import bodyrig.photoreal_digital_twin_operator_status_cli as status_cli
from bodyrig.digital_twin_photoreal_link import DigitalTwinPhotorealLinkError

PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
BODY_ID = "body-0123456789abcdef0123456789abcdef"
REVISION = "a" * 40
OTHER_REVISION = "b" * 40
M4_LINK_ID = "dtphoto-" + "1" * 32
M5_LINK_ID = "dtphotom5-" + "2" * 32
PHOTO_RELEASE_ID = "dtphotorel-" + "3" * 32
CANONICAL_RELEASE_ID = "dtrelease-" + "4" * 32


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    composition = tmp_path / "composition"
    acceptance = tmp_path / "acceptance"
    library = tmp_path / "library"
    repo = tmp_path / "repo"
    composition.mkdir()
    acceptance.mkdir()
    library.mkdir()
    repo.mkdir()
    _write_json(
        composition / "authority.json",
        {
            "person_id": PERSON_ID,
            "person_revision": PERSON_REVISION,
            "body_id": BODY_ID,
            "bodyrig_revision": REVISION,
        },
    )
    binding = tmp_path / "photoreal-person-binding.json"
    p3 = tmp_path / "p3-physical-runtime-review.json"
    _write_json(binding, {"fixture": "binding"})
    _write_json(p3, {"fixture": "p3"})
    for script in status._PHOTOREAL_SCRIPTS:
        (repo / script).write_text("# fixture\n", encoding="utf-8")
    return composition, acceptance, library, repo, binding, p3


def _canonical(
    repo: Path,
    *,
    state: str = "required",
    m5_ready: bool = False,
    ready: bool = False,
    next_gate: str = "digital_twin_platform_acceptance",
    next_command: str | None = "CANONICAL-NEXT",
    m6_authority_path: str | None = None,
) -> dict:
    return {
        "state": state,
        "operator_root": str(repo),
        "m5_ready": m5_ready,
        "digital_twin_ready": ready,
        "production_activation": ready,
        "next_gate": next_gate,
        "next_command": next_command,
        "message": "canonical status",
        "m6_authority_path": m6_authority_path,
    }


def _m4_expected() -> dict:
    return {
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "link_id": M4_LINK_ID,
    }


def _m5_expected() -> dict:
    return {
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "link_id": M5_LINK_ID,
    }


def _release_expected() -> dict:
    return {
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "release_id": PHOTO_RELEASE_ID,
    }


def _paths(library: Path) -> tuple[Path, Path, Path]:
    return (
        library / "m4-photo" / M4_LINK_ID,
        library / "m5-photo" / M5_LINK_ID,
        library / "m6-photo" / PHOTO_RELEASE_ID,
    )


def _patch_photoreal(
    monkeypatch: pytest.MonkeyPatch,
    *,
    library: Path,
) -> tuple[Path, Path, Path]:
    m4_dir, m5_dir, release_dir = _paths(library)
    monkeypatch.setattr(status, "build_photoreal_link", lambda *args, **kwargs: _m4_expected())
    monkeypatch.setattr(
        status,
        "photoreal_link_dir",
        lambda root, person_id, person_revision, link_id: m4_dir,
    )
    monkeypatch.setattr(
        status,
        "read_photoreal_link",
        lambda *args, **kwargs: {**_m4_expected(), "production_activation": False},
    )
    monkeypatch.setattr(
        status,
        "build_photoreal_m5_link",
        lambda *args, **kwargs: _m5_expected(),
    )
    monkeypatch.setattr(
        status,
        "photoreal_m5_link_dir",
        lambda root, person_id, person_revision, link_id: m5_dir,
    )
    monkeypatch.setattr(
        status,
        "read_photoreal_m5_link",
        lambda *args, **kwargs: {**_m5_expected(), "photoreal_m5_ready": True},
    )
    monkeypatch.setattr(
        status,
        "build_photoreal_release",
        lambda *args, **kwargs: _release_expected(),
    )
    monkeypatch.setattr(
        status,
        "photoreal_release_dir",
        lambda root, person_id, person_revision, release_id: release_dir,
    )
    monkeypatch.setattr(
        status,
        "read_photoreal_release",
        lambda *args, **kwargs: {
            **_release_expected(),
            "state": "released",
            "photoreal_digital_twin_ready": True,
            "production_activation": True,
        },
    )
    return m4_dir, m5_dir, release_dir


def _inspect(
    composition: Path,
    acceptance: Path,
    library: Path,
    repo: Path,
    binding: Path,
    p3: Path,
) -> dict:
    return status.inspect_photoreal_operator_status(
        composition_authority_dir=composition,
        acceptance_dir=acceptance,
        library_root=library,
        photoreal_person_binding=binding,
        p3_physical_review=p3,
        operator_root=repo,
    )


def test_missing_m4_photoreal_link_points_to_exact_checkout_bound_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    composition, acceptance, library, repo, binding, p3 = _workspace(tmp_path)
    _patch_photoreal(monkeypatch, library=library)
    monkeypatch.setattr(
        status,
        "inspect_operator_status",
        lambda **kwargs: _canonical(repo),
    )
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (REVISION, True))
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))

    result = _inspect(composition, acceptance, library, repo, binding, p3)

    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert before == after
    assert result["read_only"] is True
    assert result["state"] == "required"
    assert result["next_gate"] == "photoreal_m4_link"
    assert result["m4_photoreal_link_ready"] is False
    assert str((repo / "link-photoreal-v2-m4.ps1").resolve()) in result["next_command"]
    assert str(binding.resolve()) in result["next_command"]
    assert str(p3.resolve()) in result["next_command"]
    assert result["production_activation"] is False


def test_checkout_mismatch_suppresses_photoreal_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    composition, acceptance, library, repo, binding, p3 = _workspace(tmp_path)
    _patch_photoreal(monkeypatch, library=library)
    monkeypatch.setattr(status, "inspect_operator_status", lambda **kwargs: _canonical(repo))
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (OTHER_REVISION, True))

    result = _inspect(composition, acceptance, library, repo, binding, p3)

    assert result["state"] == "blocked"
    assert result["next_gate"] == "operator-checkout"
    assert result["next_command"] is None
    assert OTHER_REVISION in result["message"]
    assert REVISION in result["message"]


def test_existing_m4_link_defers_to_canonical_m5_when_needed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    composition, acceptance, library, repo, binding, p3 = _workspace(tmp_path)
    m4_dir, _m5_dir, _release_dir = _patch_photoreal(monkeypatch, library=library)
    m4_dir.mkdir(parents=True)
    monkeypatch.setattr(
        status,
        "inspect_operator_status",
        lambda **kwargs: _canonical(
            repo,
            state="required",
            m5_ready=False,
            next_gate="digital_twin_platform_acceptance",
            next_command="CANONICAL-M5",
        ),
    )

    result = _inspect(composition, acceptance, library, repo, binding, p3)

    assert result["m4_photoreal_link_ready"] is True
    assert result["state"] == "required"
    assert result["next_gate"] == "digital_twin_platform_acceptance"
    assert result["next_command"] == "CANONICAL-M5"


def test_complete_canonical_m5_points_to_photoreal_m5_link(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    composition, acceptance, library, repo, binding, p3 = _workspace(tmp_path)
    m4_dir, _m5_dir, _release_dir = _patch_photoreal(monkeypatch, library=library)
    m4_dir.mkdir(parents=True)
    monkeypatch.setattr(
        status,
        "inspect_operator_status",
        lambda **kwargs: _canonical(
            repo,
            state="required",
            m5_ready=True,
            ready=False,
            next_gate="digital_twin_final_release",
            next_command="CANONICAL-M6",
        ),
    )
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (REVISION, True))

    result = _inspect(composition, acceptance, library, repo, binding, p3)

    assert result["m4_photoreal_link_ready"] is True
    assert result["photoreal_m5_ready"] is False
    assert result["next_gate"] == "photoreal_m5_link"
    assert str((repo / "link-photoreal-v2-m5.ps1").resolve()) in result["next_command"]


def test_complete_photoreal_m5_defers_to_missing_canonical_m6(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    composition, acceptance, library, repo, binding, p3 = _workspace(tmp_path)
    m4_dir, m5_dir, _release_dir = _patch_photoreal(monkeypatch, library=library)
    m4_dir.mkdir(parents=True)
    m5_dir.mkdir(parents=True)
    monkeypatch.setattr(
        status,
        "inspect_operator_status",
        lambda **kwargs: _canonical(
            repo,
            state="required",
            m5_ready=True,
            ready=False,
            next_gate="digital_twin_final_release",
            next_command="CANONICAL-M6",
        ),
    )

    result = _inspect(composition, acceptance, library, repo, binding, p3)

    assert result["photoreal_m5_ready"] is True
    assert result["state"] == "required"
    assert result["next_gate"] == "digital_twin_final_release"
    assert result["next_command"] == "CANONICAL-M6"


def test_complete_canonical_m6_points_to_final_photoreal_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    composition, acceptance, library, repo, binding, p3 = _workspace(tmp_path)
    m4_dir, m5_dir, _release_dir = _patch_photoreal(monkeypatch, library=library)
    m4_dir.mkdir(parents=True)
    m5_dir.mkdir(parents=True)
    canonical_m6 = library / "canonical-m6" / CANONICAL_RELEASE_ID
    canonical_m6.mkdir(parents=True)
    authority_path = canonical_m6 / "authority.json"
    _write_json(authority_path, {"release_id": CANONICAL_RELEASE_ID})
    monkeypatch.setattr(
        status,
        "inspect_operator_status",
        lambda **kwargs: _canonical(
            repo,
            state="complete",
            m5_ready=True,
            ready=True,
            next_gate="complete",
            next_command=None,
            m6_authority_path=str(authority_path),
        ),
    )
    monkeypatch.setattr(status, "_git_checkout_state", lambda root: (REVISION, True))

    result = _inspect(composition, acceptance, library, repo, binding, p3)

    assert result["canonical_digital_twin_ready"] is True
    assert result["photoreal_digital_twin_ready"] is False
    assert result["next_gate"] == "photoreal_m6_release"
    assert str((repo / "finalize-photoreal-digital-twin.ps1").resolve()) in result["next_command"]
    assert str(canonical_m6.resolve()) in result["next_command"]


def test_existing_final_photoreal_release_is_strict_readback_complete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    composition, acceptance, library, repo, binding, p3 = _workspace(tmp_path)
    m4_dir, m5_dir, release_dir = _patch_photoreal(monkeypatch, library=library)
    m4_dir.mkdir(parents=True)
    m5_dir.mkdir(parents=True)
    release_dir.mkdir(parents=True)
    canonical_m6 = library / "canonical-m6" / CANONICAL_RELEASE_ID
    canonical_m6.mkdir(parents=True)
    authority_path = canonical_m6 / "authority.json"
    _write_json(authority_path, {"release_id": CANONICAL_RELEASE_ID})
    monkeypatch.setattr(
        status,
        "inspect_operator_status",
        lambda **kwargs: _canonical(
            repo,
            state="complete",
            m5_ready=True,
            ready=True,
            next_gate="complete",
            next_command=None,
            m6_authority_path=str(authority_path),
        ),
    )

    result = _inspect(composition, acceptance, library, repo, binding, p3)

    assert result["state"] == "complete"
    assert result["next_gate"] == "complete"
    assert result["next_command"] is None
    assert result["m4_photoreal_link_ready"] is True
    assert result["photoreal_m5_ready"] is True
    assert result["photoreal_digital_twin_ready"] is True
    assert result["production_activation"] is True


def test_invalid_photoreal_preflight_fails_closed_without_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    composition, acceptance, library, repo, binding, p3 = _workspace(tmp_path)
    monkeypatch.setattr(status, "inspect_operator_status", lambda **kwargs: _canonical(repo))
    monkeypatch.setattr(
        status,
        "build_photoreal_link",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            DigitalTwinPhotorealLinkError("fixture drift")
        ),
    )

    result = _inspect(composition, acceptance, library, repo, binding, p3)

    assert result["state"] == "invalid"
    assert result["next_gate"] == "photoreal_m4_link"
    assert result["next_command"] is None
    assert "fixture drift" in result["message"]


def test_cli_uses_blocked_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        status_cli,
        "inspect_photoreal_operator_status",
        lambda **kwargs: {"state": "blocked", "read_only": True},
    )
    code = status_cli.main(
        [
            "--composition-authority-dir",
            "composition",
            "--acceptance-dir",
            "acceptance",
            "--photoreal-person-binding",
            "binding.json",
            "--p3-physical-review",
            "p3.json",
        ]
    )
    assert code == 3
    assert json.loads(capsys.readouterr().out)["state"] == "blocked"


def test_powershell_status_wrapper_is_evidence_read_only() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "photoreal-digital-twin-status.ps1").read_text(encoding="utf-8")
    assert "bodyrig.photoreal_digital_twin_operator_status_cli" in source
    assert '"--operator-root", $repoRoot' in source
    assert "$env:PYTHONPATH = $repoRoot" in source
    for mutation in (
        "Set-Content",
        "Out-File",
        "New-Item",
        "Move-Item",
        "Remove-Item",
        "Copy-Item",
    ):
        assert mutation not in source
