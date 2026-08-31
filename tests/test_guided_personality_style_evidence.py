from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig.person_profiles import create_profile, load_profile
from bodyrig.personality_authoring import (
    PersonalityAuthoringError,
    build_guided_personality,
    save_guided_personality,
)
from bodyrig.personality_exemplar_approval import build_approval


def _communication() -> dict[str, float]:
    return {
        "directness": 0.7,
        "warmth": 0.6,
        "playfulness": 0.7,
        "formality": 0.2,
        "verbosity": 0.4,
        "initiative": 0.7,
    }


def _report() -> dict:
    return {
        "format": "bodyrig-personality-exemplar-candidates",
        "version": 1,
        "source_count": 1,
        "source_sha256": ["d" * 64],
        "candidate_count": 3,
        "candidates": [
            "Ja ja, det går nok.",
            "Nå, videre.",
            "Det var da typisk.",
        ],
        "suggested_exemplars": ["Ja ja, det går nok.", "Det var da typisk."],
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def _approval(report: dict) -> dict:
    return build_approval(
        report,
        selected_candidate_indexes=[0, 2],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )


def test_guided_preview_verifies_inline_style_evidence_without_writing(tmp_path: Path) -> None:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Anna")
    report = _report()

    result = build_guided_personality(
        root,
        profile["person_id"],
        default_language="da",
        communication=_communication(),
        style_report=report,
        style_approval=_approval(report),
    )

    assert result["blueprint"]["style_exemplars"] == [
        "Ja ja, det går nok.",
        "Det var da typisk.",
    ]
    assert result["style_evidence"]["approved_count"] == 2
    assert len(result["style_evidence"]["candidate_report_sha256"]) == 64
    assert len(result["style_evidence"]["approval_sha256"]) == 64
    assert "style_report_sha256=" in result["candidate"]["style_notes"]
    assert "style_approval_sha256=" in result["candidate"]["style_notes"]
    assert not (root / "personality-style-evidence").exists()
    assert load_profile(root, profile["person_id"])["personality_revisions"] == []


def test_guided_save_persists_verified_style_evidence_before_candidate(tmp_path: Path) -> None:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Anna")
    report = _report()
    approval = _approval(report)

    result = save_guided_personality(
        root,
        profile["person_id"],
        default_language="da",
        communication=_communication(),
        style_report=report,
        style_approval=approval,
        feedback="approved transcript style",
    )

    style = result["style_evidence"]
    paths = result["style_evidence_paths"]
    assert Path(paths["report"]).is_file()
    assert Path(paths["approval"]).is_file()
    assert Path(paths["report"]).name == f"{style['candidate_report_sha256']}.json"
    assert Path(paths["approval"]).name == f"{style['approval_sha256']}.json"
    saved = load_profile(root, profile["person_id"])
    revision = saved["personality_revisions"][0]
    assert "style_report_sha256=" + style["candidate_report_sha256"] in revision["style_notes"]
    assert "style_approval_sha256=" + style["approval_sha256"] in revision["style_notes"]
    assert saved["active_person_revision"] is None


def test_mismatched_inline_style_evidence_fails_before_any_persistence(tmp_path: Path) -> None:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Anna")
    report = _report()
    approval = _approval(report)
    report["candidates"][0] = "En ændret replik."
    report["suggested_exemplars"] = ["Det var da typisk."]

    with pytest.raises(PersonalityAuthoringError, match="exact candidate report"):
        save_guided_personality(
            root,
            profile["person_id"],
            default_language="da",
            communication=_communication(),
            style_report=report,
            style_approval=approval,
        )

    assert load_profile(root, profile["person_id"])["personality_revisions"] == []
    assert not (root / "personality-style-evidence").exists()
    assert not (root / "personality-blueprints").exists()


def test_report_and_approval_must_be_supplied_together(tmp_path: Path) -> None:
    root = tmp_path / "people"
    profile = create_profile(root, display_name="Anna")

    with pytest.raises(PersonalityAuthoringError, match="supplied together"):
        build_guided_personality(
            root,
            profile["person_id"],
            default_language="da",
            communication=_communication(),
            style_report=_report(),
        )
