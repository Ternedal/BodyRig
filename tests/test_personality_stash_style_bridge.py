from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from bodyrig.guided_app import (
    SourceStyleApprovalRequest,
    app,
    approve_style_exemplars,
)
from bodyrig.personality_exemplar_approval import verify_approval


def _report() -> dict:
    return {
        "format": "bodyrig-personality-exemplar-candidates",
        "version": 1,
        "source_count": 1,
        "source_sha256": ["a" * 64],
        "candidate_count": 3,
        "candidates": [
            "Well, that is actually pretty funny.",
            "Yeah, I mean, I would probably do that.",
            "No, seriously, that is wild.",
        ],
        "suggested_exemplars": [
            "Well, that is actually pretty funny.",
            "No, seriously, that is wild.",
        ],
        "operator_review_required": True,
        "speaker_identity_authority": False,
        "personality_authority": False,
        "content_semantics": "style-only-not-biography-or-memory",
    }


def test_stash_style_routes_are_exposed_as_separate_non_activation_api() -> None:
    paths = app.openapi()["paths"]

    candidates = paths[
        "/api/v1/people/{person_id}/personality/source-style-candidates"
    ]
    approval = paths[
        "/api/v1/personality/style-exemplars/approval"
    ]

    assert "post" in candidates
    assert "post" in approval
    assert set(candidates) <= {"post"}
    assert set(approval) <= {"post"}


def test_style_approval_requires_exact_explicit_operator_confirmation() -> None:
    request = SourceStyleApprovalRequest(
        report=_report(),
        selected_candidate_indexes=[0, 2],
        speaker_identity_confirmed=True,
        style_use_approved=True,
    )

    result = approve_style_exemplars(request)

    assert result["personality_authority"] is False
    assert result["content_semantics"] == "style-only-not-biography-or-memory"
    verified = verify_approval(_report(), result["approval"])
    assert verified["approved_exemplars"] == [
        "Well, that is actually pretty funny.",
        "No, seriously, that is wild.",
    ]


@pytest.mark.parametrize(
    ("speaker_confirmed", "style_approved", "message"),
    [
        (False, True, "speaker identity"),
        (True, False, "style use"),
    ],
)
def test_style_approval_fails_closed_without_both_confirmations(
    speaker_confirmed: bool,
    style_approved: bool,
    message: str,
) -> None:
    request = SourceStyleApprovalRequest(
        report=_report(),
        selected_candidate_indexes=[0],
        speaker_identity_confirmed=speaker_confirmed,
        style_use_approved=style_approved,
    )

    with pytest.raises(HTTPException) as caught:
        approve_style_exemplars(request)

    assert caught.value.status_code == 422
    assert message in str(caught.value.detail)


def test_style_approval_indexes_are_strict_and_bounded() -> None:
    with pytest.raises(ValidationError):
        SourceStyleApprovalRequest(
            report=_report(),
            selected_candidate_indexes=[True],
            speaker_identity_confirmed=True,
            style_use_approved=True,
        )

    with pytest.raises(ValidationError):
        SourceStyleApprovalRequest(
            report=_report(),
            selected_candidate_indexes=list(range(13)),
            speaker_identity_confirmed=True,
            style_use_approved=True,
        )


def test_guided_ui_bridges_stash_style_without_inferring_traits() -> None:
    html = Path("bodyrig/ui/personality_guided.html").read_text(
        encoding="utf-8"
    )

    for token in (
        "Hent fra Stash",
        "Stash speaking-style",
        "stashSpeakerConfirmed",
        "stashStyleUseApproved",
        "approveStashStyle",
        "/personality/source-style-candidates",
        "/api/v1/personality/style-exemplars/approval",
        "De 120 traits ændres aldrig automatisk af Stash-data.",
        "Evidence må kun påvirke phrasing/rytme",
        "Revaliderer den bundne Stash/body-source",
    ):
        assert token in html

    render_start = html.index("function renderStashStyleCandidates")
    render_end = html.index("async function loadStashStyle", render_start)
    render_function = html[render_start:render_end]
    assert "value.textContent=text" in render_function
    assert ".innerHTML" not in render_function

    assert 'state.styleEvidenceOrigin==="stash"' in html
    assert "resetStashStyleReview();" in html
    assert "if(state.stashStyleReport||state.styleEvidenceOrigin" in html
