from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "export-runtime-speech-timing-evidence.ps1"


def test_exporter_requires_exact_running_checkout_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'http://127.0.0.1:8775' in source
    assert 'git -C $repoRoot status --porcelain' in source
    assert 'git -C $repoRoot rev-parse HEAD' in source
    assert 'BodyRig\\ui-service.json' in source
    assert '[string]$launch.revision -ne $revision' in source
    assert 'different checkout or revision' in source


def test_exporter_reads_only_runtime_produced_timing_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '/api/v1/health' in source
    assert '/api/v1/runtime/state' in source
    assert '$state.speech_timing_evidence' in source
    assert 'bodyrig-speech-timing-evidence' in source
    assert 'voicerig-runtime' in source
    assert 'human_review_required' in source
    assert 'production_activation' in source


def test_exporter_is_create_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'Refusing to overwrite existing runtime timing evidence' in source
    assert '[System.IO.FileMode]::CreateNew' in source
    assert 'Get-FileHash' in source
