from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_historical_gate_a_resume_wrapper_is_checkout_bound() -> None:
    wrapper = (ROOT / "resume-body-job.ps1").read_text(encoding="utf-8")
    resume = (ROOT / "bodyrig" / "resume_body_job.py").read_text(encoding="utf-8")

    assert "$PSVersionTable.PSVersion.Major -lt 7" in wrapper
    assert "bodyrig\\__init__.py" in wrapper
    assert "$env:PYTHONPATH = $repoRoot" in wrapper
    assert "pathlib.Path(bodyrig.__file__).resolve()" in wrapper
    assert "Expected checkout authority" in wrapper
    assert "-m bodyrig.resume_body_job" in wrapper
    assert "operator_checkout_status()" in resume
    assert 'if producer_revision == validator_revision:' in resume
    assert 'resumed_without_clone_rerun"] = True' in resume
