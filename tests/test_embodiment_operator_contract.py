from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "finalize-person-embodiment-authority.ps1"


def test_m4_finalizer_is_clean_checkout_and_exact_revision_bound() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in source
    assert "requires a clean BodyRig checkout" in source
    assert "git -C $repoRoot rev-parse HEAD" in source
    assert "--bodyrig-revision $revision" in source


def test_m4_finalizer_uses_checkout_bound_python() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert '.venv\\Scripts\\python.exe' in source
    assert "$env:PYTHONPATH = $repoRoot" in source
    assert "bodyrig.__file__" in source
    assert "Python imported BodyRig outside current checkout" in source
    assert "sys.version_info >= (3, 11)" in source


def test_m4_finalizer_requires_three_real_operator_reviews() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert "ConfirmMotionReview" in source
    assert "ConfirmExpressionReview" in source
    assert "ConfirmVoiceTimingReview" in source
    assert "must explicitly PASS" not in source  # core owns semantic review error; wrapper owns switch check
    assert "requires explicit operator confirmation" in source
    assert "QualityNote must be a real 12-2000 character operator note" in source
    assert "-match '^<[^>]+>$'" in source


def test_m4_finalizer_routes_only_through_canonical_cli() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert "-m bodyrig.embodiment_authority_cli" in source
    assert "--assembly-receipt $assembly" in source
    assert "--body-release-status $release" in source
    assert "--package $package" in source
    assert "--motor-state $motor" in source
    assert "--speech-timing $timing" in source
    assert "--audition-receipt $audition" in source
    assert "--confirm-motion-review" in source
    assert "--confirm-expression-review" in source
    assert "--confirm-voice-timing-review" in source
