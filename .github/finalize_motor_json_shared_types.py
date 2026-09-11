from pathlib import Path

SHIM = Path("reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs")
TEST = Path("tests/test_reference_renderer_json_utility_guard.py")

source = SHIM.read_text(encoding="utf-8")
old = '''            if (!versionMatch.Success)
            {
                // ApplyMotorJson will reject an unsupported or malformed version.
                // Do not guess a schema version at the raw boundary.
                return;
            }
'''
new = '''            if (!versionMatch.Success)
            {
                // Once a payload identifies itself as Motor State, do not let a
                // malformed version bypass the raw guard and rely on JsonUtility
                // coercion. The canonical contracts expose integer versions 1..3.
                throw new ArgumentException("Motor State requires integer version 1, 2, or 3");
            }
'''
if source.count(old) != 1:
    raise SystemExit(f"version anchor count={source.count(old)}")
SHIM.write_text(source.replace(old, new, 1), encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
needle = '''    assert "VersionPattern" in shim
    assert 'Groups["version"].Value' in shim
'''
replacement = '''    assert "VersionPattern" in shim
    assert 'Groups["version"].Value' in shim
    assert "Motor State requires integer version 1, 2, or 3" in shim
'''
if test.count(needle) != 1:
    raise SystemExit(f"test anchor count={test.count(needle)}")
TEST.write_text(test.replace(needle, replacement, 1), encoding="utf-8")
