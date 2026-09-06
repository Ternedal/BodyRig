from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.digital_twin_operator_status as operator
import bodyrig.digital_twin_release_cli as release_cli
from bodyrig.acceptance_status import AcceptanceStatus

PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
BODY_ID = "body-0123456789abcdef0123456789abcdef"
OTHER_BODY_ID = "body-fedcba9876543210fedcba9876543210"
REVISION = "a" * 40
OTHER_REVISION = "b" * 40
RELEASE_ID = "dtrelease-0123456789abcdef0123456789abcdef"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    composition = tmp_path / "composition"
    acceptance = tmp_path / "acceptance"
    library = tmp_path / "custom-library"
    repo = tmp_path / "repo"
    for path in (composition, acceptance, library, repo):
        path.mkdir()
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
        "authority_id": "dtcomp-0123456789abcdef0123456789abcdef",
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "body_id": BODY_ID,
        "bodyrig_revision": REVISION,
    }


def _physical(
    acceptance: Path,
    *,
    state: str = "complete",
    gate: str = "release",
    body_id: str = BODY_ID,
    revision: str = REVISION,
) -> AcceptanceStatus:
    return AcceptanceStatus(
        state=state,
        gate=gate,
        acceptance_dir=str(acceptance),
        body_id=body_id,
        bodyrig_revision=revision,
        message="physical status",
        next_command=".\\physical-next.ps1" if state != "complete" else None,
    )


def _m5(*, windows: str, quest: str, ready: bool = False) -> dict:
    return {
        "format": "bodyrig-digital-twin-platform-status",
        "version": 1,
        "m5_ready": ready,
        "digital_twin_ready": False,
        "production_activation": False,
        "platforms": {
            "windows-unity-univrm": {
                "ready": windows == "complete",
                "state": windows,
                "message": "windows evidence modified" if windows == "invalid" else "windows status",
                "next_command": None,
            },
            "android-quest-class": {
                "ready": quest == "complete",
                "state": quest,
                "message": "quest evidence modified" if quest == "invalid" else "quest status",
                "next_command": None,
            },
        },
        "blockers": [],
        "next_gate": "digital_twin_final_release" if ready else "m5:windows-unity-univrm",
        "message": "M5 status",
    }


def _twin(*, ready: bool, eligible: bool = False) -> dict:
    return {
        "digital_twin_release_eligible": eligible,
        "digital_twin_ready": ready,
        "production_activation": ready,
        "next_gate": "complete" if ready else "digital_twin_final_release",
        "message": "complete" if ready else "composed twin is not ready",
    }


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    acceptance: Path,
    repo: Path,
    physical: AcceptanceStatus,
    m5: dict,
    twin: dict,
) -> None:
    monkeypatch.setattr(operator, "_composition_bundle", lambda *args, **kwargs: (_composition(), b"{}", {}, b"{}"))
    monkeypatch.setattr(operator, "inspect_digital_twin_platform_acceptance", lambda **kwargs: m5)
    monkeypatch.setattr(operator, "inspect_acceptance_dir", lambda path: physical)
    monkeypatch.setattr(operator, "apply_reference_policy", lambda status: status)
    monkeypatch.setattr(operator, "inspect_digital_twin_status", lambda **kwargs: twin)
    monkeypatch.setattr(operator, "_operator_root", lambda value: repo)
    monkeypatch.setattr(operator, "_git_checkout_state", lambda root: (REVISION, True))


def test_other_invalid_m5_platform_blocks_selected_required_platform(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    composition, acceptance, library, repo = _workspace(tmp_path)
    _patch(
        monkeypatch,
        acceptance=acceptance,
        repo=repo,
        physical=_physical(acceptance),
        m5=_m5(windows="required", quest="invalid"),
        twin=_twin(ready=False),
    )

    status = operator.inspect_operator_status(
        composition_authority_dir=composition,
        acceptance_dir=acceptance,
        library_root=library,
        operator_root=repo,
    )

    assert status["state"] == "invalid"
    assert status["next_gate"] == "digital_twin_platform_acceptance"
    assert status["next_command"] is None
    assert "quest evidence modified" in status["message"]


def test_physical_identity_mismatch_blocks_before_physical_next_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    composition, acceptance, library, repo = _workspace(tmp_path)
    _patch(
        monkeypatch,
        acceptance=acceptance,
        repo=repo,
        physical=_physical(acceptance, state="required", gate="windows", body_id=OTHER_BODY_ID),
        m5=_m5(windows="blocked", quest="blocked"),
        twin=_twin(ready=False),
    )

    status = operator.inspect_operator_status(
        composition_authority_dir=composition,
        acceptance_dir=acceptance,
        library_root=library,
        operator_root=repo,
    )

    assert status["state"] == "invalid"
    assert status["next_gate"] == "body_physical_identity"
    assert status["next_command"] is None
    assert OTHER_BODY_ID in status["message"]
    assert BODY_ID in status["message"]


def test_custom_library_root_is_preserved_in_m6_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    composition, acceptance, library, repo = _workspace(tmp_path)
    _patch(
        monkeypatch,
        acceptance=acceptance,
        repo=repo,
        physical=_physical(acceptance),
        m5=_m5(windows="complete", quest="complete", ready=True),
        twin=_twin(ready=False, eligible=True),
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
    assert "-LibraryRoot" in status["next_command"]
    assert str(library.resolve()) in status["next_command"]
    assert status["library_root"] == str(library.resolve())


def test_existing_m6_cannot_force_complete_when_composed_twin_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    composition, acceptance, library, repo = _workspace(tmp_path)
    _patch(
        monkeypatch,
        acceptance=acceptance,
        repo=repo,
        physical=_physical(acceptance),
        m5=_m5(windows="complete", quest="complete", ready=True),
        twin=_twin(ready=False, eligible=True),
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

    status = operator.inspect_operator_status(
        composition_authority_dir=composition,
        acceptance_dir=acceptance,
        library_root=library,
        operator_root=repo,
    )

    assert status["state"] == "invalid"
    assert status["digital_twin_ready"] is False
    assert status["production_activation"] is False
    assert status["next_command"] is None
    assert "not ready" in status["message"]


def test_release_cli_threads_explicit_library_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    custom = tmp_path / "custom-library"
    seen: list[Path] = []

    def write(library: Path, **kwargs: object) -> dict:
        seen.append(Path(library))
        return {
            "release_id": RELEASE_ID,
            "person_id": PERSON_ID,
            "person_revision": PERSON_REVISION,
        }

    def directory(library: Path, **kwargs: object) -> Path:
        seen.append(Path(library))
        return Path(library) / "release"

    monkeypatch.setattr(release_cli, "write_release", write)
    monkeypatch.setattr(release_cli, "release_dir", directory)

    code = release_cli.main(
        [
            "--composition-authority-dir",
            "composition",
            "--acceptance-dir",
            "acceptance",
            "--bodyrig-revision",
            REVISION,
            "--library-root",
            str(custom),
        ]
    )

    assert code == 0
    expected = custom.resolve()
    assert seen == [expected, expected]
    result = json.loads(capsys.readouterr().out)
    assert result["library_root"] == str(expected)


def test_m6_powershell_wrapper_threads_optional_library_root() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "finalize-digital-twin-release.ps1").read_text(encoding="utf-8")
    assert '[string]$LibraryRoot = ""' in source
    assert '"--library-root", $LibraryRoot' in source
