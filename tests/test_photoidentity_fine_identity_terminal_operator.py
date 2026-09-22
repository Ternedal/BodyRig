from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.photoidentity_fine_identity_operator as subject


JOB_ID = "hfpreview-" + "a" * 32


def _operator_root() -> Path:
    return Path(subject.__file__).resolve().parents[1]


def test_operator_runs_exact_registered_terminal_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sweep = tmp_path / "sweep"
    sweep.mkdir()
    (sweep / "private-fine-identity-review-manifest.json").write_text("{}", encoding="utf-8")
    (sweep / "photoidentity-fine-identity-attestation.json").write_text("{}", encoding="utf-8")
    config = tmp_path / "adapter.json"
    config.write_text("{}", encoding="utf-8")
    source_package = tmp_path / "hfn.mrbody"
    source_package.write_bytes(b"hfn")
    fine_root = tmp_path / "preview" / "continuation" / "fine-identity-application"
    package_path = fine_root / "package" / "applied.mrbody"

    monkeypatch.setattr(subject, "_git_state", lambda _root: ("1" * 40, True))
    monkeypatch.setattr(
        subject.preview_manager,
        "get",
        lambda _job: {"body_job_id": "body-job-1", "bodyrig_revision": "2" * 40},
    )
    monkeypatch.setattr(
        subject,
        "inspect_source_status",
        lambda *_args, **_kwargs: {
            "stage": "registered",
            "avatar_render_permitted": True,
            "generic_guessing_permitted": False,
            "production_activation": False,
            "body_job_id": "body-job-1",
            "bodyrig_revision": "2" * 40,
        },
    )
    calls = {"status": 0}

    def continuation(_job: str) -> dict:
        calls["status"] += 1
        if calls["status"] == 1:
            return {
                "state": "incomplete",
                "next_gate": {"gate": subject.FINE_IDENTITY_GATE},
                "current_package_path": str(source_package),
            }
        return {
            "state": "complete",
            "next_gate": None,
            "current_package_path": str(package_path),
            "current_package_sha256": "3" * 64,
            "high_fidelity_complete": True,
            "production_ready": False,
            "production_activation": False,
            "gates": [{"id": subject.FINE_IDENTITY_GATE, "state": "pass"}],
        }

    monkeypatch.setattr(subject, "inspect_continuation", continuation)
    monkeypatch.setattr(
        subject,
        "continuation_paths",
        lambda _job: {"fine_identity": fine_root},
    )

    reconstruction_calls: list[dict] = []
    materialize_calls: list[dict] = []

    def run_reconstruction(**kwargs):
        reconstruction_calls.append(kwargs)
        Path(kwargs["output_dir"]).mkdir(parents=True)

    def materialize_application(**kwargs):
        materialize_calls.append(kwargs)
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True)
        (output / "applied.mrbody").write_bytes(b"applied")

    monkeypatch.setattr(subject, "run_reconstruction", run_reconstruction)
    monkeypatch.setattr(subject, "materialize_application", materialize_application)

    result = subject.apply_terminal_fine_identity(
        preview_job_id=JOB_ID,
        sweep_root=sweep,
        adapter_config=config,
        operator_root=_operator_root(),
    )

    assert result["state"] == "complete"
    assert result["production_activation"] is False
    assert len(reconstruction_calls) == 1
    assert reconstruction_calls[0]["source_package_path"] == source_package.resolve()
    assert reconstruction_calls[0]["operator_bodyrig_revision"] == "1" * 40
    assert materialize_calls[0]["reconstruction_workspace"] == fine_root / "reconstruction"
    assert package_path.is_file()


def test_operator_cleans_partial_terminal_workspace_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sweep = tmp_path / "sweep"
    sweep.mkdir()
    (sweep / "private-fine-identity-review-manifest.json").write_text("{}", encoding="utf-8")
    (sweep / "photoidentity-fine-identity-attestation.json").write_text("{}", encoding="utf-8")
    config = tmp_path / "adapter.json"
    config.write_text("{}", encoding="utf-8")
    source_package = tmp_path / "hfn.mrbody"
    source_package.write_bytes(b"hfn")
    fine_root = tmp_path / "preview" / "continuation" / "fine-identity-application"

    monkeypatch.setattr(subject, "_git_state", lambda _root: ("1" * 40, True))
    monkeypatch.setattr(
        subject.preview_manager,
        "get",
        lambda _job: {"body_job_id": "body-job-1", "bodyrig_revision": "2" * 40},
    )
    monkeypatch.setattr(
        subject,
        "inspect_source_status",
        lambda *_args, **_kwargs: {
            "stage": "registered",
            "avatar_render_permitted": True,
            "generic_guessing_permitted": False,
            "production_activation": False,
            "body_job_id": "body-job-1",
            "bodyrig_revision": "2" * 40,
        },
    )
    monkeypatch.setattr(
        subject,
        "inspect_continuation",
        lambda _job: {
            "state": "incomplete",
            "next_gate": {"gate": subject.FINE_IDENTITY_GATE},
            "current_package_path": str(source_package),
        },
    )
    monkeypatch.setattr(
        subject,
        "continuation_paths",
        lambda _job: {"fine_identity": fine_root},
    )

    def run_reconstruction(**kwargs):
        Path(kwargs["output_dir"]).mkdir(parents=True)

    monkeypatch.setattr(subject, "run_reconstruction", run_reconstruction)
    monkeypatch.setattr(
        subject,
        "materialize_application",
        lambda **_kwargs: (_ for _ in ()).throw(
            subject.PhotoIdentityFineIdentityPackageError("final audit failed")
        ),
    )

    with pytest.raises(subject.PhotoIdentityFineIdentityPackageError, match="final audit failed"):
        subject.apply_terminal_fine_identity(
            preview_job_id=JOB_ID,
            sweep_root=sweep,
            adapter_config=config,
            operator_root=_operator_root(),
        )

    assert not fine_root.exists()




@pytest.mark.parametrize(
    "final_state",
    [
        ("1" * 40, False),
        ("4" * 40, True),
    ],
)
def test_operator_requires_same_clean_git_state_after_terminal_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_state: tuple[str, bool],
) -> None:
    sweep = tmp_path / "sweep"
    sweep.mkdir()
    (sweep / "private-fine-identity-review-manifest.json").write_text("{}", encoding="utf-8")
    (sweep / "photoidentity-fine-identity-attestation.json").write_text("{}", encoding="utf-8")
    config = tmp_path / "adapter.json"
    config.write_text("{}", encoding="utf-8")
    source_package = tmp_path / "hfn.mrbody"
    source_package.write_bytes(b"hfn")
    fine_root = tmp_path / "preview" / "continuation" / "fine-identity-application"

    git_states = iter([
        ("1" * 40, True),
        final_state,
    ])
    monkeypatch.setattr(subject, "_git_state", lambda _root: next(git_states))
    monkeypatch.setattr(
        subject.preview_manager,
        "get",
        lambda _job: {"body_job_id": "body-job-1", "bodyrig_revision": "2" * 40},
    )
    monkeypatch.setattr(
        subject,
        "inspect_source_status",
        lambda *_args, **_kwargs: {
            "stage": "registered",
            "avatar_render_permitted": True,
            "generic_guessing_permitted": False,
            "production_activation": False,
            "body_job_id": "body-job-1",
            "bodyrig_revision": "2" * 40,
        },
    )
    monkeypatch.setattr(
        subject,
        "inspect_continuation",
        lambda _job: {
            "state": "incomplete",
            "next_gate": {"gate": subject.FINE_IDENTITY_GATE},
            "current_package_path": str(source_package),
        },
    )
    monkeypatch.setattr(
        subject,
        "continuation_paths",
        lambda _job: {"fine_identity": fine_root},
    )
    monkeypatch.setattr(
        subject,
        "run_reconstruction",
        lambda **kwargs: Path(kwargs["output_dir"]).mkdir(parents=True),
    )

    def materialize_application(**kwargs):
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True)
        (output / "applied.mrbody").write_bytes(b"applied")

    monkeypatch.setattr(subject, "materialize_application", materialize_application)

    with pytest.raises(
        subject.PhotoIdentityFineIdentityOperatorError,
        match="checkout changed or became dirty",
    ):
        subject.apply_terminal_fine_identity(
            preview_job_id=JOB_ID,
            sweep_root=sweep,
            adapter_config=config,
            operator_root=_operator_root(),
        )

    assert not fine_root.exists()



def test_powershell_operator_has_no_user_revision_and_rechecks_status() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "apply-photoidentity-fine-identity.ps1").read_text(encoding="utf-8")

    assert "BodyRigRevision" not in text
    assert "git -C $repoRoot rev-parse HEAD" in text
    assert "git -C $repoRoot status --porcelain" in text
    assert "bodyrig.photoidentity_fine_identity_operator" in text
    assert '"--preview-job-id", $PreviewJobId' in text
    assert '"--sweep-root", $SweepRoot' in text
    assert '"--adapter-config", $AdapterConfig' in text
    assert "high-fidelity-physical-status.ps1" in text
    assert "Generic fallback: FALSE" in text
    assert "Generative identity synthesis: FALSE" in text
    assert "Production activation: FALSE" in text
