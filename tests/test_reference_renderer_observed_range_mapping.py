from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
MOTOR_V2 = REPO / "contracts" / "bodyrig-motor-state-v2.schema.json"
MOTOR_V3 = REPO / "contracts" / "bodyrig-motor-state-v3.schema.json"


def _observed_ranges(path: Path) -> dict[str, tuple[int, int]]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    properties = contract["properties"]["embodiment"]["properties"]["observed"]["properties"]
    return {
        field: (int(schema["minimum"]), int(schema["maximum"]))
        for field, schema in properties.items()
    }


def _guard_ranges(source: str) -> dict[str, tuple[int, int]]:
    helper = source[
        source.index("private static void ValidateObservedEmbodimentNumericRange") :
        source.index("private static void ValidateLocomotion")
    ]
    block_pattern = re.compile(
        r'(?P<cases>(?:\s*case "[A-Za-z0-9_]+":)+)\s*'
        r'RequireNumericRangeMember\(observed, field, "embodiment\.observed", '
        r'(?P<minimum>-?\d+)L, (?P<maximum>-?\d+)L\);\s*return;',
        flags=re.MULTILINE,
    )
    result: dict[str, tuple[int, int]] = {}
    for match in block_pattern.finditer(helper):
        bounds = (int(match.group("minimum")), int(match.group("maximum")))
        fields = re.findall(r'case "([A-Za-z0-9_]+)":', match.group("cases"))
        for field in fields:
            assert field not in result, field
            result[field] = bounds
    return result


def test_every_observed_embodiment_field_is_in_the_exact_schema_range_group() -> None:
    source = SHIM.read_text(encoding="utf-8")
    expected_v2 = _observed_ranges(MOTOR_V2)
    expected_v3 = _observed_ranges(MOTOR_V3)
    assert expected_v2 == expected_v3

    actual = _guard_ranges(source)
    assert actual == expected_v2
