from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.fidelity_ab_review import CANONICAL_VIEWS, FidelityAbReviewError, build_review

LEFT_REV = "1" * 40
RIGHT_REV = "2" * 40
RENDERER_REV = "3" * 40
LEFT_PACKAGE = "4" * 64
RIGHT_PACKAGE = "5" * 64
BODY_ID = "bodyid-" + "a" * 24


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ab_evidence(tmp_path: Path, *, version: object = 1) -> Path:
    path = tmp_path / "ab.json"
    _write_json(
        path,
        {
            "format": "bodyrig-fidelity-ab-evidence",
            "version": version,
            "left": {
                "file_name": "left.mrbody",
                "body_id": BODY_ID,
                "builder_revision": LEFT_REV,
                "package_sha256": LEFT_PACKAGE,
            },
            "right": {
                "file_name": "right.mrbody",
                "body_id": BODY_ID,
                "builder_revision": RIGHT_REV,
                "package_sha256": RIGHT_PACKAGE,
            },
            "invariants": {"clean_appearance_ab": True},
            "revision_binding": {
                "expected_left_builder_revision": LEFT_REV,
                "expected_right_builder_revision": RIGHT_REV,
                "passed": True,
            },
            "human_visual_authority_required": True,
            "comparison_only": True,
            "production_activation": False,
        },
    )
    return path


def _render_dir(
    tmp_path: Path,
    *,
    name: str,
    package_sha: str,
    comparison_version: object = 1,
    render_set_version: object = 1,
) -> Path:
    root = tmp_path / name
    snapshots = root / "snapshots"
    snapshots.mkdir(parents=True)
    entries = []
    for view in CANONICAL_VIEWS:
        payload = b"\x89PNG\r\n\x1a\n" + name.encode("ascii") + b"-" + view.encode("ascii")
        target = snapshots / f"{view}.png"
        target.write_bytes(payload)
        entries.append(
            {
                "view": view,
                "file": f"{view}.png",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "width": 1024,
                "height": 1024,
            }
        )
    _write_json(
        root / "comparison-authority.json",
        {
            "format": "bodyrig-fidelity-comparison-authority",
            "version": comparison_version,
            "authority": "validated-package-comparison-only",
            "bodyrig_revision": RENDERER_REV,
            "runtime_manifest_sha256": "6" * 64,
            "package_sha256": package_sha,
            "physical_acceptance_authority": False,
            "comparison_only": True,
            "production_activation": False,
        },
    )
    _write_json(
        snapshots / "fidelity-render-set.json",
        {
            "format": "bodyrig-fidelity-render-set",
            "version": render_set_version,
            "body_id": BODY_ID,
            "package_sha256": package_sha,
            "semantics": "visual-fidelity-not-identity-verification",
            "snapshots": entries,
        },
    )
    return root


def _build(
    tmp_path: Path,
    *,
    ab_version: object = 1,
    left_comparison_version: object = 1,
    right_comparison_version: object = 1,
    left_render_set_version: object = 1,
    right_render_set_version: object = 1,
) -> dict:
    ab = _ab_evidence(tmp_path, version=ab_version)
    left = _render_dir(
        tmp_path,
        name="left-render",
        package_sha=LEFT_PACKAGE,
        comparison_version=left_comparison_version,
        render_set_version=left_render_set_version,
    )
    right = _render_dir(
        tmp_path,
        name="right-render",
        package_sha=RIGHT_PACKAGE,
        comparison_version=right_comparison_version,
        render_set_version=right_render_set_version,
    )
    return build_review(
        ab_evidence=ab,
        left_render_dir=left,
        right_render_dir=right,
        decision="right",
        quality_note="Right preserves the intended appearance without changing authority semantics.",
        expected_renderer_revision=RENDERER_REV,
    )


def test_review_rejects_boolean_machine_ab_version(tmp_path: Path) -> None:
    with pytest.raises(FidelityAbReviewError, match="fidelity A/B evidence format/version mismatch"):
        _build(tmp_path, ab_version=True)


def test_review_rejects_boolean_comparison_authority_version(tmp_path: Path) -> None:
    with pytest.raises(FidelityAbReviewError, match="left comparison authority format/version mismatch"):
        _build(tmp_path, left_comparison_version=True)


def test_review_rejects_boolean_render_set_version_on_right_path(tmp_path: Path) -> None:
    with pytest.raises(FidelityAbReviewError, match="right render-set format/version mismatch"):
        _build(tmp_path, right_render_set_version=True)


def test_review_accepts_numeric_float_v1_versions_and_preserves_authority(tmp_path: Path) -> None:
    value = _build(
        tmp_path,
        ab_version=1.0,
        left_comparison_version=1.0,
        right_comparison_version=1.0,
        left_render_set_version=1.0,
        right_render_set_version=1.0,
    )

    assert value["decision"] == "right"
    assert value["human_visual_review_confirmed"] is True
    assert value["comparison_only"] is True
    assert value["physical_acceptance_authority"] is False
    assert value["production_activation"] is False
