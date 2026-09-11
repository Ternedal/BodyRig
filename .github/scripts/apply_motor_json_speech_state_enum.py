from pathlib import Path

repo = Path(__file__).resolve().parents[2]
shim_path = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
test_path = repo / "tests" / "test_reference_renderer_speech_state_guard.py"

shim = shim_path.read_text(encoding="utf-8")
old = '''            RequireAllowedAndRequiredFields(fields, SpeechAllowedFields, SpeechRequiredFields, "speech");
            RequireStringMember(fields, "state", "speech");
            RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);
'''
new = '''            RequireAllowedAndRequiredFields(fields, SpeechAllowedFields, SpeechRequiredFields, "speech");
            var state = RequireStringMember(fields, "state", "speech");
            if (state != "start" && state != "update" && state != "stop")
            {
                throw new ArgumentException("Motor State speech state must be start, update, or stop");
            }
            RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);
'''
assert old in shim
assert "speech state must be start, update, or stop" not in shim
shim = shim.replace(old, new, 1)
shim_path.write_text(shim, encoding="utf-8")

test = '''from __future__ import annotations

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
'''
assert not test_path.exists()
test_path.write_text(test, encoding="utf-8")
