from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "bodyrig" / "gate_a_resume.py").read_text(encoding="utf-8")
SCHEMA = (ROOT / "contracts" / "bodyrig-rig-acceptance-v1.schema.json").read_text(encoding="utf-8")


def test_resumed_gate_a_keeps_producer_validator_provenance_separate() -> None:
    assert '"producer_revision": producer_revision' in SOURCE
    assert '"validator_revision": validator_revision' in SOURCE
    assert '"format": FORMAT' in SOURCE
    assert '"reason": "resume-existing-clone-after-validator-contract-failure"' in SOURCE
    assert '"package_rebuilt": False' in SOURCE
    assert '"recovery_rerun": False' in SOURCE
    assert '"fitter_rerun": False' in SOURCE


def test_standard_acceptance_report_remains_v1_shape() -> None:
    report_block = SOURCE.split('report = {', 1)[1].split('report_path =', 1)[0]
    assert '"created_at": _utc_now()' in report_block
    assert '"bodyrig_revision": validator_revision' in report_block
    assert '"producer_revision"' not in report_block
    assert '"validator_revision"' not in report_block
    assert '"historical_physical_producer_bound"' not in report_block
    assert '"validator_revision_bound"' not in report_block
    assert '"additionalProperties": false' in SCHEMA


def test_resume_validates_real_shape_and_motion_evidence() -> None:
    assert 'shape_present = isinstance(shape, Mapping)' in SOURCE
    assert 'motion_present = (' in SOURCE
    assert '"source_derived_shape_present": lineage["shape_present"]' in SOURCE
    assert '"source_derived_motion_present": lineage["motion_present"]' in SOURCE
