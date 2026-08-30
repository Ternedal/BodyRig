from __future__ import annotations

from pathlib import Path


def test_profiled_launcher_resolves_gender_before_canonical_ready_clone() -> None:
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "clone-body-from-stash-profiled-ready.ps1").read_text(encoding="utf-8")

    assert '"-m", "bodyrig.stash_performer_profile"' in source
    assert "$env:BODYRIG_SITH_BODY_MODEL_GENDER = $resolvedGender" in source
    assert "refusing a silent neutral body model" in source
    assert '& $readyScript @forward' in source
    assert 'if ([string]$entry.Key -eq "BodyModelGender")' in source
    assert "STASH_API_KEY" in source
    assert "api key" not in source.lower().replace("api key env", "")


def test_orchestrator_uses_profiled_gender_environment_when_flag_is_absent() -> None:
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "bodyrig" / "sith_fitter_orchestrator.py").read_text(encoding="utf-8")

    assert 'BODY_MODEL_GENDER_ENV = "BODYRIG_SITH_BODY_MODEL_GENDER"' in source
    assert 'parser.add_argument("--body-model-gender", choices=SMPLX_GENDERS, default=None)' in source
    assert "resolved_gender = args.body_model_gender or _default_body_model_gender()" in source
    assert "body_model_gender=resolved_gender" in source
