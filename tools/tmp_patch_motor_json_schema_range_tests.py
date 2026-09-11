from pathlib import Path

path = Path("tests/test_reference_renderer_json_utility_guard.py")
text = path.read_text(encoding="utf-8")

old = '''    assert 'ValidateDuration(root);' in validate
    assert 'RequireIntegerToken(raw, "duration_ms")' in validate
    speech = source[source.index("private static void ValidateSpeech") : source.index("private static void ValidatePosture")]
    assert 'RequireStringMember(fields, "state", "speech")' in speech
    assert 'RequireIntegerMember(fields, "elapsed_ms", "speech")' in speech
    assert 'RequireStringMember(fields, "viseme", "speech")' in speech
    assert 'RequireNumericMember(fields, "amplitude", "speech")' in speech
'''
new = '''    assert 'ValidateDuration(root);' in validate
    assert 'RequireIntegerToken(raw, 0L, 120000L, "duration_ms")' in validate
    speech = source[source.index("private static void ValidateSpeech") : source.index("private static void ValidatePosture")]
    assert 'var state = RequireStringMember(fields, "state", "speech")' in speech
    assert 'state != "start" && state != "update" && state != "stop"' in speech
    assert 'RequireIntegerMember(fields, "elapsed_ms", 0L, 3600000L, "speech")' in speech
    assert 'var viseme = RequireStringMember(fields, "viseme", "speech")' in speech
    assert 'viseme.Length > 32' in speech
    assert '^[A-Za-z0-9._-]+$' in speech
    assert 'RequireNumericMember(fields, "amplitude", "speech")' in speech
'''
if text.count(old) != 1:
    raise SystemExit(f"test anchor count={text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
