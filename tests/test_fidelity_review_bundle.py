from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.fidelity_review_bundle import FidelityReviewBundleError, SNAPSHOTS, build_review_bundle


def _render(root: Path, marker: str) -> Path:
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True)
    for name, _ in SNAPSHOTS:
        (snapshots / name).write_bytes(f"png:{marker}:{name}".encode())
    (snapshots / "fidelity-render-set.json").write_text(
        json.dumps({"format": "bodyrig-fidelity-render-set", "version": 1, "marker": marker}),
        encoding="utf-8",
    )
    return root


def _evidence(path: Path, *, clean: bool = True) -> Path:
    value = {
        "format": "bodyrig-fidelity-ab-evidence",
        "version": 1,
        "left": {
            "package_sha256": "1" * 64,
            "geometry_surface_sha256": "2" * 64,
        },
        "right": {
            "package_sha256": "3" * 64,
            "geometry_surface_sha256": "2" * 64,
        },
        "invariants": {
            "body_id_identical": True,
            "bodyprint_identical": True,
            "geometry_identical": True,
            "skin_binding_identical": True,
            "rig_identical": True,
            "appearance_identical": False,
            "appearance_changed": True,
            "clean_appearance_ab": clean,
        },
        "human_visual_authority_required": True,
        "comparison_only": True,
        "production_activation": False,
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_review_bundle_builds_three_column_create_only_page(tmp_path: Path) -> None:
    historical = _render(tmp_path / "historical", "historical")
    pr40 = _render(tmp_path / "pr40", "pr40")
    pr41 = _render(tmp_path / "pr41", "pr41")
    evidence = _evidence(tmp_path / "ab.json")
    output = tmp_path / "review"

    index = build_review_bundle(
        historical_render=historical,
        pr40_render=pr40,
        pr41_render=pr41,
        ab_evidence=evidence,
        output_dir=output,
    )

    assert index == output / "index.html"
    text = index.read_text(encoding="utf-8")
    assert "Historical bad baseline" in text
    assert "#40 · donor topology" in text
    assert "#41 · seam-aware UV" in text
    assert "Human review remains authoritative" in text
    assert "production activation remains false" in text
    for prefix in ("historical", "pr40", "pr41"):
        for name, _ in SNAPSHOTS:
            assert (output / f"{prefix}-{name}").is_file()
    assert (output / "fidelity-ab-evidence.json").is_file()

    with pytest.raises(FidelityReviewBundleError, match="already exists"):
        build_review_bundle(
            historical_render=historical,
            pr40_render=pr40,
            pr41_render=pr41,
            ab_evidence=evidence,
            output_dir=output,
        )


def test_review_bundle_refuses_non_clean_ab_evidence(tmp_path: Path) -> None:
    historical = _render(tmp_path / "historical", "historical")
    pr40 = _render(tmp_path / "pr40", "pr40")
    pr41 = _render(tmp_path / "pr41", "pr41")
    evidence = _evidence(tmp_path / "ab.json", clean=False)
    with pytest.raises(FidelityReviewBundleError, match="clean appearance A/B"):
        build_review_bundle(
            historical_render=historical,
            pr40_render=pr40,
            pr41_render=pr41,
            ab_evidence=evidence,
            output_dir=tmp_path / "review",
        )


def test_review_bundle_refuses_missing_canonical_snapshot(tmp_path: Path) -> None:
    historical = _render(tmp_path / "historical", "historical")
    pr40 = _render(tmp_path / "pr40", "pr40")
    pr41 = _render(tmp_path / "pr41", "pr41")
    (pr41 / "snapshots" / "face-front.png").unlink()
    evidence = _evidence(tmp_path / "ab.json")
    with pytest.raises(FidelityReviewBundleError, match="canonical snapshot missing"):
        build_review_bundle(
            historical_render=historical,
            pr40_render=pr40,
            pr41_render=pr41,
            ab_evidence=evidence,
            output_dir=tmp_path / "review",
        )
