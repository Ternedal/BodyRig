from __future__ import annotations

from pathlib import Path

TARGETS = (
    Path("run-windows-renderer-probe.ps1"),
    Path("run-quest-renderer-probe.ps1"),
    Path("record-renderer-acceptance.ps1"),
)

OLD_HELPER = "return [decimal]$Value -eq [decimal]1"
NEW_HELPER = "return $Value -eq 1"
OLD_CONTRACT = "[decimal]$contractVersion -ne [decimal]1"
NEW_CONTRACT = "$contractVersion -ne 1"

for path in TARGETS:
    text = path.read_text(encoding="utf-8")
    if OLD_HELPER not in text:
        raise SystemExit(f"missing helper pattern in {path}")
    text = text.replace(OLD_HELPER, NEW_HELPER)
    text = text.replace(OLD_CONTRACT, NEW_CONTRACT)
    path.write_text(text, encoding="utf-8", newline="\n")

test_path = Path("tests/test_low_level_physical_v1_bool_hardening.py")
text = test_path.read_text(encoding="utf-8")
old_assert = '        assert "[decimal]$Value -eq [decimal]1" in source, relative\n'
new_assert = (
    '        assert "return $Value -eq 1" in source, relative\n'
    '        assert "[decimal]$Value" not in source, relative\n'
)
if old_assert not in text:
    raise SystemExit("low-level regression no longer contains expected decimal assertion")
text = text.replace(old_assert, new_assert)

if "test_numeric_v1_guard_rejects_near_one_values" not in text:
    text += '''\n\ndef test_numeric_v1_guard_rejects_near_one_values() -> None:\n    import shutil\n    import subprocess\n\n    import pytest\n\n    pwsh = shutil.which("pwsh")\n    if pwsh is None:\n        pytest.skip("PowerShell 7 is not available")\n    helper = r"""function Test-V1Version($Value) {\n    if ($null -eq $Value -or $Value -is [bool] -or $Value -isnot [ValueType]) { return $false }\n    return $Value -eq 1\n}"""\n    cases = (\n        ('{"version":1}', True),\n        ('{"version":1.0}', True),\n        ('{"version":true}', False),\n        ('{"version":"1"}', False),\n        ('{"version":1.000000000000001}', False),\n    )\n    for payload, expected in cases:\n        expected_ps = "$true" if expected else "$false"\n        command = (\n            helper\n            + "\\n$value = ('"\n            + payload.replace("'", "''")\n            + "' | ConvertFrom-Json).version\\n"\n            + f"if ((Test-V1Version $value) -ne {expected_ps}) {{ exit 17 }}"\n        )\n        result = subprocess.run([pwsh, "-NoProfile", "-Command", command], check=False)\n        assert result.returncode == 0, payload\n'''

test_path.write_text(text, encoding="utf-8", newline="\n")
