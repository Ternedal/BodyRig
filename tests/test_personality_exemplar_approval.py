from __future__ import annotations

import copy

import pytest

from bodyrig.personality_exemplar_approval import (
    PersonalityExemplarApprovalError,
    build_approval,
    canonical_sha256,
    verify_approval,
)


def report() -> dict:
    return {
        "format": "bodyrig-personality-exemplar-candidates",
        "version": 1,
        "source_count": 1,
        "source_sha256": ["a" * 64],
        "candidate_count": 4,
        "candidates": [
            "Ja ja, det går nok.",
            "Nå, videre.",
            "Det var da typisk.",
            "Vi finder ud af det.",
        ],
        "suggested_exemplars": [
            "Ja ja, det går nok.",
            "Det var da typisk.",
        ],
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def test_approval_requires_explicit_speaker_and_style_confirmation() -> None:
    with pytest.raises(PersonalityExemplarApprovalError, match="speaker identity"):
        build_approval(
            report(),
            selected_candidate_indexes=[0],
            speaker_identity_confirmed=False,
            style_use_approved=True,
        )
    with pytest.raises(PersonalityExemplarApprovalError, match="style use"):
        build_approval(
            report(),
            selected_candidate_indexes=[0],
            speaker_identity_confirmed=True,
            style_use_approved=False,
        )


def test_approval_is_bound_to_exact_report_indexes_and_text() -> None:
    source = report()
    approval = build_approval(
        source,
        selected_candidate_indexes=[0, 2],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )

    verified = verify_approval(source, approval)
    assert verified["candidate_report_sha256"] == canonical_sha256(source)
    assert verified["approved_exemplars"] == [
        "Ja ja, det går nok.",
        "Det var da typisk.",
    ]
    assert verified["personality_authority"] is False


def test_report_tamper_invalidates_existing_approval() -> None:
    source = report()
    approval = build_approval(
        source,
        selected_candidate_indexes=[1],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )
    tampered = copy.deepcopy(source)
    tampered["candidates"][1] = "En anden replik."
    tampered["suggested_exemplars"] = ["Ja ja, det går nok."]

    with pytest.raises(PersonalityExemplarApprovalError, match="exact candidate report"):
        verify_approval(tampered, approval)


def test_receipt_text_or_index_tamper_fails_against_bound_report() -> None:
    source = report()
    approval = build_approval(
        source,
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )

    text_tamper = copy.deepcopy(approval)
    text_tamper["approved_exemplars"][0] = "Nå, videre."
    with pytest.raises(PersonalityExemplarApprovalError, match="bound candidate indexes"):
        verify_approval(source, text_tamper)

    index_tamper = copy.deepcopy(approval)
    index_tamper["selected_candidate_indexes"][0] = 999
    with pytest.raises(PersonalityExemplarApprovalError, match="outside the bound report"):
        verify_approval(source, index_tamper)


def test_selected_indexes_must_be_unique_and_in_range() -> None:
    with pytest.raises(PersonalityExemplarApprovalError, match="unique"):
        build_approval(
            report(),
            selected_candidate_indexes=[0, 0],
            speaker_identity_confirmed=True,
            style_use_approved=True,
        )
    with pytest.raises(PersonalityExemplarApprovalError, match="out of range"):
        build_approval(
            report(),
            selected_candidate_indexes=[4],
            speaker_identity_confirmed=True,
            style_use_approved=True,
        )
