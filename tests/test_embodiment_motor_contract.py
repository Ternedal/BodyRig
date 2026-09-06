import json
from pathlib import Path

import pytest

from bodyrig.embodiment_authority import EmbodimentAuthorityError, _motor


BODY_ID = "body-0123456789abcdef0123456789abcdef"
UTTERANCE = "utt-001"
OBSERVED = {"energy": 0.7, "head_motion": 0.8, "speech_motion": 0.8, "gaze_strength": 0.75}
TIMING = {
    "utterance_id": UTTERANCE,
    "events": [
        {"state": "start", "elapsed_ms": 0, "viseme": None, "amplitude": 0.1},
        {"state": "update", "elapsed_ms": 500, "viseme": "A", "amplitude": 0.4},
        {"state": "stop", "elapsed_ms": 1000, "viseme": None, "amplitude": 0.0},
    ],
}


def _write(tmp_path: Path, **changes) -> Path:
    value = {
        "type": "bodyrig-motor-state",
        "version": 2,
        "body_id": BODY_ID,
        "utterance_id": UTTERANCE,
        "motion": {"energy": 0.7, "head_motion": 0.8},
        "expression": {"emotion": "neutral", "intensity": 0.4},
        "speech": {"state": "update", "elapsed_ms": 500, "viseme": "A", "amplitude": 0.52},
        "embodiment": {"source": "modelrig-bodyprint-v1", "observed": dict(OBSERVED)},
    }
    value.update(changes)
    path = tmp_path / "motor.json"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


def test_m4_rejects_out_of_range_machine_motion(tmp_path: Path) -> None:
    path = _write(tmp_path, motion={"energy": 4.0, "head_motion": 0.8})
    with pytest.raises(EmbodimentAuthorityError, match="motion.energy"):
        _motor(path, body_id=BODY_ID, expected_observed=OBSERVED, timing=TIMING)


def test_m4_rejects_noncanonical_expression_token(tmp_path: Path) -> None:
    path = _write(tmp_path, expression={"emotion": "Not Valid!", "intensity": 0.4})
    with pytest.raises(EmbodimentAuthorityError, match="expression emotion"):
        _motor(path, body_id=BODY_ID, expected_observed=OBSERVED, timing=TIMING)


def test_m4_rejects_malformed_optional_gesture(tmp_path: Path) -> None:
    path = _write(tmp_path, gesture={"id": "wave", "amplitude": 1.7})
    with pytest.raises(EmbodimentAuthorityError, match="gesture amplitude"):
        _motor(path, body_id=BODY_ID, expected_observed=OBSERVED, timing=TIMING)


def test_m4_rejects_speech_not_present_in_exact_voicerig_timeline(tmp_path: Path) -> None:
    path = _write(tmp_path, speech={"state": "update", "elapsed_ms": 501, "viseme": "A", "amplitude": 0.52})
    with pytest.raises(EmbodimentAuthorityError, match="not uniquely present"):
        _motor(path, body_id=BODY_ID, expected_observed=OBSERVED, timing=TIMING)
