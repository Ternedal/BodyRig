from pathlib import Path

shim = Path('reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs')
source = shim.read_text(encoding='utf-8')

old = 'using System;\nusing System.Collections.Generic;'
new = 'using System;\nusing System.Collections.Generic;\nusing System.Globalization;'
if old not in source:
    raise SystemExit('using anchor missing')
source = source.replace(old, new, 1)

old = '                RequireIntegerToken(raw, "duration_ms");'
new = '                RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L);'
if old not in source:
    raise SystemExit('duration anchor missing')
source = source.replace(old, new, 1)

old = '            RequireIntegerMember(fields, "elapsed_ms", "speech");'
new = '            RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);'
if old not in source:
    raise SystemExit('speech anchor missing')
source = source.replace(old, new, 1)

anchor = '''        private static void RequireIntegerMember(\n            Dictionary<string, string> members,\n            string field,\n            string context)\n        {\n            if (!members.TryGetValue(field, out var raw))\n            {\n                throw new ArgumentException($"Motor State {context} is missing required field: {field}");\n            }\n            RequireIntegerToken(raw, context + "." + field);\n        }\n\n'''
insert = anchor + '''        private static void RequireIntegerRangeMember(\n            Dictionary<string, string> members,\n            string field,\n            string context,\n            long minimum,\n            long maximum)\n        {\n            if (!members.TryGetValue(field, out var raw))\n            {\n                throw new ArgumentException($"Motor State {context} is missing required field: {field}");\n            }\n            RequireIntegerRangeToken(raw, context + "." + field, minimum, maximum);\n        }\n\n'''
if anchor not in source:
    raise SystemExit('integer member helper anchor missing')
source = source.replace(anchor, insert, 1)

anchor = '''        private static void RequireIntegerToken(string raw, string context)\n        {\n            if (!Regex.IsMatch(raw.Trim(), "^(?:" + JsonIntegerPattern + ")$", RegexOptions.CultureInvariant))\n            {\n                throw new ArgumentException($"Motor State {context} requires an integer JSON token");\n            }\n        }\n\n'''
insert = anchor + '''        private static void RequireIntegerRangeToken(\n            string raw,\n            string context,\n            long minimum,\n            long maximum)\n        {\n            RequireIntegerToken(raw, context);\n            if (!long.TryParse(\n                    raw.Trim(),\n                    NumberStyles.AllowLeadingSign,\n                    CultureInfo.InvariantCulture,\n                    out var value) ||\n                value < minimum || value > maximum)\n            {\n                throw new ArgumentOutOfRangeException(\n                    context,\n                    $"Motor State integer value must be in {minimum}..{maximum}");\n            }\n        }\n\n'''
if anchor not in source:
    raise SystemExit('integer token helper anchor missing')
source = source.replace(anchor, insert, 1)
shim.write_text(source, encoding='utf-8')

test = Path('tests/test_reference_renderer_json_utility_guard.py')
tests = test.read_text(encoding='utf-8')
anchor = '''    assert 'ValidateDuration(root);' in validate\n    assert 'RequireIntegerToken(raw, "duration_ms")' in validate\n'''
replacement = '''    assert 'ValidateDuration(root);' in validate\n    assert 'RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L)' in validate\n'''
if anchor not in tests:
    raise SystemExit('duration test anchor missing')
tests = tests.replace(anchor, replacement, 1)
anchor = '''    assert 'RequireIntegerMember(fields, "elapsed_ms", "speech")' in speech\n'''
replacement = '''    assert 'RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L)' in speech\n'''
if anchor not in tests:
    raise SystemExit('speech test anchor missing')
tests = tests.replace(anchor, replacement, 1)

tests += '''\n\ndef test_raw_integer_ranges_are_checked_before_unity_int_coercion() -> None:\n    source = SHIM.read_text(encoding="utf-8")\n    helper = source[source.index("private static void RequireIntegerRangeToken") :]\n    assert "long.TryParse(" in helper\n    assert "NumberStyles.AllowLeadingSign" in helper\n    assert "CultureInfo.InvariantCulture" in helper\n    assert "value < minimum || value > maximum" in helper\n    assert "ArgumentOutOfRangeException" in helper\n'''
test.write_text(tests, encoding='utf-8')
