from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import bodyrig.high_fidelity_physical_acceptance_audit as audit
from bodyrig.high_fidelity_release_gate import CANONICAL_RELEASE_CHECKS


JOB_ID = "hfpreview-" + "a" * 32
BODY_ID = "bodyid-" + "1" * 24
BODY_JOB_ID = "job-" + "2" * 32
REVISION = "c" * 40
SOURCE_REVISION = "b" * 40
SOURCE_PACKAGE_SHA = "d" * 64
BODYPRINT_SHA = "e" * 64


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _fixture(monkeypatch, tmp_path: Path, *, state: str = "ready", gate_name: str = "windows-probe", production: bool = False):
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-promoted-package")
    package_sha = _hash(package)

    acceptance = tmp_path / "physical-acceptance"
    acceptance.mkdir()
    accepted = acceptance / f"{BODY_ID}.mrbody"
    accepted.write_bytes(package.read_bytes())

    review = acceptance / "review.json"
    review.write_text("{}\n", encoding="utf-8")
    session = acceptance / "bodyrig-physical-clone-session.json"
    readiness = acceptance / "bodyrig-rig-readiness.json"
    skin = acceptance / "bodyrig-skin-qa.json"
    topology = acceptance / "bodyrig-mesh-topology-qa.json"
    runtime = acceptance / "runtime" / "runtime-manifest.json"
    session.write_bytes(b"source-session")
    readiness.write_bytes(b"source-readiness")
    skin.write_bytes(b"fresh-skin")
    topology.write_bytes(b"fresh-topology")
    runtime.parent.mkdir()
    runtime.write_bytes(b"fresh-runtime")

    source = tmp_path / "source-gate-a"
    source.mkdir()
    source_session = source / "bodyrig-physical-clone-session.json"
    source_readiness = source / "bodyrig-rig-readiness.json"
    source_gate_path = source / "bodyrig-acceptance.json"
    source_session.write_bytes(session.read_bytes())
    source_readiness.write_bytes(readiness.read_bytes())
    source_gate_path.write_bytes(b"source-gate-a-authority")
    source_gate_sha = _hash(source_gate_path)

    receipt = {
        "format": audit.FORMAT,
        "version": audit.VERSION,
        "previewJobId": JOB_ID,
        "bodyJobId": BODY_JOB_ID,
        "canonicalBodyId": BODY_ID,
        "bodyrigRevision": REVISION,
        "sourceGateABodyRigRevision": SOURCE_REVISION,
        "sourceGateASha256": source_gate_sha,
        "sourcePackageSha256": SOURCE_PACKAGE_SHA,
        "sourcePhysicalSessionSha256": _hash(session),
        "sourceReadinessSha256": _hash(readiness),
        "sourceBodyprintSha256": BODYPRINT_SHA,
        "promotedBodyprintSha256": BODYPRINT_SHA,
        "promotedPackageSha256": package_sha,
        "highFidelityHumanReviewSha256": _hash(review),
        "skinQaSha256": _hash(skin),
        "meshTopologyQaSha256": _hash(topology),
        "runtimeManifestSha256": _hash(runtime),
        "releaseLineageReproved": True,
        "physicalAcceptanceAuthority": False,
        "productionActivation": False,
    }
    receipt_path = acceptance / audit.RECEIPT_NAME
    _write(receipt_path, receipt)

    gate = {
        "bodyrig_checkout_clean": True,
        "source_count": 3,
        "physical_clone": {
            "session_sha256": _hash(session),
            "readiness_sha256": _hash(readiness),
            "mode": "stash-sith-high-fidelity",
        },
        "skin_qa": {"report_sha256": _hash(skin)},
        "mesh_topology_qa": {"report_sha256": _hash(topology)},
        "recovery": {
            "adapter": "recoverer",
            "revision": "recovery-v1",
            "track_id": "track-1",
            "observed_frames": 4,
        },
        "package": {
            "vrm_spec_version": "1.0",
            "placeholder_avatar": False,
            "bodyprint_matches_proof": True,
            "source_count_matches": True,
            "recovery_provenance_matches": True,
            "avatar_fitting_provenance_present": True,
        },
        "runtime": {
            "manifest": "runtime/runtime-manifest.json",
            "manifest_sha256": _hash(runtime),
            "materialized_from_package": True,
        },
        "high_fidelity_handoff": {
            "receipt_sha256": _hash(receipt_path),
            "source_gate_a_sha256": source_gate_sha,
            "source_bodyprint_sha256": BODYPRINT_SHA,
            "promoted_bodyprint_sha256": BODYPRINT_SHA,
            "release_lineage_reproved": True,
            "package_sha256": package_sha,
            "human_review_sha256": _hash(review),
            "preview_job_id": JOB_ID,
            "body_job_id": BODY_JOB_ID,
        },
        "checks": {name: True for name in CANONICAL_RELEASE_CHECKS},
    }
    gate_path = acceptance / "bodyrig-acceptance.json"
    _write(gate_path, gate)

    base = {
        "state": state,
        "gate": gate_name,
        "acceptance_dir": str(acceptance),
        "body_id": BODY_ID,
        "bodyrig_revision": REVISION,
        "message": "canonical physical status",
        "next_command": None if state == "complete" else ".\\next.ps1",
        "production_activation": production,
    }
    monkeypatch.setattr(audit, "physical_acceptance_status", lambda *_args, **_kwargs: dict(base))
    monkeypatch.setattr(audit, "physical_acceptance_dir", lambda _job: acceptance)
    monkeypatch.setattr(
        audit,
        "inspect_acceptance_dir",
        lambda _path: SimpleNamespace(state=state, gate=gate_name, message="canonical physical status"),
    )
    monkeypatch.setattr(audit, "apply_reference_policy", lambda status: status)
    monkeypatch.setattr(audit, "human_review_path", lambda *_args, **_kwargs: review)
    monkeypatch.setattr(audit, "read_human_review", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        audit,
        "_validate_gate_a",
        lambda _path: SimpleNamespace(
            package_hash=package_sha,
            body_id=BODY_ID,
            revision=REVISION,
            runtime_hash=_hash(runtime),
        ),
    )
    source_report = {
        "source_count": 3,
        "physical_clone": {
            "session_sha256": _hash(source_session),
            "readiness_sha256": _hash(source_readiness),
        },
    }
    source_gate = SimpleNamespace(
        path=source_gate_path,
        body_id=BODY_ID,
        revision=SOURCE_REVISION,
        package_hash=SOURCE_PACKAGE_SHA,
    )
    monkeypatch.setattr(
        audit,
        "_source_gate",
        lambda _job: (
            {"canonical_body_id": BODY_ID},
            {"job_id": BODY_JOB_ID},
            source,
            source_gate,
            source_report,
        ),
    )
    monkeypatch.setattr(
        audit,
        "validate_promoted_release_lineage",
        lambda *_args, **_kwargs: {
            "source_count": 3,
            "recovery": {
                "adapter": "recoverer",
                "revision": "recovery-v1",
                "track_id": "track-1",
                "observed_frames": 4,
            },
            "vrm_spec_version": "1.0",
            "source_bodyprint_sha256": BODYPRINT_SHA,
            "bodyprint_sha256": BODYPRINT_SHA,
        },
    )
    return SimpleNamespace(
        package=package,
        package_sha=package_sha,
        acceptance=acceptance,
        receipt=receipt_path,
        gate=gate_path,
        runtime=runtime,
        source_gate=source_gate_path,
        base=base,
    )


def _status(fixture):
    return audit.audited_physical_acceptance_status(
        JOB_ID,
        package_path=fixture.package,
        package_sha256=fixture.package_sha,
    )


def test_valid_transitive_authority_preserves_canonical_state(monkeypatch, tmp_path: Path) -> None:
    fixture = _fixture(monkeypatch, tmp_path)
    result = _status(fixture)
    assert result == fixture.base


def test_reference_policy_block_fails_closed_before_physical_state_is_exposed(monkeypatch, tmp_path: Path) -> None:
    fixture = _fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(
        audit,
        "apply_reference_policy",
        lambda _status: SimpleNamespace(
            state="blocked",
            gate="reference-contract",
            message="renderer evidence drifted from renderer-contract.json",
        ),
    )

    result = _status(fixture)

    assert result["state"] == "invalid"
    assert result["gate"] == "physical-gate-a"
    assert result["next_command"] is None
    assert result["production_activation"] is False
    assert "reference-contract" in result["message"]
    assert "renderer-contract" in result["message"]


def test_runtime_tamper_fails_closed_before_windows_state_is_exposed(monkeypatch, tmp_path: Path) -> None:
    fixture = _fixture(monkeypatch, tmp_path)
    fixture.runtime.write_bytes(b"tampered-runtime")
    result = _status(fixture)
    assert result["state"] == "invalid"
    assert result["gate"] == "physical-gate-a"
    assert result["next_command"] is None
    assert result["production_activation"] is False
    assert "runtime" in result["message"].lower()


def test_gate_a_extension_must_bind_exact_handoff_receipt(monkeypatch, tmp_path: Path) -> None:
    fixture = _fixture(monkeypatch, tmp_path)
    gate = json.loads(fixture.gate.read_text(encoding="utf-8"))
    gate["high_fidelity_handoff"]["receipt_sha256"] = "0" * 64
    _write(fixture.gate, gate)
    result = _status(fixture)
    assert result["state"] == "invalid"
    assert result["production_activation"] is False
    assert "receipt" in result["message"].lower()


def test_source_gate_lineage_is_revalidated_on_every_status_read(monkeypatch, tmp_path: Path) -> None:
    fixture = _fixture(monkeypatch, tmp_path)
    fixture.source_gate.write_bytes(b"mutated-source-gate-a")
    result = _status(fixture)
    assert result["state"] == "invalid"
    assert result["production_activation"] is False
    assert "source gate a" in result["message"].lower()


def test_release_check_tamper_fails_closed(monkeypatch, tmp_path: Path) -> None:
    fixture = _fixture(monkeypatch, tmp_path)
    gate = json.loads(fixture.gate.read_text(encoding="utf-8"))
    gate["checks"]["bodyprint_matches_package"] = False
    _write(fixture.gate, gate)
    result = _status(fixture)
    assert result["state"] == "invalid"
    assert result["gate"] == "physical-gate-a"
    assert result["production_activation"] is False
    assert "release" in result["message"].lower() or "bodyprint" in result["message"].lower()


def test_tamper_revokes_even_apparently_complete_release(monkeypatch, tmp_path: Path) -> None:
    fixture = _fixture(monkeypatch, tmp_path, state="complete", gate_name="release", production=True)
    fixture.runtime.write_bytes(b"tampered-after-release")
    result = _status(fixture)
    assert result["state"] == "invalid"
    assert result["gate"] == "physical-gate-a"
    assert result["production_activation"] is False


def test_missing_gate_a_required_state_is_not_reinterpreted(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "promoted.mrbody"
    package.write_bytes(b"exact-promoted-package")
    package_sha = _hash(package)
    required = {
        "state": "required",
        "gate": "physical-gate-a",
        "acceptance_dir": str(tmp_path / "physical-acceptance"),
        "message": "fresh Gate A required",
        "next_command": ".\\prepare-high-fidelity-physical-acceptance.ps1",
        "production_activation": False,
    }
    monkeypatch.setattr(audit, "physical_acceptance_status", lambda *_args, **_kwargs: dict(required))
    result = audit.audited_physical_acceptance_status(
        JOB_ID,
        package_path=package,
        package_sha256=package_sha,
    )
    assert result == required
