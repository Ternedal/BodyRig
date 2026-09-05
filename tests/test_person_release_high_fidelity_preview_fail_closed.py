from __future__ import annotations

import pytest

import bodyrig.person_release_status as release_status
from bodyrig.person_release_status import PersonReleaseStatusError

PERSON_ID = "person-" + "1" * 32
BODY_REVISION = "body-r0001"
BODY_ID = "bodyid-" + "2" * 24
REGISTERED_SHA = "3" * 64


def test_invalid_existing_high_fidelity_preview_never_falls_back_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_preview(person_id: str, body_revision: str) -> dict:
        raise release_status.HighFidelityPreviewError(
            "high-fidelity preview persisted evidence no longer matches completed comparison authority"
        )

    monkeypatch.setattr(release_status.high_fidelity_preview_manager, "latest_for_revision", invalid_preview)
    monkeypatch.setattr(
        release_status,
        "_legacy_inspect_candidate_release_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("invalid high-fidelity authority must never fall back to legacy release state")
        ),
    )

    with pytest.raises(PersonReleaseStatusError, match="high-fidelity preview authority is invalid"):
        release_status.inspect_candidate_release_status(
            [],
            person_id=PERSON_ID,
            body_revision=BODY_REVISION,
            body_id=BODY_ID,
            package_sha256=REGISTERED_SHA,
        )


def test_exact_preview_not_found_state_still_allows_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = {"state": "legacy"}

    def no_preview(person_id: str, body_revision: str) -> dict:
        raise release_status.HighFidelityPreviewError(
            "no high-fidelity preview exists for this body revision"
        )

    monkeypatch.setattr(release_status.high_fidelity_preview_manager, "latest_for_revision", no_preview)
    monkeypatch.setattr(
        release_status,
        "_legacy_inspect_candidate_release_status",
        lambda *args, **kwargs: sentinel,
    )

    value = release_status.inspect_candidate_release_status(
        [],
        person_id=PERSON_ID,
        body_revision=BODY_REVISION,
        body_id=BODY_ID,
        package_sha256=REGISTERED_SHA,
    )

    assert value is sentinel
