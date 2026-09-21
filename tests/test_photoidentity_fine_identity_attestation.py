from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoidentity_fine_identity_attestation as subject


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    anatomy_obs = tmp_path / "photoidentity-observations.json"
    anatomy_report = tmp_path / "photoidentity-evidence.json"
    marker = tmp_path / "markers.private.json"

    entries = []
    selected = []
    ordinal = 0
    for domain in subject.REQUIRED_DOMAINS:
        for index in (1, 2):
            ordinal += 1
            scene_id = f"{domain}-scene-{index}"
            media = tmp_path / f"{domain}-{index}.mp4"
            image = tmp_path / f"{domain}-{index}.png"
            media.write_bytes(f"media-{domain}-{index}".encode())
            image.write_bytes(f"image-{domain}-{index}".encode())
            entries.append(
                {
                    "reference": f"{domain}-ref-{index}",
                    "domain": domain,
                    "scene_id": scene_id,
                    "region": f"{domain}-region",
                    "source_ordinal": ordinal,
                    "source_media_path": str(media.resolve()),
                    "source_media_sha256": _sha(media),
                    "review_image_path": str(image.resolve()),
                    "review_image_sha256": _sha(image),
                    "source_quality": 0.91,
                }
            )
            selected.append(
                {
                    "scene_id": scene_id,
                    "scene_title": scene_id,
                    "path": str(media.resolve()),
                    "width": 1920,
                    "height": 1080,
                    "duration": 60.0,
                    "framerate": 30.0,
                    "performer_count": 1,
                    "score": 100.0,
                }
            )

    batch = tmp_path / "private-batches" / "batch-0001"
    batch.mkdir(parents=True)
    source_manifest = {
        "format": "bodyrig-stash-source-manifest",
        "version": 1,
        "source_kind": "stash-local",
        "performer": {"id": "42", "name": "Fixture", "disambiguation": ""},
        "stash_version": "test",
        "candidate_count": len(selected),
        "selected": selected,
    }
    (batch / "bodyrig-stash-source-manifest.json").write_text(
        json.dumps(source_manifest),
        encoding="utf-8",
    )
    _, manifest_set_sha = subject._private_source_bindings(tmp_path, expected_count=len(selected))

    anatomy_obs.write_text(
        json.dumps({"performer_id": "42", "bodyrig_revision": "a" * 40}),
        encoding="utf-8",
    )
    anatomy_report.write_text(
        json.dumps(
            {
                "performer_id": "42",
                "bodyrig_revision": "a" * 40,
                "source_files_scanned": len(selected),
            }
        ),
        encoding="utf-8",
    )

    marker_refs = [
        entry["reference"] for entry in entries if entry["domain"] == "distinctive_markers_detail"
    ]
    marker.write_text(
        json.dumps(
            {
                "format": subject.MARKER_INVENTORY_FORMAT,
                "version": subject.MARKER_INVENTORY_VERSION,
                "reviewed_regions": sorted(subject.REQUIRED_MARKER_REVIEW_REGIONS),
                "markers": [
                    {
                        "marker_id": "marker-1",
                        "kind": "mole",
                        "region": "left_arm",
                        "laterality": "left",
                        "source_references": marker_refs,
                    }
                ],
                "complete_body_marker_review": True,
                "generic_guessing_permitted": False,
            }
        ),
        encoding="utf-8",
    )
    manifest = {
        "format": subject.PRIVATE_FORMAT,
        "version": subject.PRIVATE_VERSION,
        "performer_id": "42",
        "bodyrig_revision": "a" * 40,
        "anatomy_observation_evidence_sha256": _sha(anatomy_obs),
        "anatomy_sufficiency_report_sha256": _sha(anatomy_report),
        "private_source_manifest_set_sha256": manifest_set_sha,
        "marker_inventory_path": str(marker.resolve()),
        "marker_inventory_sha256": _sha(marker),
        "entries": entries,
    }
    manifest_path = tmp_path / "private-fine-review.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, anatomy_obs, anatomy_report, marker


def _record(tmp_path: Path, **overrides: object) -> dict:
    manifest, obs, report, _ = _fixture(tmp_path)
    kwargs = dict(
        sweep_root=tmp_path,
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


def _record_direct(
    *,
    root: Path,
    manifest: Path,
    observations: Path,
    report: Path,
    output: Path,
) -> dict:
    return subject.record_attestation(
        sweep_root=root,
        private_manifest=manifest,
        anatomy_observations=observations,
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
        _record_direct(root=tmp_path, manifest=manifest_path, observations=obs, report=report, output=tmp_path / "out.json")


def test_rejects_changed_source_bytes(tmp_path: Path) -> None:
    manifest_path, obs, report, _ = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    Path(manifest["entries"][0]["source_media_path"]).write_bytes(b"tampered")
    with pytest.raises(subject.PhotoIdentityFineIdentityAttestationError, match="source media bytes changed"):
        _record_direct(root=tmp_path, manifest=manifest_path, observations=obs, report=report, output=tmp_path / "out.json")


def test_rejects_source_path_swap_even_if_private_manifest_hash_is_updated(tmp_path: Path) -> None:
    manifest_path, obs, report, _ = _fixture(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    first = manifest["entries"][0]
    second = manifest["entries"][1]
    first["source_media_path"] = second["source_media_path"]
    first["source_media_sha256"] = second["source_media_sha256"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(subject.PhotoIdentityFineIdentityAttestationError, match="source path does not match exact sweep"):
        _record_direct(root=tmp_path, manifest=manifest_path, observations=obs, report=report, output=tmp_path / "out.json")


def test_create_only_output(tmp_path: Path) -> None:
    _record(tmp_path)
    other = tmp_path / "other"
    manifest, obs, report, _ = _fixture(other)
    output = tmp_path / "photoidentity-fine-identity-attestation.json"
    with pytest.raises(subject.PhotoIdentityFineIdentityAttestationError, match="already exists"):
        _record_direct(root=other, manifest=manifest, observations=obs, report=report, output=output)
