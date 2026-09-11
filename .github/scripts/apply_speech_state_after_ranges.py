from pathlib import Path

repo = Path(__file__).resolve().parents[2]
shim = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
test = repo / "tests" / "test_reference_renderer_speech_state_guard.py"

source = shim.read_text(encoding="utf-8")
old = '            RequireStringMember(fields, "state", "speech");\n'
new = '''            var state = RequireStringMember(fields, "state", "speech");
            if (state != "start" && state != "update" && state != "stop")
            {
                throw new ArgumentException("Motor State speech state must be start, update, or stop");
            }
'''
if source.count(old) != 1:
    raise SystemExit(f"expected exactly one speech state string guard, found {source.count(old)}")
source = source.replace(old, new)
shim.write_text(source, encoding="utf-8")

test.write_text('''from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]


def _states(path: Path) -> list[str]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    return list(contract["properties"]["speech"]["properties"]["state"]["enum"])


def test_renderer_enforces_shared_decoded_speech_state_enum_before_unity() -> None:
    schema_states = [_states(path) for path in SCHEMAS]
    assert all(states == schema_states[0] for states in schema_states[1:])
    assert schema_states[0] == ["start", "update", "stop"]

    source = SHIM.read_text(encoding="utf-8")
    block = source[
        source.index("private static void ValidateSpeech") :
        source.index("private static void ValidatePosture")
    ]

    assert 'var state = RequireStringMember(fields, "state", "speech")' in block
    for state in schema_states[0]:
        assert f'state != "{state}"' in block
    assert "speech state must be start, update, or stop" in block


def test_speech_state_enum_runs_after_structural_json_string_decoding() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert "TryParseStringToken" in source
    assert "ReadJsonString" in source
    helper = source[
        source.index("private static string RequireStringMember") :
        source.index("private static string RequireConstrainedStringMember")
    ]
    assert "TryParseStringToken(raw, out var value)" in helper
''', encoding="utf-8")
