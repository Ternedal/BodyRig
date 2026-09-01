from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.fidelity_review_bundle import (
    KNOWN_BAD_PACKAGE_SHA256,
    FidelityReviewBundleError,
    SNAPSHOTS,
    build_review_bundle,
)

PR40_SHA = "1" * 64
PR41_SHA = "3" * 64


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render(root: Path, marker: str, package_sha: str) -> Path:
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True)
    entries = []
    for name, _ in SNAPSHOTS:
        image = snapshots / name
        image.write_bytes(f"png:{marker}:{name}".encode())
        entries.append(
            {
                "view": name.removesuffix(".png"),
                "file": name,
                "width": 1024,
                "height": 1024,
                "sha256": _sha(image),
            }
        )
    (snapshots / "fidelity-render-set.json").write_text(
        json.dumps(
            {
                "format": "bodyrig-fidelity-render-set",
                "version": 1,
                "semantics": "visual-fidelity-not-identity-verification",
                "body_id": "fixture",
                "package_sha256": package_sha,
                "snapshots": entries,
            }
        ),
        encoding="utf-8",
    )
    return root


def _evidence(path: Path, *, clean: bool = True) -> Path:
    value = {
        "format": "bodyrig-fidelity-ab-evidence",
        "version": 1,
        "left": {
            "package_sha256": PR40_SHA,
            "geometry_surface_sha256": "2" * 64,
        },
        "right": {
            "package_sha256": PR41_SHA,
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


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    historical = _render(tmp_path / "historical", "historical", KNOWN_BAD_PACKAGE_SHA256)
    pr40 = _render(tmp_path / "pr40", "pr40", PR40_SHA)
    pr41 = _render(tmp_path / "pr41", "pr41", PR41_SHA)
    evidence = _evidence(tmp_path / "ab.json")
    return historical, pr40, pr41, evidence


def test_review_bundle_builds_three_column_create_only_page(tmp_path: Path) -> None:
    historical, pr40, pr41, evidence = _inputs(tmp_path)
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
    assert "SHA-bound to its renderer manifest/package" in text
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
    historical = _render(tmp_path / "historical", "historical", KNOWN_BAD_PACKAGE_SHA256)
    pr40 = _render(tmp_path / "pr40", "pr40", PR40_SHA)
    pr41 = _render(tmp_path / "pr41", "pr41", PR41_SHA)
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
    historical, pr40, pr41, evidence = _inputs(tmp_path)
    (pr41 / "snapshots" / "face-front.png").unlink()
    with pytest.raises(FidelityReviewBundleError, match="canonical snapshot missing"):
        build_review_bundle(
            historical_render=historical,
            pr40_render=pr40,
            pr41_render=pr41,
            ab_evidence=evidence,
            output_dir=tmp_path / "review",
        )


def test_review_bundle_refuses_snapshot_pixel_tamper(tmp_path: Path) -> None:
    historical, pr40, pr41, evidence = _inputs(tmp_path)
    target = pr41 / "snapshots" / "face-front.png"
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(FidelityReviewBundleError, match="canonical snapshot hash mismatch"):
        build_review_bundle(
            historical_render=historical,
            pr40_render=pr40,
            pr41_render=pr41,
            ab_evidence=evidence,
            output_dir=tmp_path / "review",
        )


def test_review_bundle_refuses_render_set_bound_to_other_package(tmp_path: Path) -> None:
    historical, pr40, pr41, evidence = _inputs(tmp_path)
    manifest_path = pr40 / "snapshots" / "fidelity-render-set.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package_sha256"] = "f" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FidelityReviewBundleError, match="not bound to the expected package bytes"):
        build_review_bundle(
            historical_render=historical,
            pr40_render=pr40,
            pr41_render=pr41,
            ab_evidence=evidence,
            output_dir=tmp_path / "review",
        )
