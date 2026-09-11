from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
TEST = ROOT / "tests" / "test_reference_renderer_integer_schema_parity.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(DRIVER, "            public int elapsed_ms;", "            public float elapsed_ms;")
replace_once(DRIVER, "            public int duration_ms;", "            public float duration_ms;")

text = TEST.read_text(encoding="utf-8")
if "DRIVER = REPO" not in text:
    text = text.replace(
        'SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"\n',
        'SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"\nDRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"\n',
        1,
    )
text += '''\n\ndef test_unity_integer_wire_transport_accepts_schema_number_spellings_exactly() -> None:\n    source = DRIVER.read_text(encoding="utf-8")\n    speech = source[\n        source.index("private sealed class SpeechState") :\n        source.index("private sealed class ObservedEmbodimentState")\n    ]\n    motor = source[\n        source.index("private sealed class MotorState") :\n        source.index("[SerializeField] private BodyRigAvatarLoader")\n    ]\n    assert "public float elapsed_ms;" in speech\n    assert "public int elapsed_ms;" not in speech\n    assert "public float duration_ms;" in motor\n    assert "public int duration_ms;" not in motor\n\n    contracts = [_integer_contracts(path) for path in SCHEMAS]\n    duration, elapsed = contracts[0]\n    assert duration["maximum"] < 2**24\n    assert elapsed["maximum"] < 2**24\n\n    apply = source[\n        source.index("public void ApplyMotorJson") :\n        source.index("private static void ValidatePosture")\n    ]\n    assert 'ValidateRange(next.duration_ms, 0.0f, 120000.0f, "duration_ms")' in apply\n    assert "next.speech.elapsed_ms < 0 || next.speech.elapsed_ms > 3600000" in apply\n'''
TEST.write_text(text, encoding="utf-8")
