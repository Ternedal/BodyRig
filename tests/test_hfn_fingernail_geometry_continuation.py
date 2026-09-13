from __future__ import annotations

import hashlib
from pathlib import Path

import bodyrig.high_fidelity_hfn_continuation as continuation


PERSON = "person-" + "1" * 32
BODY = "body-r0001"
REVISION = "a" * 40
CAPTURE = "capture-1"
CANDIDATE = "candidate-1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _detail(tmp_path: Path, source_sha: str) -> dict:
    package = tmp_path / "detail.mrbody"
    package.write_bytes(b"detail")
    receipt = tmp_path / "detail.json"
    receipt.write_text("{}\n", encoding="utf-8")
    return {
        "person_id": PERSON,
        "body_revision": BODY,
        "capture_id": CAPTURE,
        "candidate_id": CANDIDATE,
        "body_id": "bodyid-test",
        "bodyrig_revision": REVISION,
        "source_package_sha256": source_sha,
        "candidate_package_sha256": _sha(package),
        "candidate_basecolor_sha256": "b" * 64,
        "package_path": str(package),
        "receipt_path": str(receipt),
        "clean_appearance_ab": True,
    }


def test_hfn_render_cannot_start_before_fingernail_geometry_exists(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "face.mrbody"
    source.write_bytes(b"face")
    source_sha = _sha(source)
    detail = _detail(tmp_path, source_sha)
    missing_package = tmp_path / "geometry.mrbody"
    missing_receipt = tmp_path / "geometry.json"

    monkeypatch.setattr(continuation, "_find_candidate", lambda *args, **kwargs: detail)
    monkeypatch.setattr(
        continuation,
        "geometry_paths",
        lambda *args, **kwargs: (missing_package, missing_receipt),
    )

    result = continuation.inspect_hfn_continuation(
        root=tmp_path / "people",
        person_id=PERSON,
        body_revision=BODY,
        bodyrig_revision=REVISION,
        source_package_path=source,
        source_package_sha256=source_sha,
        render_dir=tmp_path / "render",
        human_review_dir=tmp_path / "review",
    )

    assert result["gates"][0]["id"] == continuation.CANDIDATE_GATE
    assert result["gates"][0]["state"] == "required"
    assert result["gates"][0]["passed"] is False
    action = result["actions"][continuation.CANDIDATE_GATE]
    assert "prepare-hands-feet-nails-fingernail-geometry-candidate.ps1" in action["command"]
    assert action["operator_input_required"] is False
    assert continuation.RENDER_GATE not in result["actions"]
    assert result["package_sha256"] == detail["candidate_package_sha256"]


def test_hfn_render_uses_geometry_package_not_texture_only_detail(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "face.mrbody"
    source.write_bytes(b"face")
    source_sha = _sha(source)
    detail = _detail(tmp_path, source_sha)
    geometry = tmp_path / "geometry.mrbody"
    geometry.write_bytes(b"geometry")
    geometry_receipt = tmp_path / "geometry.json"
    geometry_receipt.write_text("{}\n", encoding="utf-8")
    geometry_sha = _sha(geometry)

    monkeypatch.setattr(continuation, "_find_candidate", lambda *args, **kwargs: detail)
    monkeypatch.setattr(
        continuation,
        "geometry_paths",
        lambda *args, **kwargs: (geometry, geometry_receipt),
    )
    monkeypatch.setattr(
        continuation,
        "_geometry_review_candidate",
        lambda *args, **kwargs: {
            **detail,
            "package_path": str(geometry),
            "candidate_package_sha256": geometry_sha,
            "candidate_avatar_sha256": "c" * 64,
            "detail_candidate_package_sha256": detail["candidate_package_sha256"],
            "fingernail_geometry_package_sha256": geometry_sha,
            "fingernail_plate_count": 10,
        },
    )

    render_dir = tmp_path / "render"
    result = continuation.inspect_hfn_continuation(
        root=tmp_path / "people",
        person_id=PERSON,
        body_revision=BODY,
        bodyrig_revision=REVISION,
        source_package_path=source,
        source_package_sha256=source_sha,
        render_dir=render_dir,
        human_review_dir=tmp_path / "review",
    )

    assert result["gates"][0]["state"] == "pass"
    assert result["gates"][0]["evidence"]["fingernail_plate_count"] == 10
    assert result["gates"][1]["id"] == continuation.RENDER_GATE
    assert result["gates"][1]["state"] == "required"
    command = result["actions"][continuation.RENDER_GATE]["command"]
    assert str(geometry.resolve()) in command
    assert str(Path(detail["package_path"]).resolve()) not in command
    assert result["package_path"] == geometry.resolve()
    assert result["package_sha256"] == geometry_sha


def test_hfn_human_review_is_geometry_package_bound() -> None:
    root = Path(__file__).resolve().parents[1]
    review = (root / "bodyrig" / "high_fidelity_hfn_review.py").read_text(encoding="utf-8")
    wrapper = (root / "prepare-hands-feet-nails-fingernail-geometry-candidate.ps1").read_text(encoding="utf-8")
    cli = (root / "bodyrig" / "hands_feet_nails_fingernail_geometry_candidate_cli.py").read_text(encoding="utf-8")

    assert "read_fingernail_geometry_candidate" in review
    assert '"candidate_package_sha256": str(geometry["geometry_package_sha256"])' in review
    assert '"receipt_path": str(geometry["receipt_path"])' in review
    assert "HFN human review requires exact fingernail geometry authority" in review
    assert "git -C $repoRoot status --porcelain" in wrapper
    assert "requires a clean BodyRig checkout" in wrapper
    assert "--bodyrig-revision $head" in wrapper
    assert "read_detail_candidate" in cli
    assert "HFN detail candidate was produced by a different BodyRig revision" in cli
