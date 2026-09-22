from __future__ import annotations

import hashlib
import json

import pytest

import bodyrig.photoidentity_fine_identity_adapter as subject


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _config() -> dict[str, object]:
    return {
        "format": subject.CONFIG_FORMAT,
        "version": subject.CONFIG_VERSION,
        "adapter": "pinned-local-fine-identity",
        "revision": "model-revision-1",
        "command": [
            "python",
            "adapter.py",
            "--bodyrig-fine-identity-input",
            "<input>",
            "--bodyrig-fine-identity-output",
            "<output>",
        ],
        "capabilities": {
            "domains": {
                domain: {
                    "geometry": bool(minimum["geometry"]),
                    "appearance": bool(minimum["appearance"]),
                }
                for domain, minimum in subject.APPLICATION_DOMAINS.items()
            },
            "source_grounded": True,
            "generative_identity_synthesis": False,
            "preserves_rig": True,
            "preserves_source_derived_dental_identity": True,
            "preserves_hfn_authority": True,
        },
        "timeout_seconds": 3600,
    }


def test_adapter_config_requires_exact_source_grounded_non_generative_capabilities() -> None:
    value = subject.validate_adapter_config(_config())
    assert set(value["capabilities"]["domains"]) == set(subject.APPLICATION_DOMAINS)
    assert "oral_teeth_detail" not in value["capabilities"]["domains"]

    broken = _config()
    broken["capabilities"]["generative_identity_synthesis"] = True
    with pytest.raises(
        subject.PhotoIdentityFineIdentityAdapterError,
        match="may not use generative identity synthesis",
    ):
        subject.validate_adapter_config(broken)


def test_application_source_evidence_reconciles_private_and_public_bytes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "a" * 40
    marker = tmp_path / "markers.json"
    marker.write_bytes(b'{"review":"complete"}')
    marker_sha = _sha(marker.read_bytes())

    entries: list[dict[str, object]] = []
    selected: list[dict[str, object]] = []
    for domain_index, domain in enumerate(subject.APPLICATION_DOMAINS):
        for scene_index in range(2):
            reference = f"{domain}-{scene_index}"
            source = tmp_path / f"source-{domain_index}-{scene_index}.bin"
            review = tmp_path / f"review-{domain_index}-{scene_index}.png"
            source.write_bytes(f"source-{reference}".encode())
            review.write_bytes(f"review-{reference}".encode())
            entry = {
                "reference": reference,
                "domain": domain,
                "scene_id": f"scene-{domain_index}-{scene_index}",
                "region": f"region-{domain_index}",
                "source_ordinal": domain_index * 10 + scene_index,
                "source_media_path": str(source),
                "source_media_sha256": _sha(source.read_bytes()),
                "review_image_path": str(review),
                "review_image_sha256": _sha(review.read_bytes()),
                "source_quality": 0.95,
            }
            entries.append(entry)
            selected.append(
                {field: entry[field] for field in subject.PUBLIC_ENTRY_FIELDS}
            )

    manifest = {
        "format": subject.PRIVATE_FORMAT,
        "version": subject.PRIVATE_VERSION,
        "performer_id": "42",
        "bodyrig_revision": revision,
        "anatomy_observation_evidence_sha256": "b" * 64,
        "anatomy_sufficiency_report_sha256": "c" * 64,
        "private_source_manifest_set_sha256": "d" * 64,
        "marker_inventory_path": str(marker),
        "marker_inventory_sha256": marker_sha,
        "entries": entries,
    }
    manifest_path = tmp_path / "private.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    attestation_path = tmp_path / "attestation.json"
    attestation_path.write_text("{}", encoding="utf-8")

    attestation = {
        "performer_id": "42",
        "bodyrig_revision": revision,
        "selected_evidence": selected,
        "marker_inventory_sha256": marker_sha,
        "source_grounded": True,
        "generic_guessing_permitted": False,
    }
    monkeypatch.setattr(subject, "read_attestation", lambda *_args, **_kwargs: dict(attestation))

    loaded_attestation, loaded_manifest, grouped = subject.load_application_source_evidence(
        private_manifest_path=manifest_path,
        attestation_path=attestation_path,
        bodyrig_revision=revision,
    )
    assert loaded_attestation["performer_id"] == "42"
    assert loaded_manifest["marker_inventory_sha256"] == marker_sha
    assert set(grouped) == set(subject.APPLICATION_DOMAINS)
    assert all(len(items) == 2 for items in grouped.values())


def test_application_source_evidence_rejects_review_image_drift(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "a" * 40
    marker = tmp_path / "markers.json"
    marker.write_bytes(b"markers")
    marker_sha = _sha(marker.read_bytes())

    entries: list[dict[str, object]] = []
    selected: list[dict[str, object]] = []
    first_review = None
    for domain_index, domain in enumerate(subject.APPLICATION_DOMAINS):
        for scene_index in range(2):
            reference = f"{domain}-{scene_index}"
            source = tmp_path / f"s-{domain_index}-{scene_index}.bin"
            review = tmp_path / f"r-{domain_index}-{scene_index}.png"
            source.write_bytes(reference.encode())
            review.write_bytes(("review-" + reference).encode())
            if first_review is None:
                first_review = review
            entry = {
                "reference": reference,
                "domain": domain,
                "scene_id": f"scene-{domain_index}-{scene_index}",
                "region": "review-region",
                "source_ordinal": domain_index * 10 + scene_index,
                "source_media_path": str(source),
                "source_media_sha256": _sha(source.read_bytes()),
                "review_image_path": str(review),
                "review_image_sha256": _sha(review.read_bytes()),
                "source_quality": 0.95,
            }
            entries.append(entry)
            selected.append({field: entry[field] for field in subject.PUBLIC_ENTRY_FIELDS})

    manifest = {
        "format": subject.PRIVATE_FORMAT,
        "version": subject.PRIVATE_VERSION,
        "performer_id": "42",
        "bodyrig_revision": revision,
        "anatomy_observation_evidence_sha256": "b" * 64,
        "anatomy_sufficiency_report_sha256": "c" * 64,
        "private_source_manifest_set_sha256": "d" * 64,
        "marker_inventory_path": str(marker),
        "marker_inventory_sha256": marker_sha,
        "entries": entries,
    }
    manifest_path = tmp_path / "private.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    attestation_path = tmp_path / "attestation.json"
    attestation_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        subject,
        "read_attestation",
        lambda *_args, **_kwargs: {
            "performer_id": "42",
            "bodyrig_revision": revision,
            "selected_evidence": selected,
            "marker_inventory_sha256": marker_sha,
            "source_grounded": True,
            "generic_guessing_permitted": False,
        },
    )

    assert first_review is not None
    first_review.write_bytes(b"tampered")
    with pytest.raises(
        subject.PhotoIdentityFineIdentityAdapterError,
        match="review image hash drifted",
    ):
        subject.load_application_source_evidence(
            private_manifest_path=manifest_path,
            attestation_path=attestation_path,
            bodyrig_revision=revision,
        )
