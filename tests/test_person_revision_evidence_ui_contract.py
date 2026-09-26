from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "bodyrig" / "ui" / "person.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "bodyrig" / "ui" / "person_app.js").read_text(encoding="utf-8")
EVIDENCE_JS = (ROOT / "bodyrig" / "ui" / "person_revision_evidence.js").read_text(encoding="utf-8")
EVIDENCE_CSS = (ROOT / "bodyrig" / "ui" / "person_revision_evidence.css").read_text(encoding="utf-8")
APP = (ROOT / "bodyrig" / "app.py").read_text(encoding="utf-8")


def test_person_revision_rows_expose_read_only_evidence_action() -> None:
    assert 'class="secondary inspect-person-revision"' in APP_JS
    assert "Vis evidence" in APP_JS
    assert '<script src="/ui/person_revision_evidence.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="/ui/person_revision_evidence.css">' in HTML


def test_evidence_inspector_revalidates_through_read_only_endpoint() -> None:
    assert '@app.get("/api/v1/people/{person_id}/revisions/{revision_id}/evidence")' in APP
    assert "verify_audition(" in APP
    assert "audition_receipt_sha256(" in APP
    assert "verify_receipt(" in APP
    assert '"verified": True' in APP
    assert '"verified": False' in APP
    assert '"legacy": True' in APP


def test_evidence_payload_exposes_hashes_not_raw_prompt_or_reply() -> None:
    endpoint_start = APP.index('@app.get("/api/v1/people/{person_id}/revisions/{revision_id}/evidence")')
    endpoint_end = APP.index('@app.post("/api/v1/people/{person_id}/revisions")', endpoint_start)
    endpoint = APP[endpoint_start:endpoint_end]

    for token in (
        '"prompt_sha256": audition["prompt_sha256"]',
        '"reply_sha256": audition["reply_sha256"]',
        '"audio_sha256": audition["audio_sha256"]',
        '"receipt_sha256": actual_sha',
        '"modelrig_version": audition["modelrig_version"]',
        '"voicerig_version": audition["voicerig_version"]',
    ):
        assert token in endpoint
    assert '"prompt":' not in endpoint
    assert '"reply":' not in endpoint


def test_evidence_inspector_is_read_only_and_fail_closed() -> None:
    assert "fetch(" in EVIDENCE_JS
    assert 'headers: { Accept: "application/json" }' in EVIDENCE_JS
    assert "POST" not in EVIDENCE_JS
    assert "/activate" not in EVIDENCE_JS
    assert "Fail-closed:" in EVIDENCE_JS
    assert "showModal()" in EVIDENCE_JS
    assert "audio.controls = true" in EVIDENCE_JS
    assert "prefers-reduced-motion" in EVIDENCE_CSS
