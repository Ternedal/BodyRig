from pathlib import Path


def test_drift_job_history_filters_are_local_and_bounded() -> None:
    html = Path("bodyrig/ui/person.html").read_text(encoding="utf-8")
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")
    css = Path("bodyrig/ui/operator_control_plane.css").read_text(encoding="utf-8")

    for control in (
        "operatorJobPersonFilter",
        "operatorJobKindFilter",
        "operatorJobStateFilter",
        "operatorJobSearch",
    ):
        assert f'id="{control}"' in html

    assert "function filteredJobs(jobs)" in js
    assert 'personFilter === "current"' in js
    assert 'kindFilter !== "all"' in js
    assert 'filter === "open"' in js
    assert 'filter === "action"' in js
    assert 'filter === "failure"' in js
    assert 'filter === "final"' in js
    assert "haystack.includes(search)" in js
    assert ").slice(0, 30);" in js
    assert "lastJobsPayload" in js
    assert "renderJobs(lastJobsPayload)" in js
    assert ".operator-job-filters" in css


def test_drift_job_evidence_is_whitelisted_not_raw_job_serialization() -> None:
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")

    assert "function jobEvidenceLines(job)" in js
    for label in (
        "Job id",
        "BodyRig revision",
        "Source manifest SHA-256",
        "Source binding SHA-256",
        "Body review SHA-256",
        "Package SHA-256",
        "Adjustment feedback SHA-256",
    ):
        assert label in js
    assert "Evidence / detaljer" in js
    assert "operator-job-evidence-body" in js
    assert "JSON.stringify(job)" not in js


def test_drift_job_navigation_reuses_person_studio_selection_and_component_tabs() -> None:
    js = Path("bodyrig/ui/operator_control_plane.js").read_text(encoding="utf-8")
    person_js = Path("bodyrig/ui/person_app.js").read_text(encoding="utf-8")

    assert "button.dataset.personId = person.person_id" in person_js
    assert 'document.querySelectorAll("#personList .person-item")' in js
    assert "sidebarButton.click()" in js
    assert 'String(job?.kind || "") === "voice-build" ? "voice" : "body"' in js
    assert "targetTab" in js
    assert "Åbn Stemme" in js
    assert "Åbn Krop" in js
    navigation = js[js.index("async function openJobPerson"):js.index("function latestByKey")]
    assert "/api/v1/people/" not in navigation
