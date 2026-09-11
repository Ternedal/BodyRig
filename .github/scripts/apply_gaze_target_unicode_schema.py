from pathlib import Path

repo = Path(__file__).resolve().parents[2]
schemas = [
    repo / "contracts" / "bodyrig-motor-state-v1.schema.json",
    repo / "contracts" / "bodyrig-motor-state-v2.schema.json",
    repo / "contracts" / "bodyrig-motor-state-v3.schema.json",
]
old = '        "target": {"type": "string", "minLength": 1, "maxLength": 127},\n'
new = '        "target": {"type": "string", "minLength": 1, "maxLength": 127, "pattern": "^(?:[^\\\\uD800-\\\\uDFFF]|[\\\\uD800-\\\\uDBFF][\\\\uDC00-\\\\uDFFF])+$"},\n'
for path in schemas:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one canonical gaze.target line, found {text.count(old)}")
    path.write_text(text.replace(old, new), encoding="utf-8")

test = repo / "tests" / "test_motor_state_gaze_target_unicode_schema.py"
test.write_text(r'''from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"


def _target_schema(path: Path) -> dict[str, object]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    return contract["properties"]["gaze"]["properties"]["target"]


def test_gaze_target_requires_well_formed_unicode_in_all_motor_state_schemas() -> None:
    targets = [_target_schema(path) for path in SCHEMAS]
    assert all(target == targets[0] for target in targets[1:])
    target = targets[0]
    assert target["type"] == "string"
    assert target["minLength"] == 1
    assert target["maxLength"] == 127
    assert target["pattern"] == r"^(?:[^\uD800-\uDFFF]|[\uD800-\uDBFF][\uDC00-\uDFFF])+$"


def test_gaze_target_unicode_pattern_accepts_valid_text_and_rejects_lone_surrogates() -> None:
    pattern = _target_schema(SCHEMAS[0])["pattern"]
    assert isinstance(pattern, str)
    assert re.fullmatch(pattern, "camera") is not None
    assert re.fullmatch(pattern, "camera 😀") is not None
    assert re.fullmatch(pattern, "\ud83d\ude00") is not None
    assert re.fullmatch(pattern, "\ud83d") is None
    assert re.fullmatch(pattern, "\ude00") is None


def test_renderer_keeps_fail_closed_surrogate_boundary() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[
        source.index("private static int CountUnicodeScalars") :
        source.index("private static void RequireNumericMember")
    ]
    assert "unpaired high surrogate" in helper
    assert "unpaired low surrogate" in helper
    assert "char.IsHighSurrogate" in helper
    assert "char.IsLowSurrogate" in helper
''', encoding="utf-8")
