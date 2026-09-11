from pathlib import Path

TEST = Path("tests/test_reference_renderer_json_utility_guard.py")

text = TEST.read_text(encoding="utf-8")
old = '''    assert 'RequireStringMember(root, "body_id", "root")' in validate
    assert 'RequireStringMember(root, "utterance_id", "root")' in validate
'''
new = '''    assert 'root, "body_id", "root", 1, 160, "^[a-z0-9æøå_-]+$"' in validate
    assert 'root, "utterance_id", "root", 1, 160, "^[A-Za-z0-9._:-]+$"' in validate
'''
if text.count(old) != 1:
    raise RuntimeError("expected legacy root string assertions exactly once")
text = text.replace(old, new, 1)
old = '''    assert 'RequireStringMember(fields, "viseme", "speech")' in speech
'''
new = '''    assert 'fields, "viseme", "speech", 1, 32, "^[A-Za-z0-9._-]+$"' in speech
'''
if text.count(old) != 1:
    raise RuntimeError("expected legacy viseme string assertion exactly once")
text = text.replace(old, new, 1)
TEST.write_text(text.rstrip() + "\n", encoding="utf-8")
