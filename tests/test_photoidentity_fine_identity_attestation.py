from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoidentity_fine_identity_attestation as subject


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    anatomy_obs = tmp_path / "photoidentity-observations.json"
    anatomy_report = tmp_path / "photoidentity-evidence.json"
    anatomy_obs.write_text('{"ok":true}\n', encoding="utf-8")
    anatomy_report.write_text('{"ok":true}\n', encoding="utf-8")
    marker = tmp_path / "markers.private.json"
    marker.write_text('{"markers":[{"kind":"mole","region":"left-shoulder"}]}\n', encoding="utf-8")

    entries = []
    for domain in subject.REQUIRED_DOMAINS:
        for index in (1, 2):
            media = tmp_path / f"{domain}-{index}.mp4"
            image = tmp_path / f"{domain}-{index}.png"
            media.write_bytes(f"media-{domain}-{index}".encode())
            image.write_bytes(f"image-{domain}-{index}".encode())
            entries.append(
                {
                    "reference": f"{domain}-ref-{index}",
                    "domain": domain,
                    "scene_id": f"{domain}-scene-{index}",
                    "region": f"{domain}-region",
                    "source_media_path": str(media),
                    "source_media_sha256": _sha(media),
                    "review_image_path": str(image),
                    "review_image_sha256": _sha(image),
                    "source_quality": 0.91,
                }
            )
    manifest = {
        "format": subject.PRIVATE_FORMAT,
        "version": subject.PRIVATE_VERSION,
        "performer_id": "42",
        "bodyrig_revision": "a" * 40,
        "anatomy_observation_evidence_sha256": _sha(anatomy_obs),
        "anatomy_sufficiency_report_sha256": _sha(anatomy_report),
        "marker_inventory_path": str(marker),
        "marker_inventory_sha256": _sha(marker),
        "entries": entries,
    }
    manifest_path = tmp_path / "private-fine-review.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, anatomy_obs, anatomy_report, marker


def _record(tmp_path: Path, **overrides: object) -> dict:
    manifest, obs, report, _ = _fixture(tmp_path)
    kwargs = dict(
        private_manifest=manifest,
        anatomy_observations=obs,
        anatomy_report=report,
        reviewed_by="human-reviewer",
        quality_note="Reviewed exact source-grounded fine identity detail for photoidentical reconstruction.",
        confirm_oral_teeth_photoidentity=True,
        confirm_chest_breast_shape_photoidentity=True,
        confirm_nipple_areola_photoidentity=True,
        confirm_intimate_anatomy_photoidentity=True,
        confirm_distinctive_markers_photoidentity=True,
        output=tmp_path / "photoidentity-fine-identity-attestation.json",
    )
    kwargs.update(overrides)
    return subject.record_attestation(**kwargs)


def test_records_all_required_photoidentical_domains_without_private_paths(tmp_path: Path) -> None:
    result = _record(tmp_path)
    assert set(result["attested_domains"]) == set(subject.REQUIRED_DOMAINS)
    assert result["source_grounded"] is True
    assert result["photoidentical_identity_detail_required"] is True
    assert result["generic_guessing_permitted"] is False
    assert result["reconstruction_permitted"] is False
    serialized = json.dumps(result)
    assert "source_media_path" not in serialized
    assert "review_image_path" not in serialized
    assert "marker_inventory_path" not in serialized
    assert "chest_breast_shape_detail" in serialized
    assert "nipple_areola_detail" in serialized
    assert "intimate_anatomy_detail" in serialized


@pytest.mark.parametrize(
    "field",
    [
        "confirm_oral_teeth_photoidentity",
        "confirm_chest_breast_shape_photoidentity",
        "confirm_nipple_areola_photoidentity",
        "confirm_intimate_anatomy_photoidentity",
        "confirm_distinctive_markers_photoidentity",
    ],
)
def test_each_human_confirmation_is_mandatory(tmp_path: Path, field: str) -> None:
    with pytest.raises(subject.PhotoIdentityFineIdentityAttestationError, match="missing confirmations"):
        _record(tmp_path, **{field: False})


def test_rejects_single_scene_domain(tmp_path: Path) -> None:
    manifest_path, obs, report, _ = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"] = [
        entry
        for entry in manifest["entries"]
        if not (entry["domain"] == "oral_teeth_detail" and entry["scene_id"].endswith("-2"))
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(subject.PhotoIdentityFineIdentityAttestationError, match="oral_teeth_detail requires at least 2"):
        subject.record_attestation(
            private_manifest=manifest_path,
            anatomy_observations=obs,
            anatomy_report=report,
            reviewed_by="reviewer",
            quality_note="Reviewed exact source detail and found insufficient oral coverage.",
            confirm_oral_teeth_photoidentity=True,
            confirm_chest_breast_shape_photoidentity=True,
            confirm_nipple_areola_photoidentity=True,
            confirm_intimate_anatomy_photoidentity=True,
            confirm_distinctive_markers_photoidentity=True,
            output=tmp_path / "out.json",
        )


def test_rejects_changed_source_bytes(tmp_path: Path) -> None:
    manifest_path, obs, report, _ = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    Path(manifest["entries"][0]["source_media_path"]).write_bytes(b"tampered")
    with pytest.raises(subject.PhotoIdentityFineIdentityAttestationError, match="source media bytes changed"):
        subject.record_attestation(
            private_manifest=manifest_path,
            anatomy_observations=obs,
            anatomy_report=report,
            reviewed_by="reviewer",
            quality_note="Reviewed exact source-grounded fine identity detail for photoidentical reconstruction.",
            confirm_oral_teeth_photoidentity=True,
            confirm_chest_breast_shape_photoidentity=True,
            confirm_nipple_areola_photoidentity=True,
            confirm_intimate_anatomy_photoidentity=True,
            confirm_distinctive_markers_photoidentity=True,
            output=tmp_path / "out.json",
        )


def test_create_only_output(tmp_path: Path) -> None:
    _record(tmp_path)
    manifest, obs, report, _ = _fixture(tmp_path / "other")
    output = tmp_path / "photoidentity-fine-identity-attestation.json"
    with pytest.raises(subject.PhotoIdentityFineIdentityAttestationError, match="already exists"):
        subject.record_attestation(
            private_manifest=manifest,
            anatomy_observations=obs,
            anatomy_report=report,
            reviewed_by="reviewer",
            quality_note="Reviewed exact source-grounded fine identity detail for photoidentical reconstruction.",
            confirm_oral_teeth_photoidentity=True,
            confirm_chest_breast_shape_photoidentity=True,
            confirm_nipple_areola_photoidentity=True,
            confirm_intimate_anatomy_photoidentity=True,
            confirm_distinctive_markers_photoidentity=True,
            output=output,
        )
