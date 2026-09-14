from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.fidelity_component_gap_executor as executor


REVISION = "a" * 40
PERSON = "person-" + "1" * 32
BODY_REVISION = "body-r0007"
BODY_ID = "body-" + "b" * 32
PACKAGE_BYTES = b"package"
PACKAGE_SHA = hashlib.sha256(PACKAGE_BYTES).hexdigest()
CAPTURE = "hfncap-" + "2" * 32


def _plan() -> dict:
    return {
        "format": "bodyrig-fidelity-component-gap-plan",
        "version": 1,
        "bodyrig_revision": REVISION,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "state": "composition-required",
        "drawable_components": [],
        "missing_components": ["fingernails", "toenails"],
        "next_actions": [{
            "id": "source-bound-hfn-continuation",
            "components": ["fingernails", "toenails"],
            "operator_input_required": True,
            "implementation_required": False,
            "reason": "source-bound HFN continuation required",
        }],
        "strict_machine_scoring_ready": False,
        "human_visual_authority_required": True,
        "production_activation": False,
        "semantics": "physical-component-gap-planning-not-visual-or-release-acceptance",
    }


def _setup(tmp_path: Path) -> tuple[Path, dict[str, str], Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "prepare-hands-feet-nails-detail-candidate.ps1").write_text("exit 0\n", encoding="utf-8")
    package = tmp_path / "source.mrbody"
    package.write_bytes(PACKAGE_BYTES)
    root = tmp_path / "people"
    root.mkdir()
    uv_path = (
        root
        / "hands-feet-nails-uv-domain-evidence"
        / PERSON
        / BODY_REVISION
        / CAPTURE
        / ("c" * 40 + ".json")
    )
    uv_path.parent.mkdir(parents=True)
    uv_path.write_bytes(b"exact uv evidence")
    context = {
        "package_path": str(package),
        "hfn_root": str(root),
        "person_id": PERSON,
        "body_revision": BODY_REVISION,
        "hfn_render_dir": str(root / "render"),
        "hfn_human_review_dir": str(root / "review"),
    }
    return repo, context, package, uv_path


def _source_stop(package: Path) -> dict:
    return {
        "actions": {
            executor.HFN_CANDIDATE_GATE: {
                "gate": executor.HFN_CANDIDATE_GATE,
                "command": ".\\prepare-hands-feet-nails-detail-candidate.ps1 -CaptureId <CAPTURE_ID> -UvEvidence <UV_EVIDENCE_PATH>",
                "operator_input_required": True,
                "reason": "select exact HFN source evidence",
            }
        },
        "package_path": package,
        "package_sha256": PACKAGE_SHA,
    }


def _authority(uv_path: Path) -> dict[str, str]:
    return {
        "capture_id": CAPTURE,
        "uv_evidence_path": str(uv_path.resolve()),
        "uv_evidence_sha256": hashlib.sha256(uv_path.read_bytes()).hexdigest(),
        "source_capture_sha256": "d" * 64,
        "landmark_evidence_sha256": "e" * 64,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
    }


def test_unique_existing_hfn_authority_becomes_exact_machine_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo, context, package, uv_path = _setup(tmp_path)
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: _source_stop(package))
    monkeypatch.setattr(
        executor,
        "find_reusable_hfn_source_uv_authorities",
        lambda *args, **kwargs: [_authority(uv_path)],
    )

    result = executor.build_execution(_plan(), context=context, repo_root=repo)

    assert result["mode"] == "machine-executable"
    assert result["operator_input_required"] is False
    assert result["hfn_substep"] == "detail-candidate"
    assert result["hfn_reused_existing_source_uv_authority"] is True
    assert result["reprobe_required_after_execution"] is True
    assert result["human_visual_authority_required"] is True
    assert result["production_activation"] is False
    command = result["commands"][0]
    assert command[3] == str(repo / "prepare-hands-feet-nails-detail-candidate.ps1")
    assert "<CAPTURE_ID>" not in command
    assert "<UV_EVIDENCE_PATH>" not in command
    assert command[command.index("-CaptureId") + 1] == CAPTURE
    assert command[command.index("-UvEvidence") + 1] == str(uv_path.resolve())
    assert command[command.index("-PackagePath") + 1] == str(package.resolve())


@pytest.mark.parametrize("match_count", [0, 2])
def test_zero_or_multiple_existing_hfn_chains_keep_operator_stop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    match_count: int,
) -> None:
    repo, context, package, uv_path = _setup(tmp_path)
    stop = _source_stop(package)
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: stop)
    matches = [] if match_count == 0 else [_authority(uv_path), dict(_authority(uv_path))]
    monkeypatch.setattr(
        executor,
        "find_reusable_hfn_source_uv_authorities",
        lambda *args, **kwargs: matches,
    )

    result = executor.build_execution(_plan(), context=context, repo_root=repo)

    assert result["mode"] == "operator-stop"
    assert result["operator_input_required"] is True
    assert result["commands"] == []
    assert "<CAPTURE_ID>" in result["operator_command"]
    assert "<UV_EVIDENCE_PATH>" in result["operator_command"]
    assert result["reprobe_required_after_execution"] is False
    assert result["production_activation"] is False


def test_reused_uv_bytes_are_rechecked_after_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo, context, package, uv_path = _setup(tmp_path)
    authority = _authority(uv_path)
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: _source_stop(package))
    monkeypatch.setattr(
        executor,
        "find_reusable_hfn_source_uv_authorities",
        lambda *args, **kwargs: [authority],
    )
    uv_path.write_bytes(b"changed after discovery")

    with pytest.raises(executor.FidelityComponentGapExecutionError, match="UV evidence bytes changed"):
        executor.build_execution(_plan(), context=context, repo_root=repo)


def test_reused_authority_must_bind_exact_gap_body_and_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo, context, package, uv_path = _setup(tmp_path)
    monkeypatch.setattr(executor, "inspect_hfn_continuation", lambda **_kwargs: _source_stop(package))
    wrong_body = {**_authority(uv_path), "body_id": "body-" + "f" * 32}
    monkeypatch.setattr(
        executor,
        "find_reusable_hfn_source_uv_authorities",
        lambda *args, **kwargs: [wrong_body],
    )
    with pytest.raises(executor.FidelityComponentGapExecutionError, match="different canonical body"):
        executor.build_execution(_plan(), context=context, repo_root=repo)
