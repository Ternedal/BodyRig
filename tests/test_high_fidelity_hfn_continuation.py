from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.high_fidelity_hfn_continuation as subject


PERSON = "person-" + "1" * 32
BODY = "body-r0001"
REVISION = "a" * 40
SOURCE_SHA = hashlib.sha256(b"source package").hexdigest()
CANDIDATE_SHA = hashlib.sha256(b"candidate package").hexdigest()


def _source_package(tmp_path: Path) -> Path:
    path = tmp_path / "source.mrbody"
    path.write_bytes(b"source package")
    return path


def _candidate(root: Path, *, capture: str, candidate: str, source_sha: str = SOURCE_SHA) -> dict[str, object]:
    receipt = root / "hands-feet-nails-detail-candidates" / PERSON / BODY / capture / f"{candidate}.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        "format": "bodyrig-hands-feet-nails-detail-candidate",
        "version": 1,
        "source_package_sha256": source_sha,
        "bodyrig_revision": REVISION,
    }))
    return {
        "version": 1,
        "person_id": PERSON,
        "body_revision": BODY,
        "capture_id": capture,
        "candidate_id": candidate,
        "body_id": "body-" + "4" * 32,
        "bodyrig_revision": REVISION,
        "source_package_sha256": source_sha,
        "candidate_package_sha256": CANDIDATE_SHA,
        "package_path": str(receipt.with_suffix(".mrbody")),
        "clean_appearance_ab": True,
    }


def test_missing_candidate_returns_exact_source_bound_operator_action(tmp_path: Path) -> None:
    source = _source_package(tmp_path)
    result = subject.inspect_hfn_continuation(
        root=tmp_path / "people",
        person_id=PERSON,
        body_revision=BODY,
        bodyrig_revision=REVISION,
        source_package_path=source,
        source_package_sha256=SOURCE_SHA,
        render_dir=tmp_path / "render",
        human_review_dir=tmp_path / "review",
    )

    assert result["gates"] == [{
        "id": subject.CANDIDATE_GATE,
        "state": "required",
        "passed": False,
        "reason": "no exact HFN detail candidate targets the face-secondary promoted package",
        "evidence": {},
    }]
    action = result["actions"][subject.CANDIDATE_GATE]
    assert action["operator_input_required"] is True
    assert "<CAPTURE_ID>" in action["command"]
    assert "<UV_EVIDENCE_PATH>" in action["command"]
    assert str(source) in action["command"]


def test_matching_candidate_becomes_current_package_and_requires_canonical_render(tmp_path: Path, monkeypatch) -> None:
    source = _source_package(tmp_path)
    root = tmp_path / "people"
    capture = "hfncap-" + "2" * 32
    candidate_id = "hfncand-" + "3" * 32
    candidate = _candidate(root, capture=capture, candidate=candidate_id)
    candidate_path = Path(candidate["package_path"])
    candidate_path.write_bytes(b"candidate package")
    monkeypatch.setattr(subject, "read_detail_candidate", lambda *args, **kwargs: dict(candidate))

    result = subject.inspect_hfn_continuation(
        root=root,
        person_id=PERSON,
        body_revision=BODY,
        bodyrig_revision=REVISION,
        source_package_path=source,
        source_package_sha256=SOURCE_SHA,
        render_dir=tmp_path / "render",
        human_review_dir=tmp_path / "review",
    )

    assert [gate["id"] for gate in result["gates"]] == [subject.CANDIDATE_GATE, subject.RENDER_GATE]
    assert result["gates"][0]["state"] == "pass"
    assert result["gates"][1]["state"] == "required"
    assert result["package_path"] == candidate_path
    assert result["package_sha256"] == CANDIDATE_SHA
    action = result["actions"][subject.RENDER_GATE]
    assert action["operator_input_required"] is False
    assert "prepare-hands-feet-nails-render-review.ps1" in action["command"]
    assert str(candidate_path) in action["command"]


def test_multiple_matching_candidates_fail_closed_as_ambiguous(tmp_path: Path, monkeypatch) -> None:
    source = _source_package(tmp_path)
    root = tmp_path / "people"
    first_capture = "hfncap-" + "2" * 32
    second_capture = "hfncap-" + "5" * 32
    first_id = "hfncand-" + "3" * 32
    second_id = "hfncand-" + "6" * 32
    first = _candidate(root, capture=first_capture, candidate=first_id)
    second = _candidate(root, capture=second_capture, candidate=second_id)

    def reader(_root, _person, *, body_revision, capture_id, candidate_id):
        assert body_revision == BODY
        if candidate_id == first_id:
            return dict(first)
        if candidate_id == second_id:
            return dict(second)
        raise AssertionError(candidate_id)

    monkeypatch.setattr(subject, "read_detail_candidate", reader)
    result = subject.inspect_hfn_continuation(
        root=root,
        person_id=PERSON,
        body_revision=BODY,
        bodyrig_revision=REVISION,
        source_package_path=source,
        source_package_sha256=SOURCE_SHA,
        render_dir=tmp_path / "render",
        human_review_dir=tmp_path / "review",
    )

    assert result["gates"][-1]["id"] == subject.CANDIDATE_GATE
    assert result["gates"][-1]["state"] == "invalid"
    assert "ambiguous" in result["gates"][-1]["reason"]
    assert result["actions"] == {}


def test_review_gate_requires_operator_input_after_exact_render_pass(tmp_path: Path, monkeypatch) -> None:
    source = _source_package(tmp_path)
    root = tmp_path / "people"
    capture = "hfncap-" + "2" * 32
    candidate_id = "hfncand-" + "3" * 32
    candidate = _candidate(root, capture=capture, candidate=candidate_id)
    candidate_path = Path(candidate["package_path"])
    candidate_path.write_bytes(b"candidate package")
    render_dir = tmp_path / "render"
    render_dir.mkdir()
    monkeypatch.setattr(subject, "read_detail_candidate", lambda *args, **kwargs: dict(candidate))
    monkeypatch.setattr(subject, "_validate_render_authority", lambda *args, **kwargs: {
        "manifest_path": str(render_dir / "snapshots" / "hands-feet-nails-render-set.json"),
        "manifest_sha256": hashlib.sha256(b"render").hexdigest(),
        "region_sha256": {},
        "render_authority_sha256": hashlib.sha256(b"authority").hexdigest(),
    })

    result = subject.inspect_hfn_continuation(
        root=root,
        person_id=PERSON,
        body_revision=BODY,
        bodyrig_revision=REVISION,
        source_package_path=source,
        source_package_sha256=SOURCE_SHA,
        render_dir=render_dir,
        human_review_dir=tmp_path / "review",
    )

    assert [gate["state"] for gate in result["gates"]] == ["pass", "pass", "required"]
    action = result["actions"][subject.HUMAN_GATE]
    assert action["operator_input_required"] is True
    assert "record-high-fidelity-hfn-review.ps1" in action["command"]
    assert "-ConfirmDetailChecklist" in action["command"]
    assert "<QUALITY_NOTE>" in action["command"]
