from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_canonical_smplx_gender_is_explicit_and_not_hardcoded() -> None:
    source = text("bodyrig/bridges/sith_canonical_smplx_obj.py")
    assert 'SMPLX_GENDERS = ("female", "male", "neutral")' in source
    assert 'parser.add_argument("--gender", choices=SMPLX_GENDERS, default="neutral")' in source
    assert "gender=gender" in source
    assert 'gender="male"' not in source


def test_pinned_sith_fit_is_gender_patched_in_memory_only() -> None:
    source = text("bodyrig/bridges/sith_fit_gender.py")
    assert 'MARKER = "gender=\'male\'"' in source
    assert "source.count(MARKER) != 1" in source
    assert "patched = source.replace" in source
    assert "write_text(" not in source


def test_final_vrm_rigging_is_gender_and_donor_topology_patched_in_memory_only() -> None:
    source = text("bodyrig/bridges/sith_smplx_vrm_fitter_gender.py")
    assert 'GENDER_MARKER = \'gender="male",\'' in source
    assert "_replace_once(" in source
    assert "source.replace(old, new, 1)" in source
    assert 'with_name("sith_smplx_vrm_fitter_donor.py")' in source
    assert "repair_source_shell" not in source
    assert "write_text(" not in source


def test_reconstruction_threads_gender_to_fit_and_canonical_regeneration() -> None:
    source = text("bodyrig/sith_reconstruct.py")
    assert 'body_model_gender: str = "neutral"' in source
    assert '"sith_fit_gender.py"' in source
    assert '"--bodyrig-smplx-gender"' in source
    assert '"--gender"' in source
    assert 'parser.add_argument("--body-model-gender", choices=SMPLX_GENDERS, default="neutral")' in source


def test_orchestrator_threads_profiled_gender_to_final_rigging_bridge() -> None:
    source = text("bodyrig/sith_fitter_orchestrator.py")
    assert 'body_model_gender: str = "neutral"' in source
    assert 'BODY_MODEL_GENDER_ENV = "BODYRIG_SITH_BODY_MODEL_GENDER"' in source
    assert '"sith_smplx_vrm_fitter_gender.py"' in source
    assert '"--bodyrig-smplx-gender"' in source
    assert 'parser.add_argument("--body-model-gender", choices=SMPLX_GENDERS, default=None)' in source
    assert "resolved_gender = args.body_model_gender or _default_body_model_gender()" in source
