from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
SCHEMA = REPO / "contracts" / "bodyrig-motor-state-v3.schema.json"


def test_integer_ranges_are_pinned_to_schema_before_unity_deserialization() -> None:
    source = SHIM.read_text(encoding="utf-8")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    duration = schema["properties"]["duration_ms"]
    speech = schema["properties"]["speech"]["properties"]

    assert f'RequireIntegerToken(raw, {duration["minimum"]}L, {duration["maximum"]}L, "duration_ms")' in source
    assert f'RequireIntegerMember(fields, "elapsed_ms", {speech["elapsed_ms"]["minimum"]}L, {speech["elapsed_ms"]["maximum"]}L, "speech")' in source
    assert "long.TryParse(token, out var value)" in source
    assert "value < minimum" in source
    assert "value > maximum" in source


def test_speech_state_and_viseme_constraints_match_schema() -> None:
    source = SHIM.read_text(encoding="utf-8")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    speech = schema["properties"]["speech"]["properties"]
    block = source[source.index("private static void ValidateSpeech") : source.index("private static void ValidatePosture")]

    for state in speech["state"]["enum"]:
        assert f'state != "{state}"' in block

    viseme = speech["viseme"]
    assert f"viseme.Length > {viseme['maxLength']}" in block
    assert f'"{viseme["pattern"]}"' in block
    assert "viseme.Length < 1" in block
    assert "RegexOptions.CultureInvariant" in block
