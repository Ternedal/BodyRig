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
    '''        try:\n            payload = json.loads(completed.stdout)\n        except json.JSONDecodeError as exc:\n            raise RecoveryError("recovery adapter returned invalid JSON") from exc\n''',
    '''        try:\n            payload = json.loads(completed.stdout)\n        except (json.JSONDecodeError, ValueError) as exc:\n            raise RecoveryError("recovery adapter returned invalid JSON") from exc\n''',
)

tests = Path("tests/test_recovery.py")
text = tests.read_text(encoding="utf-8").rstrip()
addition = '''\n\n\ndef test_json_command_adapter_normalizes_integer_digit_limit_error(monkeypatch, tmp_path):\n    bad = payload([frame(0), frame(100)])\n    bad["tracks"][0]["frames"][1]["confidence"] = "__HUGE_INTEGER__"\n    stdout = json.dumps(bad).replace('"__HUGE_INTEGER__"', "9" * 5000)\n    completed = subprocess.CompletedProcess(\n        args=["fixture"],\n        returncode=0,\n        stdout=stdout,\n        stderr="",\n    )\n    monkeypatch.setattr(\n        recovery_module.subprocess,\n        "run",\n        lambda *args, **kwargs: completed,\n    )\n    adapter = JsonCommandRecoveryAdapter(\n        ["fixture"],\n        name="fixture",\n        revision="fixture-v1",\n    )\n\n    with pytest.raises(RecoveryError, match="returned invalid JSON"):\n        adapter.recover([tmp_path / "source.mp4"])\n'''
if "test_json_command_adapter_normalizes_integer_digit_limit_error" in text:
    raise SystemExit("digit-limit regression already present")
tests.write_text(text + addition.rstrip() + "\n", encoding="utf-8")
