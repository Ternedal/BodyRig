from pathlib import Path

SCRIPT = Path("run-fidelity-evening.ps1")
TEST = Path("tests/test_fidelity_evening_hfn_context_derivation.py")

text = SCRIPT.read_text(encoding="utf-8")
anchor = text.index('$temporaryExecutionContext = ""')
needle = 'if ([string]::IsNullOrWhiteSpace($ExecutionContext)) {'
pos = text.index(needle, anchor)
text = text[:pos] + 'try {\n    ' + text[pos:]

old = '''} else {
    $contextPath = Need-File -Path $ExecutionContext -Label "Component-gap execution context"
}
try {
    $execution = Invoke-GapExecutor'''
new = '''    } else {
        $contextPath = Need-File -Path $ExecutionContext -Label "Component-gap execution context"
    }
    $execution = Invoke-GapExecutor'''
if text.count(old) != 1:
    raise SystemExit(f"expected exactly one executor context/try boundary, found {text.count(old)}")
text = text.replace(old, new, 1)
SCRIPT.write_text(text, encoding="utf-8", newline="\n")

test = TEST.read_text(encoding="utf-8")
addition = '''\n\ndef test_temporary_context_creation_is_inside_cleanup_try() -> None:\n    text = source()\n    anchor = text.index('$temporaryExecutionContext = ""')\n    try_pos = text.index('try {', anchor)\n    derived_write_pos = text.index('[IO.File]::WriteAllText($temporaryExecutionContext, $derivedContextJson', anchor)\n    empty_write_pos = text.index('[IO.File]::WriteAllText($temporaryExecutionContext, "{}"', anchor)\n    finally_pos = text.index('} finally {', try_pos)\n    cleanup_pos = text.index('Remove-Item -LiteralPath $temporaryExecutionContext -Force', finally_pos)\n    assert try_pos < derived_write_pos < finally_pos\n    assert try_pos < empty_write_pos < finally_pos\n    assert cleanup_pos > finally_pos\n'''
if "def test_temporary_context_creation_is_inside_cleanup_try" in test:
    raise SystemExit("cleanup regression already present")
TEST.write_text(test.rstrip() + addition + "\n", encoding="utf-8", newline="\n")
