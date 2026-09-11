from pathlib import Path

DRIVER = Path("reference-renderer/Assets/BodyRig/BodyRigMotorDriver.cs")
TEST = Path("tests/test_reference_renderer_json_utility_guard.py")

source = DRIVER.read_text(encoding="utf-8")
old = '''            Validate01(next.motion.energy, "motion.energy");
            Validate01(next.motion.head_motion, "motion.head_motion");
            if (next.expression != null)
'''
new = '''            Validate01(next.motion.energy, "motion.energy");
            Validate01(next.motion.head_motion, "motion.head_motion");
            ValidateRange(next.duration_ms, 0.0f, 120000.0f, "duration_ms");
            if (next.expression != null)
'''
if source.count(old) != 1:
    raise SystemExit(f"duration anchor count={source.count(old)}")
source = source.replace(old, new, 1)

old = '''                if (next.speech.elapsed_ms < 0) throw new ArgumentOutOfRangeException("speech.elapsed_ms");
                Validate01(next.speech.amplitude, "speech.amplitude");
'''
new = '''                if (next.speech.elapsed_ms < 0 || next.speech.elapsed_ms > 3600000)
                    throw new ArgumentOutOfRangeException("speech.elapsed_ms");
                Validate01(next.speech.amplitude, "speech.amplitude");
'''
if source.count(old) != 1:
    raise SystemExit(f"speech anchor count={source.count(old)}")
source = source.replace(old, new, 1)
DRIVER.write_text(source, encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
func = test.index("def test_optional_action_objects_remain_optional() -> None:")
dead = test.index("    for method, property_name, end in (", func)
speech = test.index("    speech = source[", dead)
test = test[:dead] + test[speech:]
TEST.write_text(test, encoding="utf-8")
