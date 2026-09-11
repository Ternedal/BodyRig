from pathlib import Path

path = Path("reference-renderer/Assets/BodyRig/BodyRigMotorDriver.cs")
source = path.read_text(encoding="utf-8")

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
path.write_text(source.replace(old, new, 1), encoding="utf-8")
