from pathlib import Path


def test_suite_runner_uses_existing_execution_and_non_authoritative_review_api() -> None:
    html = Path("bodyrig/ui/personality_audition_suite.html").read_text(encoding="utf-8")
    guided = Path("bodyrig/guided_app.py").read_text(encoding="utf-8")

    for token in (
        "Personality Audition Suite",
        "Kør 6 scenarier",
        "Forsegl suite-evidence",
        "bodyRevision",
        "voiceRevision",
        "personalityRevision",
        "modelSelect",
        "/auditions",
        "/personality/audition-suite/reviews",
        "assemblyFingerprint",
        "audition_ids",
        "human review",
    ):
        assert token.lower() in html.lower()

    assert "/activate/" not in html
    assert "activation_authority" not in html
    assert "state.assemblyFingerprint!==result.assembly_fingerprint" in html
    assert html.count("state.runKey!==currentKey()") >= 3
    assert "resultatet kasseres fra suiten" in html
    assert "audio.addEventListener(\"ended\"" in html

    assert '@app.get("/api/v1/personality/audition-suite")' in guided
    assert '@app.post("/api/v1/people/{person_id}/personality/audition-suite/reviews")' in guided
    assert "seal_suite_review" in guided
    assert "verify_suite_review" in guided


def test_suite_deep_link_selects_exact_personality_revision() -> None:
    html = Path("bodyrig/ui/personality_audition_suite.html").read_text(encoding="utf-8")

    for token in (
        'params.get("personality_revision")',
        'requestedPersonality=params.get("personality_revision")||""',
        'selectPerson(first.person_id,{requestedPersonality})',
        'requestedKnown=(state.person.personality_revisions||[]).some',
        'item.revision_id===requestedPersonality',
        'requestedKnown?requestedPersonality:',
    ):
        assert token in html

    # Manual person changes must not keep forcing a stale deep-link revision.
    assert '$("personSelect").addEventListener("change",()=>selectPerson($("personSelect").value))' in html



def test_sealed_suite_handoff_preserves_exact_candidates_without_activation() -> None:
    html = Path("bodyrig/ui/personality_audition_suite.html").read_text(encoding="utf-8")

    for token in (
        'id="continueReviewLink"',
        "Fortsæt til samlet compatibility review",
        '$("continueReviewLink").hidden=true',
        '$("continueReviewLink").href="/"',
        'reviewLink.href=`/?person_id=${encodeURIComponent(state.person.person_id)}',
        '&body_revision=${encodeURIComponent(sel.body_revision)}',
        '&voice_revision=${encodeURIComponent(sel.voice_revision)}',
        '&personality_revision=${encodeURIComponent(sel.personality_revision)}',
        "&tab=assemble",
        "reviewLink.hidden=false",
        "ny canonical samlet audition.",
    ):
        assert token in html

    # The supplementary suite may only hand selection state to Person Studio.
    assert "/activate/" not in html
    assert "approvePersonButton" not in html


def test_suite_review_contract_is_explicitly_supplementary() -> None:
    suite = Path("bodyrig/personality_audition_suite.py").read_text(encoding="utf-8")
    review = Path("bodyrig/personality_suite_review.py").read_text(encoding="utf-8")

    assert '"human_review_required": True' in suite
    assert '"activation_authority": False' in suite
    assert '"human_review_required": True' in review
    assert '"activation_authority": False' in review
    assert "verify_audition(" in review
    assert "receipt_sha256(" in review
    assert "audition prompt does not match the suite definition" in review
    assert "audition used a different ModelRig model" in review
