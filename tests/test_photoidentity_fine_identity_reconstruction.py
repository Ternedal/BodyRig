from __future__ import annotations

import hashlib
import json

import pytest

import bodyrig.photoidentity_fine_identity_reconstruction as subject


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _prepared(tmp_path) -> dict[str, object]:
    source_avatar = tmp_path / "source-avatar.vrm"
    source_avatar.write_bytes(b"source-avatar")
    return {
        "source_avatar_path": str(source_avatar),
        "operator_bodyrig_revision": "a" * 40,
        "requirement_bodyrig_revision": "b" * 40,
        "performer_id": "42",
        "fine_identity_authority_sha256": "c" * 64,
        "fine_identity_attestation_sha256": "d" * 64,
        "source_package_sha256": "e" * 64,
        "source_avatar_sha256": _sha(b"source-avatar"),
        "source_references": {
            domain: [f"{domain}-1", f"{domain}-2"]
            for domain in (
                "chest_breast_shape_detail",
                "nipple_areola_detail",
                "intimate_anatomy_detail",
                "distinctive_markers_detail",
            )
        },
        "marker_inventory_sha256": "f" * 64,
    }


def _result(prepared: dict[str, object], candidate_sha: str, input_sha: str) -> dict[str, object]:
    return {
        "format": subject.RESULT_FORMAT,
        "version": subject.RESULT_VERSION,
        "adapter": "adapter",
        "adapter_revision": "adapter-r1",
        "operator_bodyrig_revision": prepared["operator_bodyrig_revision"],
        "requirement_bodyrig_revision": prepared["requirement_bodyrig_revision"],
        "performer_id": prepared["performer_id"],
        "input_manifest_sha256": input_sha,
        "fine_identity_authority_sha256": prepared["fine_identity_authority_sha256"],
        "fine_identity_attestation_sha256": prepared["fine_identity_attestation_sha256"],
        "source_package_sha256": prepared["source_package_sha256"],
        "source_avatar_sha256": prepared["source_avatar_sha256"],
        "candidate_vrm_sha256": candidate_sha,
        "source_references": prepared["source_references"],
        "marker_inventory_sha256": prepared["marker_inventory_sha256"],
        "source_grounded": True,
        "generative_identity_synthesis": False,
        "rig_preserved": True,
        "authority_metadata_preserved": True,
        "geometry_modified": True,
        "appearance_modified": True,
        "human_review_required": True,
        "package_application_authority": False,
        "production_activation": False,
    }


def test_validate_adapter_result_proves_rig_and_authority_preservation(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared(tmp_path)
    candidate = tmp_path / "candidate.vrm"
    candidate.write_bytes(b"candidate-avatar")
    input_manifest = tmp_path / "input.json"
    input_manifest.write_text("{}", encoding="utf-8")
    result_path = tmp_path / "result.json"

    source_fp = {
        "rig_sha256": "1" * 64,
        "geometry_surface_sha256": "2" * 64,
        "appearance_global_sha256": "3" * 64,
    }
    candidate_fp = {
        "rig_sha256": "1" * 64,
        "geometry_surface_sha256": "4" * 64,
        "appearance_global_sha256": "5" * 64,
    }
    monkeypatch.setattr(
        subject,
        "_avatar_fingerprints",
        lambda value: source_fp if value == b"source-avatar" else candidate_fp,
    )
    monkeypatch.setattr(
        subject,
        "_protected_payload_fingerprints",
        lambda _value: {
            "hair": "1" * 64,
            "eyes": "2" * 64,
            "face_secondary": "3" * 64,
            "hfn_base_color": "4" * 64,
        },
    )
    monkeypatch.setattr(subject, "_bodyrig_metadata", lambda _value: {"authority": "same"})

    result = _result(prepared, _sha(candidate.read_bytes()), _sha(input_manifest.read_bytes()))
    result_path.write_text(json.dumps(result), encoding="utf-8")

    validated = subject.validate_adapter_result(
        result_path=result_path,
        candidate_vrm_path=candidate,
        input_manifest_path=input_manifest,
        config={"adapter": "adapter", "revision": "adapter-r1"},
        prepared=prepared,
    )
    assert validated["rig_preserved"] is True
    assert validated["geometry_modified"] is True
    assert validated["appearance_modified"] is True
    assert validated["package_application_authority"] is False
    assert validated["production_activation"] is False


def test_validate_adapter_result_rejects_candidate_self_granted_application(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared(tmp_path)
    candidate = tmp_path / "candidate.vrm"
    candidate.write_bytes(b"candidate-avatar")
    input_manifest = tmp_path / "input.json"
    input_manifest.write_text("{}", encoding="utf-8")
    result_path = tmp_path / "result.json"

    monkeypatch.setattr(
        subject,
        "_avatar_fingerprints",
        lambda value: {
            "rig_sha256": "1" * 64,
            "geometry_surface_sha256": ("2" if value == b"source-avatar" else "4") * 64,
            "appearance_global_sha256": ("3" if value == b"source-avatar" else "5") * 64,
        },
    )

    def metadata(value: bytes) -> dict[str, object]:
        if value == b"source-avatar":
            return {"authority": "same"}
        return {"authority": "same", "fineIdentityApplication": {"forged": True}}

    monkeypatch.setattr(
        subject,
        "_protected_payload_fingerprints",
        lambda _value: {
            "hair": "1" * 64,
            "eyes": "2" * 64,
            "face_secondary": "3" * 64,
            "hfn_base_color": "4" * 64,
        },
    )
    monkeypatch.setattr(subject, "_bodyrig_metadata", metadata)
    result_path.write_text(
        json.dumps(_result(prepared, _sha(candidate.read_bytes()), _sha(input_manifest.read_bytes()))),
        encoding="utf-8",
    )

    with pytest.raises(
        subject.PhotoIdentityFineIdentityReconstructionError,
        match="may not self-grant",
    ):
        subject.validate_adapter_result(
            result_path=result_path,
            candidate_vrm_path=candidate,
            input_manifest_path=input_manifest,
            config={"adapter": "adapter", "revision": "adapter-r1"},
            prepared=prepared,
        )


def test_validate_adapter_result_rejects_rig_drift(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared(tmp_path)
    candidate = tmp_path / "candidate.vrm"
    candidate.write_bytes(b"candidate-avatar")
    input_manifest = tmp_path / "input.json"
    input_manifest.write_text("{}", encoding="utf-8")
    result_path = tmp_path / "result.json"

    monkeypatch.setattr(
        subject,
        "_avatar_fingerprints",
        lambda value: {
            "rig_sha256": ("1" if value == b"source-avatar" else "9") * 64,
            "geometry_surface_sha256": ("2" if value == b"source-avatar" else "4") * 64,
            "appearance_global_sha256": ("3" if value == b"source-avatar" else "5") * 64,
        },
    )
    monkeypatch.setattr(
        subject,
        "_protected_payload_fingerprints",
        lambda _value: {
            "hair": "1" * 64,
            "eyes": "2" * 64,
            "face_secondary": "3" * 64,
            "hfn_base_color": "4" * 64,
        },
    )
    monkeypatch.setattr(subject, "_bodyrig_metadata", lambda _value: {"authority": "same"})
    result_path.write_text(
        json.dumps(_result(prepared, _sha(candidate.read_bytes()), _sha(input_manifest.read_bytes()))),
        encoding="utf-8",
    )

    with pytest.raises(
        subject.PhotoIdentityFineIdentityReconstructionError,
        match="changed canonical rig authority",
    ):
        subject.validate_adapter_result(
            result_path=result_path,
            candidate_vrm_path=candidate,
            input_manifest_path=input_manifest,
            config={"adapter": "adapter", "revision": "adapter-r1"},
            prepared=prepared,
        )

def test_validate_adapter_result_rejects_protected_payload_drift(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared(tmp_path)
    candidate = tmp_path / "candidate.vrm"
    candidate.write_bytes(b"candidate-avatar")
    input_manifest = tmp_path / "input.json"
    input_manifest.write_text("{}", encoding="utf-8")
    result_path = tmp_path / "result.json"

    monkeypatch.setattr(
        subject,
        "_avatar_fingerprints",
        lambda value: {
            "rig_sha256": "1" * 64,
            "geometry_surface_sha256": ("2" if value == b"source-avatar" else "4") * 64,
            "appearance_global_sha256": ("3" if value == b"source-avatar" else "5") * 64,
        },
    )
    monkeypatch.setattr(
        subject,
        "_protected_payload_fingerprints",
        lambda value: {
            "hair": "1" * 64,
            "eyes": "2" * 64,
            "face_secondary": ("3" if value == b"source-avatar" else "9") * 64,
            "hfn_base_color": "4" * 64,
        },
    )
    monkeypatch.setattr(subject, "_bodyrig_metadata", lambda _value: {"authority": "same"})
    result_path.write_text(
        json.dumps(_result(prepared, _sha(candidate.read_bytes()), _sha(input_manifest.read_bytes()))),
        encoding="utf-8",
    )

    with pytest.raises(
        subject.PhotoIdentityFineIdentityReconstructionError,
        match="changed protected promoted payloads: face_secondary",
    ):
        subject.validate_adapter_result(
            result_path=result_path,
            candidate_vrm_path=candidate,
            input_manifest_path=input_manifest,
            config={"adapter": "adapter", "revision": "adapter-r1"},
            prepared=prepared,
        )

