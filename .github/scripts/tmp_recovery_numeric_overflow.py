from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one replacement target, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


recovery = Path("bodyrig/recovery.py")
replace_once(
    recovery,
    '''    out: list[float] = []\n    for item in value:\n        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):\n            raise RecoveryError(f"{field}: coordinates must be finite numbers")\n        out.append(float(item))\n''',
    '''    out: list[float] = []\n    for item in value:\n        if isinstance(item, bool) or not isinstance(item, (int, float)):\n            raise RecoveryError(f"{field}: coordinates must be finite numbers")\n        try:\n            numeric = float(item)\n        except OverflowError:\n            raise RecoveryError(f"{field}: coordinates must be finite numbers") from None\n        if not math.isfinite(numeric):\n            raise RecoveryError(f"{field}: coordinates must be finite numbers")\n        out.append(numeric)\n''',
)
replace_once(
    recovery,
    '''            confidence = raw_frame.get("confidence", 1.0)\n            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:\n                raise RecoveryError(f"tracks[{ti}].frames[{fi}]: invalid confidence")\n''',
    '''            confidence = raw_frame.get("confidence", 1.0)\n            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):\n                raise RecoveryError(f"tracks[{ti}].frames[{fi}]: invalid confidence")\n            try:\n                numeric_confidence = float(confidence)\n            except OverflowError:\n                raise RecoveryError(f"tracks[{ti}].frames[{fi}]: invalid confidence") from None\n            if not math.isfinite(numeric_confidence) or not 0.0 <= numeric_confidence <= 1.0:\n                raise RecoveryError(f"tracks[{ti}].frames[{fi}]: invalid confidence")\n''',
)
replace_once(
    recovery,
    '            frames.append(RecoveryFrame(timestamp_ms=timestamp, joints=joints, confidence=float(confidence)))\n',
    '            frames.append(RecoveryFrame(timestamp_ms=timestamp, joints=joints, confidence=numeric_confidence))\n',
)

tests = Path("tests/test_recovery.py")
replace_once(
    tests,
    '''import math\n\nimport pytest\n\nfrom bodyrig.movement_identity import require_movement_identity\nfrom bodyrig.recovery import BodyprintExtractor, RecoveryError, parse_recovery_result\n''',
    '''import json\nimport math\nimport subprocess\n\nimport pytest\n\nimport bodyrig.recovery as recovery_module\nfrom bodyrig.movement_identity import require_movement_identity\nfrom bodyrig.recovery import BodyprintExtractor, JsonCommandRecoveryAdapter, RecoveryError, parse_recovery_result\n''',
)
text = tests.read_text(encoding="utf-8").rstrip() + '''\n\n\ndef test_huge_integer_confidence_rejected_with_recovery_error():\n    bad = payload([frame(0), frame(100)])\n    bad["tracks"][0]["frames"][1]["confidence"] = 10**400\n\n    with pytest.raises(RecoveryError, match="invalid confidence"):\n        parse_recovery_result(bad)\n\n\ndef test_huge_integer_joint_coordinate_rejected_with_recovery_error():\n    bad = payload([frame(0), frame(100)])\n    bad["tracks"][0]["frames"][1]["joints"]["head"][0] = 10**400\n\n    with pytest.raises(RecoveryError, match="coordinates must be finite numbers"):\n        parse_recovery_result(bad)\n\n\ndef test_confidence_boundaries_remain_inclusive():\n    value = payload([frame(0), frame(100)])\n    value["tracks"][0]["frames"][0]["confidence"] = 0\n    value["tracks"][0]["frames"][1]["confidence"] = 1\n\n    result = parse_recovery_result(value)\n    assert [item.confidence for item in result.tracks[0].frames] == [0.0, 1.0]\n\n\ndef test_json_command_adapter_normalizes_huge_numeric_stdout(monkeypatch, tmp_path):\n    bad = payload([frame(0), frame(100)])\n    bad["tracks"][0]["frames"][1]["confidence"] = 10**400\n    completed = subprocess.CompletedProcess(\n        args=["fixture"],\n        returncode=0,\n        stdout=json.dumps(bad),\n        stderr="",\n    )\n    monkeypatch.setattr(\n        recovery_module.subprocess,\n        "run",\n        lambda *args, **kwargs: completed,\n    )\n    adapter = JsonCommandRecoveryAdapter(\n        ["fixture"],\n        name="fixture",\n        revision="fixture-v1",\n    )\n\n    with pytest.raises(RecoveryError, match="invalid confidence"):\n        adapter.recover([tmp_path / "source.mp4"])\n'''
tests.write_text(text + "\n", encoding="utf-8")
