from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
TEST = ROOT / "tests" / "test_reference_renderer_version_authority.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(DRIVER, "            public int version;", "            public int version { get; set; }")
replace_once(
    TEST,
    '''def test_driver_uses_raw_semantic_version_after_unity_deserialization() -> None:\n    source = DRIVER.read_text(encoding="utf-8")\n    apply = source[''',
    '''def test_driver_uses_raw_semantic_version_after_unity_deserialization() -> None:\n    source = DRIVER.read_text(encoding="utf-8")\n    motor_state = source[\n        source.index("private sealed class MotorState") :\n        source.index("[SerializeField] private BodyRigAvatarLoader")\n    ]\n    assert "public int version { get; set; }" in motor_state\n    assert "public int version;" not in motor_state\n\n    apply = source[''',
)
