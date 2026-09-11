from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]


def _integer_contracts(path: Path) -> tuple[dict, dict]:
    schema = json.loads(path.read_text(encoding="utf-8"))
    return (
        dict(schema["properties"]["duration_ms"]),
        dict(schema["properties"]["speech"]["properties"]["elapsed_ms"]),
    )


def test_integer_contract_is_shared_across_motor_state_versions() -> None:
    contracts = [_integer_contracts(path) for path in SCHEMAS]
    assert all(contract == contracts[0] for contract in contracts[1:])
    duration, elapsed = contracts[0]
    assert duration == {"type": "integer", "minimum": 0, "maximum": 120000}
    assert elapsed == {"type": "integer", "minimum": 0, "maximum": 3600000}
    assert duration["maximum"] < 2**24
    assert elapsed["maximum"] < 2**24


def test_raw_integer_guard_uses_value_semantics_not_lexical_integer_spelling() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert "JsonIntegerPattern" not in source

    helper = source[
        source.index("private static bool IsIntegralJsonNumber") :
        source.index("private static void RequireIntegerToken")
    ]
    assert "fractionalDigits" in helper
    assert "explicitExponent" in helper
    assert "SaturatingSubtract(explicitExponent, fractionalDigits)" in helper
    assert "trailingZeroDigits" in helper
    assert "if (!hasNonZeroDigit) return true;" in helper
    assert "if (exponent10 >= 0L) return true;" in helper
    assert "if (exponent10 == long.MinValue) return false;" in helper
    assert "return -exponent10 <= trailingZeroDigits;" in helper

    token = source[
        source.index("private static void RequireIntegerToken") :
        source.index("private static void RequireIntegerRangeToken")
    ]
    assert "RequireNumericToken(raw, context);" in token
    assert "IsIntegralJsonNumber(raw)" in token
    assert "Regex.IsMatch" not in token


def test_integer_ranges_use_existing_exact_decimal_comparator() -> None:
    source = SHIM.read_text(encoding="utf-8")
    range_guard = source[
        source.index("private static void RequireIntegerRangeToken") :
        source.index("private static void RequireExactFields")
    ]
    assert "RequireIntegerToken(raw, context);" in range_guard
    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in range_guard
    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in range_guard
    assert "long.TryParse(" not in range_guard


def test_integer_fields_route_through_value_semantic_range_guard() -> None:
    source = SHIM.read_text(encoding="utf-8")
    duration = source[
        source.index("private static void ValidateDuration") :
        source.index("private static void ValidateSpeech")
    ]
    speech = source[
        source.index("private static void ValidateSpeech") :
        source.index("private static void ValidatePosture")
    ]
    assert 'RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L);' in duration
    assert 'RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);' in speech


def test_private_unity_wire_uses_exact_float_transport_for_bounded_integer_fields() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    speech_state = source[
        source.index("private sealed class SpeechState") :
        source.index("private sealed class ObservedEmbodimentState")
    ]
    motor_state = source[
        source.index("private sealed class MotorState") :
        source.index("[SerializeField] private BodyRigAvatarLoader")
    ]
    assert "public float elapsed_ms;" in speech_state
    assert "public int elapsed_ms;" not in speech_state
    assert "public float duration_ms;" in motor_state
    assert "public int duration_ms;" not in motor_state
    # Preserve the version-authority follow-up this patch is based on.
    assert "public float version;" in motor_state

    apply = source[
        source.index("public void ApplyMotorJson") :
        source.index("private static void ValidatePosture")
    ]
    assert 'ValidateRange(next.duration_ms, 0.0f, 120000.0f, "duration_ms");' in apply
    assert "next.speech.elapsed_ms < 0 || next.speech.elapsed_ms > 3600000" in apply
