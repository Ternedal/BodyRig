from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.digital_twin_control_plane_ui as twin


PERSON_ID = "person-" + "1" * 32
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"


def test_evidence_stage_is_strict_bounded_and_ignores_noncanonical_dirs(tmp_path: Path) -> None:
    base = tmp_path / "captures"
    base.mkdir()
    valid_id = "hfncap-" + "1" * 32
    rejected_id = "hfncap-" + "2" * 32
    (base / valid_id).mkdir()
    (base / rejected_id).mkdir()
    (base / "not-canonical").mkdir()

    calls: list[str] = []

    def reader(candidate_id: str) -> dict:
        calls.append(candidate_id)
        if candidate_id == rejected_id:
            raise twin.HandsFeetNailsSourceCaptureError("invalid evidence")
        return {"capture_id": candidate_id}

    value = twin._evidence_stage(
        base=base,
        id_pattern=twin.HFN_CAPTURE_ID_RE,
        reader=reader,
        errors=(twin.HandsFeetNailsSourceCaptureError,),
        label="M2 source capture",
    )

    assert value["state"] == "complete"
    assert value["complete"] is True
    assert value["valid_count"] == 1
    assert value["rejected_count"] == 1
    assert value["candidate_ids"] == [valid_id]
    assert set(calls) == {valid_id, rejected_id}
    assert "not-canonical" not in calls

    for index in range(3, 12):
        (base / ("hfncap-" + f"{index:032x}")).mkdir()
    calls.clear()
    bounded = twin._evidence_stage(
        base=base,
        id_pattern=twin.HFN_CAPTURE_ID_RE,
        reader=lambda candidate_id: calls.append(candidate_id) or {"capture_id": candidate_id},
        errors=(twin.HandsFeetNailsSourceCaptureError,),
        label="M2 source capture",
    )
    assert bounded["scan_truncated"] is True
    assert len(calls) == 8
    assert len(bounded["candidate_ids"]) <= 8


def test_component_progress_uses_existing_strict_readers_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hfn_capture = "hfncap-" + "1" * 32
    hfn_review = "hfnreview-" + "2" * 32
    ward_capture = "wardcap-" + "3" * 32
    ward_review = "wardreview-" + "4" * 32

    for path in (
        tmp_path / "hands-feet-nails-source-captures" / PERSON_ID / BODY_REVISION / hfn_capture,
        tmp_path / "hands-feet-nails-authorities" / PERSON_ID / PERSON_REVISION / hfn_review,
        tmp_path / "wardrobe-source-captures" / PERSON_ID / BODY_REVISION / ward_capture,
        tmp_path / "wardrobe-authorities" / PERSON_ID / PERSON_REVISION / ward_review,
    ):
        path.mkdir(parents=True)

    monkeypatch.setattr(
        twin,
        "read_hfn_source_capture",
        lambda *args, **kwargs: {"capture_id": kwargs["capture_id"]},
    )
    monkeypatch.setattr(
        twin,
        "read_hfn_review_authority",
        lambda *args, **kwargs: {"review_id": kwargs["review_id"]},
    )
    monkeypatch.setattr(
        twin,
        "read_wardrobe_source_capture",
        lambda *args, **kwargs: {"capture_id": kwargs["capture_id"]},
    )
    monkeypatch.setattr(
        twin,
        "read_wardrobe_review_authority",
        lambda *args, **kwargs: {"review_id": kwargs["review_id"]},
    )

    progress = twin._component_progress(
        root=tmp_path,
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        body_revision=BODY_REVISION,
        assembly={},
        body_release={},
        m2={"state": "required", "complete": False, "message": "M2 final mangler."},
        m3={"state": "required", "complete": False, "message": "M3 final mangler."},
    )

    assert progress["authority"] == {
        "read_only": True,
        "capture_mutation_authority": False,
        "human_review_authority": False,
        "finalization_authority": False,
    }
    assert progress["m2"]["source_capture"]["candidate_ids"] == [hfn_capture]
    assert progress["m2"]["review"]["candidate_ids"] == [hfn_review]
    assert progress["m2"]["next_substage"] == "finalized"
    assert progress["m3"]["source_capture"]["candidate_ids"] == [ward_capture]
    assert progress["m3"]["review"]["candidate_ids"] == [ward_review]
    assert progress["m3"]["next_substage"] == "finalized"

    complete = twin._component_progress(
        root=tmp_path,
        person_id=PERSON_ID,
        person_revision=PERSON_REVISION,
        body_revision=BODY_REVISION,
        assembly={},
        body_release={},
        m2={
            "state": "complete",
            "complete": True,
            "message": "M2 complete.",
            "authority_id": "hfnrelease-" + "5" * 32,
        },
        m3={
            "state": "complete",
            "complete": True,
            "message": "M3 complete.",
            "authority_id": "wardrelease-" + "6" * 32,
        },
    )
    assert complete["m2"]["next_substage"] == "complete"
    assert complete["m2"]["finalized"]["authority_id"] == "hfnrelease-" + "5" * 32
    assert complete["m3"]["next_substage"] == "complete"
    assert complete["m3"]["finalized"]["authority_id"] == "wardrelease-" + "6" * 32


def test_drift_m2_m3_substage_surface_is_read_only() -> None:
    api = Path("bodyrig/digital_twin_control_plane_ui_api.py").read_text(encoding="utf-8")
    core = Path("bodyrig/digital_twin_control_plane_ui.py").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/operator_control_plane.css").read_text(encoding="utf-8")

    assert "component_progress" in core
    assert '"capture_mutation_authority": False' in core
    assert '"human_review_authority": False' in core
    assert '"finalization_authority": False' in core
    assert "evidence-root er symlinket og afvises" in core
    assert "_component_progress" in core
    assert 'id="operator-digital-twin-components"' in html
    assert "M2 / M3 evidence" in html
    assert "renderDigitalTwinComponents" in js
    assert "Source capture" in js
    assert "Render + human review" in js
    assert "Finalized authority" in js
    assert ".operator-twin-component-stages" in css
    assert '@router.post("/api/v1/people/{person_id}/digital-twin-readiness/action")' in api
    assert 'action: str = Field(pattern=r"^advance-m5$")' in api
    component_renderer = js[js.index("function renderDigitalTwinComponents"):js.index("function renderDigitalTwinRealization")]
    assert "next_command" not in component_renderer
    assert "addEventListener" not in component_renderer
    assert "advance-m5" not in component_renderer
