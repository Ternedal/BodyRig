from pathlib import Path

repo = Path(__file__).resolve().parents[1]
driver = repo / 'reference-renderer/Assets/BodyRig/BodyRigMotorDriver.cs'
arm_test = repo / 'tests/test_reference_renderer_gesture_arm_ownership_contract.py'
unsupported_test = repo / 'tests/test_reference_renderer_unsupported_gesture_locomotion_arms_contract.py'

source = driver.read_text(encoding='utf-8')
old = '''        private static bool GestureOwnsRightUpperArm(GestureState gesture)\n        {\n            if (gesture == null || !IsSupportedGestureId(gesture.id))\n            {\n                return false;\n            }\n            return gesture.id == "present" || gesture.id == "neutral";\n        }\n'''
new = '''        private bool GestureOwnsRightUpperArm(GestureState gesture)\n        {\n            if (gesture == null || !IsSupportedGestureId(gesture.id))\n            {\n                return false;\n            }\n            if (gesture.id == "present")\n            {\n                // Present writes the right upper arm only as part of the full\n                // upper/lower-arm gesture. On an incomplete humanoid rig it\n                // must not steal the upper arm from locomotion if ApplyGesture\n                // will immediately fail without a lower arm.\n                return _rightUpperArm != null && _rightLowerArm != null;\n            }\n            return gesture.id == "neutral" && _rightUpperArm != null;\n        }\n'''
if source.count(old) != 1:
    raise SystemExit(f'expected one right-arm helper, found {source.count(old)}')
driver.write_text(source.replace(old, new, 1), encoding='utf-8')

for path in (arm_test, unsupported_test):
    text = path.read_text(encoding='utf-8')
    text = text.replace('private static bool GestureOwnsRightUpperArm', 'private bool GestureOwnsRightUpperArm')
    marker = '    assert \'gesture.id == "present"\' in right\n'
    if marker in text and 'return _rightUpperArm != null && _rightLowerArm != null;' not in text:
        text = text.replace(marker, marker + '    assert \'return _rightUpperArm != null && _rightLowerArm != null;\' in right\n', 1)
    neutral = '    assert \'gesture.id == "neutral"\' in right\n'
    if neutral in text and 'return gesture.id == "neutral" && _rightUpperArm != null;' not in text:
        text = text.replace(neutral, neutral + '    assert \'return gesture.id == "neutral" && _rightUpperArm != null;\' in right\n', 1)
    path.write_text(text, encoding='utf-8')
