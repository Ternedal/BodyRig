from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_integer_valued_motor_fields_use_float_wire_transport_after_raw_validation() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    speech = source[
        source.index("private sealed class SpeechState") :
        source.index("private sealed class ObservedEmbodimentState")
    ]
    motor = source[
        source.index("private sealed class MotorState") :
        source.index("[SerializeField] private BodyRigAvatarLoader")
    ]
    apply = source[
        source.index("public void ApplyMotorJson") :
        source.index("private static void ValidatePosture")
    ]

    assert "public float elapsed_ms;" in speech
    assert "public int elapsed_ms;" not in speech
    assert "public float duration_ms;" in motor
    assert "public int duration_ms;" not in motor

    raw_guard = "var validatedVersion = JsonUtility.ValidateMotorStateJson(json);"
    unity_parse = "var next = JsonUtility.FromJson<MotorState>(json);"
    assert raw_guard in apply
    assert unity_parse in apply
    assert apply.index(raw_guard) < apply.index(unity_parse)
    assert 'ValidateRange(next.duration_ms, 0.0f, 120000.0f, "duration_ms");' in apply
    assert "next.speech.elapsed_ms < 0 || next.speech.elapsed_ms > 3600000" in apply
