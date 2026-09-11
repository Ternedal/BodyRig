from pathlib import Path

path = Path("reference-renderer/Assets/BodyRig/BodyRigMotorDriver.cs")
source = path.read_text(encoding="utf-8")
old = '''                if (string.IsNullOrWhiteSpace(next.gaze.target)) throw new ArgumentException("Gaze target is required", nameof(json));
'''
new = '''                if (string.IsNullOrEmpty(next.gaze.target)) throw new ArgumentException("Gaze target is required", nameof(json));
'''
if source.count(old) != 1:
    raise SystemExit(f"gaze target validation anchor count={source.count(old)}")
path.write_text(source.replace(old, new, 1), encoding="utf-8")

test = Path("tests/test_reference_renderer_gaze_target_schema_parity.py")
test.write_text('''from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]


def _gaze_target_schema(path: Path) -> dict:
    schema = json.loads(path.read_text(encoding="utf-8"))
    return dict(schema["properties"]["gaze"]["properties"]["target"])


def test_driver_gaze_target_presence_matches_shared_schema_min_length() -> None:
    targets = [_gaze_target_schema(path) for path in SCHEMAS]
    assert all(target == targets[0] for target in targets[1:])
    target = targets[0]
    assert target["type"] == "string"
    assert target["minLength"] == 1
    assert target["maxLength"] == 127
    assert "pattern" in target

    source = DRIVER.read_text(encoding="utf-8")
    apply_motor = source[
        source.index("public void ApplyMotorJson") :
        source.index("private static void ValidatePosture")
    ]
    assert "string.IsNullOrEmpty(next.gaze.target)" in apply_motor
    assert "string.IsNullOrWhiteSpace(next.gaze.target)" not in apply_motor


def test_schema_valid_unsupported_gaze_targets_keep_fail_safe_release_path() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    apply_gaze = source[
        source.index("private bool ApplyGaze") :
        source.index("private void RestorePostureOffsetsForFrame")
    ]
    assert 'if (_state.gaze.target != "user")' in apply_gaze
    unsupported = apply_gaze[
        apply_gaze.index('if (_state.gaze.target != "user")') :
        apply_gaze.index("if (_state.gaze.strength <= 0.0f)")
    ]
    assert "_gazeStrength = 0.0f;" in unsupported
    assert "ReleaseOwnedGazeHeadRotation();" in unsupported
    assert "return false;" in unsupported
''', encoding="utf-8")
