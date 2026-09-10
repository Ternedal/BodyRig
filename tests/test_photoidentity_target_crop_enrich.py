from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import bodyrig.photoidentity_target_crop_enrich as module
from bodyrig.photoidentity_multiperformer_target_attestation import record_target_isolation_attestation
from bodyrig.photoidentity_multiperformer_target_isolation import FORMAT as CANDIDATE_FORMAT, PRIVATE_FORMAT
from bodyrig.photoidentity_target_crop_detail import SCHP_ADAPTER, SCHP_REVISION


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (256, 320), color).save(path, format="PNG", optimize=False)


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "candidates"
    private_root = root / "private-target-source"
    public_rows = []
    private_rows = []
    for index in (1, 2):
        sample_id = f"targetsample-{index:04d}"
        sample_root = private_root / sample_id
        frame = sample_root / "reviewed-source-frame.png"
        crop = sample_root / "target-track-crop.png"
        _png(frame, (20 * index, 30, 40))
        _png(crop, (30 * index, 50, 60))
        public_rows.append({
            "sample_id": sample_id,
            "timestamp_ms": index * 1000,
            "confidence": 0.95,
            "bbox_tlwh": [0.0, 0.0, 256.0, 320.0],
            "crop_ltrb": [0, 0, 256, 320],
            "native_frame_width": 256,
            "native_frame_height": 320,
            "native_crop_width": 256,
            "native_crop_height": 320,
            "source_frame_sha256": _sha(frame),
            "target_crop_sha256": _sha(crop),
        })
        private_rows.append({"sample_id": sample_id, "reviewed_source_frame": str(frame.resolve()), "target_track_crop": str(crop.resolve())})
    private = {
        "format": PRIVATE_FORMAT,
        "version": 1,
        "bodyrig_revision": "b" * 40,
        "performer_id": "42",
        "scene_id": "scene-1",
        "source_media_sha256": "a" * 64,
        "review_root": str((tmp_path / "review").resolve()),
        "source_path": str((tmp_path / "source.mp4").resolve()),
        "track_candidate_id": "trackcand-" + "c" * 32,
        "selected_track_id": "s00-t7",
        "samples": private_rows,
        "source_paths_private": True,
        "production_activation": False,
    }
    private_path = private_root / "private-target-source-index.json"
    private_path.write_text(json.dumps(private, sort_keys=True) + "\n", encoding="utf-8")
    public = {
        "format": CANDIDATE_FORMAT,
        "version": 1,
        "bodyrig_revision": "b" * 40,
        "performer_id": "42",
        "scene_id": "scene-1",
        "source_candidate_id": "multicand-" + "d" * 32,
        "source_media_sha256": "a" * 64,
        "human_track_attestation_sha256": "e" * 64,
        "public_review_manifest_sha256": "f" * 64,
        "private_review_index_sha256": "1" * 64,
        "machine_track_review_sha256": "2" * 64,
        "private_target_source_index_sha256": _sha(private_path),
        "track_candidate_id": "trackcand-" + "c" * 32,
        "selected_track_id": "s00-t7",
        "sample_count": 2,
        "samples": public_rows,
        "target_track_identity_attested": True,
        "source_frames_human_review_bound": True,
        "all_samples_phalp_observed": True,
        "bbox_interpolation_used": False,
        "source_pixels_resized": False,
        "occlusion_removal_used": False,
        "generative_pixels_used": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolation_human_review_required": True,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
    (root / "multiperformer-target-isolation-candidates.json").write_text(json.dumps(public, sort_keys=True) + "\n", encoding="utf-8")
    record_target_isolation_attestation(
        candidate_root=root,
        sample_ids=["targetsample-0001"],
        current_revision="b" * 40,
        quality_note="I reviewed the exact crop and confirmed no other performer contaminates these pixels.",
        confirm_target_isolation=True,
    )
    return root


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, *, schp_domain: str = "hair_hairline") -> None:
    monkeypatch.setattr(module, "inspect_runtime", lambda root: {"runtime_python": str(Path(root) / "python.exe"), "model_path": str(Path(root) / "model.onnx")})
    monkeypatch.setattr(module, "_run_openpose", lambda **kwargs: {"people": []})
    monkeypatch.setattr(module, "_run_schp", lambda **kwargs: [{
        "domain": schp_domain,
        "machine_observability_score": 0.91,
        "source_derived": True,
        "adapter": SCHP_ADAPTER,
        "revision": SCHP_REVISION,
        "source_detail_quality_authority": False,
        "photoidentity_sufficiency_authority": False,
        "metrics": {"test": 1},
    }])


def test_target_crop_enrichment_analyzes_only_human_accepted_subset_and_stays_non_authoritative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _fixture(tmp_path)
    _patch_runtime(monkeypatch)
    out = tmp_path / "enrichment"
    result = module.enrich_target_crops(
        candidate_root=root, output_dir=out, current_revision="b" * 40,
        distribution="Ubuntu-22.04", openpose="/opt/openpose/build/examples/openpose/openpose.bin", wsl_exe="wsl.exe",
        schp_runtime_root=tmp_path / "schp", repo_root=tmp_path,
    )
    assert result["accepted_sample_count"] == 1
    assert [row["sample_id"] for row in result["samples"]] == ["targetsample-0001"]
    assert result["machine_observability_only"] is True
    assert result["source_detail_quality_authority"] is False
    assert result["photoidentity_source_evidence_authority"] is False
    assert result["reconstruction_permitted"] is False
    assert result["production_activation"] is False
    text = Path(result["receipt"]).read_text(encoding="utf-8")
    assert str(tmp_path.resolve()) not in text
    assert "targetsample-0002" not in text


def test_target_crop_enrichment_fails_closed_if_human_accepted_crop_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _fixture(tmp_path)
    crop = root / "private-target-source" / "targetsample-0001" / "target-track-crop.png"
    crop.write_bytes(crop.read_bytes() + b"tamper")
    _patch_runtime(monkeypatch)
    with pytest.raises(module.PhotoIdentityTargetCropEnrichError, match="bytes changed"):
        module.enrich_target_crops(
            candidate_root=root, output_dir=tmp_path / "out", current_revision="b" * 40,
            distribution="Ubuntu-22.04", openpose="/opt/openpose/build/examples/openpose/openpose.bin", wsl_exe="wsl.exe",
            schp_runtime_root=tmp_path / "schp", repo_root=tmp_path,
        )


def test_target_crop_enrichment_rejects_analyzer_domain_overclaim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _fixture(tmp_path)
    _patch_runtime(monkeypatch, schp_domain="torso_chest")
    with pytest.raises(module.PhotoIdentityTargetCropEnrichError, match="overclaimed unsupported domain"):
        module.enrich_target_crops(
            candidate_root=root, output_dir=tmp_path / "out", current_revision="b" * 40,
            distribution="Ubuntu-22.04", openpose="/opt/openpose/build/examples/openpose/openpose.bin", wsl_exe="wsl.exe",
            schp_runtime_root=tmp_path / "schp", repo_root=tmp_path,
        )
