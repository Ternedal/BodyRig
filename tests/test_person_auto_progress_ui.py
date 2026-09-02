from pathlib import Path


JS = Path("bodyrig/ui/person_auto.js").read_text(encoding="utf-8")


def test_auto_person_build_shows_live_body_elapsed_progress() -> None:
    assert 'id="autoPersonBuildProgress"' in JS
    assert 'id="autoPersonBuildProgressBar"' in JS
    assert 'id="autoPersonBuildProgressText"' in JS
    assert 'BODY_EXPECTED_SECONDS = 45 * 60' in JS
    assert 'BODY_UPPER_SECONDS = 120 * 60' in JS
    assert 'formatDuration' in JS
    assert 'renderBodyProgress(bodyJob)' in JS
    assert 'typisk 45–120 min' in JS


def test_auto_person_build_prefers_real_backend_progress_when_available() -> None:
    assert 'const reported = Number(job.progress)' in JS
    assert 'job.message || job.stage' in JS
    assert 'ca. ${Math.round(reported)}%' in JS


def test_auto_person_build_surfaces_backend_diagnostic_tail_when_available() -> None:
    assert 'bodyJob.diagnostic_tail' in JS
    assert 'diagnostic ? `\\n\\n${diagnostic}`' in JS
