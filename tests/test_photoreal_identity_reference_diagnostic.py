from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIAGNOSTIC = ROOT / "tools" / "photoreal_reference_identity_diagnostic.py"
POWERSHELL_RUNNER = ROOT / "diagnose-photoreal-v2-identity-bootstrap.ps1"


def test_diagnostic_matches_strict_stage7_rejection_classes() -> None:
    text = PYTHON_DIAGNOSTIC.read_text(encoding="utf-8")

    assert 'reason = "no-person-candidates"' in text
    assert 'reason = "multiple-person-candidates"' in text
    assert 'reason = "single-person-without-face"' in text
    assert 'reason = "single-person-face-without-embedding"' in text
    assert 'reason = "accepted"' in text
    assert '"diagnostic_only": True' in text
    assert '"identity_authority": False' in text
    assert '"teacher_training_authorized": False' in text
    assert '"production_activation": False' in text


def test_diagnostic_uses_same_composite_adapter_revision_as_stage7() -> None:
    text = PYTHON_DIAGNOSTIC.read_text(encoding="utf-8")

    assert 'photoreal_reference_vision_adapter_mesh.py' in text
    assert 'current_revision = adapter._self_revision()' in text
    assert 'requested_revision != current_revision' in text
    assert 'observed_model_set = adapter.build_model_set(model_root)' in text


def test_runner_reproduces_wsl_transport_without_source_rehash() -> None:
    text = POWERSHELL_RUNNER.read_text(encoding="utf-8")

    assert 'from bodyrig.wsl_adapter_bridge import make_wsl_path_converter' in text
    assert 'make_wsl_path_converter(sys.argv[2], sys.argv[3])(sys.argv[4])' in text
    assert 'wslpath -u $transportPath' not in text
    assert '$source.resolved_path = Convert-ToWslPath -WindowsPath $raw' in text
    assert 'identity-extractor\\request.json' in text
    assert 'photoreal_source_verify_cli' not in text
    assert 'photoreal-stash-inventory.ps1' not in text
    assert 'Read-Host' not in text
    assert 'Pause' not in text



def test_runner_wsl_path_stdout_is_codepage_independent() -> None:
    text = POWERSHELL_RUNNER.read_text(encoding="utf-8")

    assert "import base64" in text
    assert 'base64.b64encode(value.encode("utf-8")).decode("ascii")' in text
    assert "[Convert]::FromBase64String($encoded)" in text
    assert "[Text.Encoding]::UTF8.GetString" in text
    assert "print(make_wsl_path_converter" not in text
