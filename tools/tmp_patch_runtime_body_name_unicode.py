from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts" / "bodyrig-runtime-assets-v1.schema.json"
TEST = ROOT / "tests" / "test_runtime_manifest_body_name_unicode_schema.py"

text = SCHEMA.read_text(encoding="utf-8")
old = '    "body_name": {"type": "string", "minLength": 1, "maxLength": 160},\n'
new = '    "body_name": {"type": "string", "minLength": 1, "maxLength": 160, "pattern": "^(?:[^\\\\uD800-\\\\uDFFF]|[\\\\uD800-\\\\uDBFF][\\\\uDC00-\\\\uDFFF])+$"},\n'
if text.count(old) != 1:
    raise SystemExit(f"expected one body_name schema line, got {text.count(old)}")
SCHEMA.write_text(text.replace(old, new, 1), encoding="utf-8")

TEST.write_text(r'''from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "contracts" / "bodyrig-runtime-assets-v1.schema.json"
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"


def _body_name_schema() -> dict[str, object]:
    contract = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return contract["properties"]["body_name"]


def test_runtime_body_name_requires_well_formed_unicode() -> None:
    body_name = _body_name_schema()
    assert body_name["type"] == "string"
    assert body_name["minLength"] == 1
    assert body_name["maxLength"] == 160
    assert body_name["pattern"] == r"^(?:[^\uD800-\uDFFF]|[\uD800-\uDBFF][\uDC00-\uDFFF])+$"


def test_runtime_body_name_unicode_pattern_accepts_valid_text_and_rejects_lone_surrogates() -> None:
    pattern = _body_name_schema()["pattern"]
    assert isinstance(pattern, str)
    assert re.fullmatch(pattern, "Anders") is not None
    assert re.fullmatch(pattern, "Anders 😀") is not None
    assert re.fullmatch(pattern, "\ud83d\ude00") is not None
    assert re.fullmatch(pattern, "\ud83d") is None
    assert re.fullmatch(pattern, "\ude00") is None


def test_runtime_manifest_guard_keeps_fail_closed_scalar_count_for_body_name() -> None:
    source = SHIM.read_text(encoding="utf-8")
    entry = source[
        source.index("internal static int ValidateRuntimeManifestJson") :
        source.index("internal static int ValidateMotorStateJson")
    ]
    assert 'RequireConstrainedStringMember(root, "body_name", "runtime manifest", 1, 160, null)' in entry
    helper = source[
        source.index("private static int CountUnicodeScalars") :
        source.index("private static void RequireNumericMember")
    ]
    assert "unpaired high surrogate" in helper
    assert "unpaired low surrogate" in helper
''', encoding="utf-8")
