from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.fidelity_ab_review import (
    CANONICAL_VIEWS,
    FidelityAbReviewError,
    build_review,
    main,
)

LEFT_REV = "1" * 40
RIGHT_REV = "2" * 40
RENDERER_REV = "3" * 40
LEFT_PACKAGE = "4" * 64
RIGHT_PACKAGE = "5" * 64


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ab_evidence(tmp_path: Path) -> Path:
    path = tmp_path / "ab.json"
    _write_json(
        path,
        {
            "format": "bodyrig-fidelity-ab-evidence",
            "version": 1,
            "left": {
                "file_name": "left.mrbody",
                "body_id": "bodyid-" + "a" * 24,
                "builder_revision": LEFT_REV,
                "package_sha256": LEFT_PACKAGE,
            },
            "right": {
                "file_name": "right.mrbody",
                "body_id": "bodyid-" + "a" * 24,
                "builder_revision": RIGHT_REV,
                "package_sha256": RIGHT_PACKAGE,
            },
            "invariants": {
                "body_id_identical": True,
                "bodyprint_identical": True,
                "geometry_identical": True,
                "skin_binding_identical": True,
                "rig_identical": True,
                "appearance_identical": False,
                "appearance_changed": True,
                "clean_appearance_ab": True,
            },
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
    renderer_revision: str = RENDERER_REV,
    authority: str = "validated-package-comparison-only",
    physical_acceptance_authority: bool = False,
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
    body_id = "bodyid-" + "a" * 24
    _write_json(
        snapshots / "fidelity-render-set.json",
        {
            "format": "bodyrig-fidelity-render-set",
            "version": 1,
            "body_id": body_id,
            "package_sha256": package_sha,
            "semantics": "visual-fidelity-not-identity-verification",
            "snapshots": entries,
        },
    )
    _write_json(
        root / "comparison-authority.json",
        {
            "format": "bodyrig-fidelity-comparison-authority",
            "version": 1,
            "authority": authority,
            "bodyrig_revision": renderer_revision,
            "runtime_manifest_sha256": "6" * 64,
            "package_sha256": package_sha,
            "physical_acceptance_authority": physical_acceptance_authority,
            "comparison_only": True,
            "production_activation": False,
        },
    )
    return root


def test_review_binds_machine_ab_packages_renderer_and_snapshot_bytes(tmp_path: Path) -> None:
    ab = _ab_evidence(tmp_path)
    left = _render_dir(tmp_path, name="left-render", package_sha=LEFT_PACKAGE)
    right = _render_dir(tmp_path, name="right-render", package_sha=RIGHT_PACKAGE)

    value = build_review(
        ab_evidence=ab,
        left_render_dir=left,
        right_render_dir=right,
        decision="right",
        quality_note="Candidate preserves skin tone while removing the plastic highlight amplification.",
    )

    assert value["decision"] == "right"
    assert value["preferred_side"] == "right"
    assert value["renderer_revision"] == RENDERER_REV
    assert value["left"]["builder_revision"] == LEFT_REV
    assert value["right"]["builder_revision"] == RIGHT_REV
    assert value["left"]["package_sha256"] == LEFT_PACKAGE
    assert value["right"]["package_sha256"] == RIGHT_PACKAGE
    assert [entry["view"] for entry in value["left"]["snapshots"]] == list(CANONICAL_VIEWS)
    assert [entry["view"] for entry in value["right"]["snapshots"]] == list(CANONICAL_VIEWS)
    for side in ("left", "right"):
        assert all(len(entry["sha256"]) == 64 for entry in value[side]["snapshots"])
    assert value["clean_appearance_ab_verified"] is True
    assert value["human_visual_review_confirmed"] is True
    assert value["directional_preference_recorded"] is True
    assert value["comparison_only"] is True
    assert value["physical_acceptance_authority"] is False
    assert value["production_activation"] is False


def test_review_rejects_snapshot_tampering(tmp_path: Path) -> None:
    ab = _ab_evidence(tmp_path)
    left = _render_dir(tmp_path, name="left-render", package_sha=LEFT_PACKAGE)
    right = _render_dir(tmp_path, name="right-render", package_sha=RIGHT_PACKAGE)
    (right / "snapshots" / "face-front.png").write_bytes(b"tampered")

    with pytest.raises(FidelityAbReviewError, match="snapshot bytes changed"):
        build_review(
            ab_evidence=ab,
            left_render_dir=left,
            right_render_dir=right,
            decision="right",
            quality_note="Candidate is better.",
        )


def test_review_rejects_different_renderer_revisions(tmp_path: Path) -> None:
    ab = _ab_evidence(tmp_path)
    left = _render_dir(tmp_path, name="left-render", package_sha=LEFT_PACKAGE)
    right = _render_dir(
        tmp_path,
        name="right-render",
        package_sha=RIGHT_PACKAGE,
        renderer_revision="7" * 40,
    )

    with pytest.raises(FidelityAbReviewError, match="different BodyRig revisions"):
        build_review(
            ab_evidence=ab,
            left_render_dir=left,
            right_render_dir=right,
            decision="right",
            quality_note="Candidate is better.",
        )


def test_review_rejects_gate_a_or_physical_render_authority(tmp_path: Path) -> None:
    ab = _ab_evidence(tmp_path)
    left = _render_dir(
        tmp_path,
        name="left-render",
        package_sha=LEFT_PACKAGE,
        authority="gate-a-pending-candidate",
        physical_acceptance_authority=True,
    )
    right = _render_dir(tmp_path, name="right-render", package_sha=RIGHT_PACKAGE)

    with pytest.raises(FidelityAbReviewError, match="not direct package comparison evidence"):
        build_review(
            ab_evidence=ab,
            left_render_dir=left,
            right_render_dir=right,
            decision="right",
            quality_note="Candidate is better.",
        )


def test_tie_is_non_directional_preference(tmp_path: Path) -> None:
    ab = _ab_evidence(tmp_path)
    left = _render_dir(tmp_path, name="left-render", package_sha=LEFT_PACKAGE)
    right = _render_dir(tmp_path, name="right-render", package_sha=RIGHT_PACKAGE)

    value = build_review(
        ab_evidence=ab,
        left_render_dir=left,
        right_render_dir=right,
        decision="tie",
        quality_note="No reliable visual preference across the four canonical views.",
    )
    assert value["preferred_side"] is None
    assert value["directional_preference_recorded"] is False


def test_left_preference_is_recorded_without_claiming_candidate_semantics(tmp_path: Path) -> None:
    ab = _ab_evidence(tmp_path)
    left = _render_dir(tmp_path, name="left-render", package_sha=LEFT_PACKAGE)
    right = _render_dir(tmp_path, name="right-render", package_sha=RIGHT_PACKAGE)
    value = build_review(
        ab_evidence=ab,
        left_render_dir=left,
        right_render_dir=right,
        decision="left",
        quality_note="Left is visibly more natural in the face and three-quarter views.",
    )
    assert value["preferred_side"] == "left"
    assert value["directional_preference_recorded"] is True
    assert "candidate_preference_authority" not in value


def test_cli_requires_confirmation_and_writes_create_only(tmp_path: Path, capsys) -> None:
    ab = _ab_evidence(tmp_path)
    left = _render_dir(tmp_path, name="left-render", package_sha=LEFT_PACKAGE)
    right = _render_dir(tmp_path, name="right-render", package_sha=RIGHT_PACKAGE)
    output = tmp_path / "review.json"
    args = [
        "--ab-evidence", str(ab),
        "--left-render-dir", str(left),
        "--right-render-dir", str(right),
        "--decision", "right",
        "--quality-note", "Candidate wins the visual material A/B.",
        "--out", str(output),
    ]
    assert main(args) == 1
    assert "requires explicit --confirm-visual-review" in capsys.readouterr().err
    assert not output.exists()

    assert main([*args, "--confirm-visual-review"]) == 0
    assert output.is_file()
    assert main([*args, "--confirm-visual-review"]) == 1
    assert "already exists" in capsys.readouterr().err
