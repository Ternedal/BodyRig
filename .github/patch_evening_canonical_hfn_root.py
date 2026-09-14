from pathlib import Path

SCRIPT = Path("run-fidelity-evening.ps1")
DERIVATION_TEST = Path("tests/test_fidelity_evening_hfn_context_derivation.py")
EXECUTION_TEST = Path("tests/test_fidelity_evening_component_gap_execution.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one occurrence, found {count}")
    return text.replace(old, new, 1)


text = SCRIPT.read_text(encoding="utf-8")
text = replace_once(text, '    [string]$HfnRoot = "",\n', '', "HfnRoot parameter")

insert_before = "function Invoke-GapExecutor {\n"
resolver = r'''function Resolve-CanonicalPersonLibrary {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )
    $previousPythonPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = $RepoRoot
        $probeCode = 'import json,pathlib,bodyrig; from bodyrig.storage import person_library; print(json.dumps({"module":str(pathlib.Path(bodyrig.__file__).resolve()),"root":str(person_library())},separators=(",",":")))'
        $raw = @(& $Python -c $probeCode 2>&1)
        if ($LASTEXITCODE -ne 0 -or $raw.Count -ne 1) {
            throw "Could not resolve canonical BodyRig person library from the current checkout."
        }
        try { $probe = ([string]$raw[0]) | ConvertFrom-Json -Depth 10 }
        catch { throw "Canonical BodyRig person-library probe returned unreadable JSON." }
        $moduleText = ([string]$probe.module).Trim()
        $rootText = ([string]$probe.root).Trim()
        if ([string]::IsNullOrWhiteSpace($moduleText) -or [string]::IsNullOrWhiteSpace($rootText)) {
            throw "Canonical BodyRig person-library probe returned empty authority."
        }
        $modulePath = [IO.Path]::GetFullPath($moduleText)
        $expectedModulePath = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\__init__.py"))
        if (-not [string]::Equals($modulePath, $expectedModulePath, [StringComparison]::OrdinalIgnoreCase)) {
            throw "BodyRig Python did not import the exact current-checkout package: $modulePath"
        }
        return Need-Directory -Path $rootText -Label "Canonical BodyRig person library root"
    } finally {
        $env:PYTHONPATH = $previousPythonPath
    }
}

'''
text = replace_once(text, insert_before, resolver + insert_before, "resolver insertion")
text = replace_once(
    text,
    '$hfnExplicitValues = @($HfnRoot, $HfnPersonId, $HfnBodyRevision)',
    '$hfnExplicitValues = @($HfnPersonId, $HfnBodyRevision)',
    "explicit HFN values",
)
text = replace_once(
    text,
    'ExecutionContext cannot be combined with HfnRoot/HfnPersonId/HfnBodyRevision; choose one explicit context authority.',
    'ExecutionContext cannot be combined with HfnPersonId/HfnBodyRevision; choose one explicit context authority.',
    "mutual exclusion message",
)
text = replace_once(
    text,
    'if ($hfnExplicitCount -ne 0 -and $hfnExplicitCount -ne 3) {\n    throw "Derived HFN context requires HfnRoot, HfnPersonId and HfnBodyRevision together; partial identity authority is refused."\n}',
    'if ($hfnExplicitCount -ne 0 -and $hfnExplicitCount -ne 2) {\n    throw "Derived HFN context requires HfnPersonId and HfnBodyRevision together; partial identity authority is refused."\n}',
    "all-or-none identity gate",
)
if text.count('$hfnExplicitCount -eq 3') != 2:
    raise SystemExit(f"expected exactly two 3-field HFN gates, found {text.count('$hfnExplicitCount -eq 3')}")
text = text.replace('$hfnExplicitCount -eq 3', '$hfnExplicitCount -eq 2')
text = replace_once(
    text,
    '$hfnRootPath = Need-Directory -Path $HfnRoot -Label "HFN person library root"',
    '$hfnRootPath = Resolve-CanonicalPersonLibrary -Python $BodyRigPython -RepoRoot $repoRoot',
    "canonical HFN root",
)
SCRIPT.write_text(text, encoding="utf-8", newline="\n")


test = DERIVATION_TEST.read_text(encoding="utf-8")
test = replace_once(test, '    assert \'[string]$HfnRoot = ""\' in text\n', '    assert \'[string]$HfnRoot = ""\' not in text\n', "HfnRoot regression")
test = replace_once(test, '    assert "HfnRoot, HfnPersonId and HfnBodyRevision together" in text\n', '    assert "HfnPersonId and HfnBodyRevision together" in text\n', "identity regression")
marker = '\n\ndef test_derived_hfn_context_is_bound_to_exact_final_face_secondary_package() -> None:\n'
new_test = r'''

def test_evening_derives_hfn_root_from_exact_current_checkout_person_library() -> None:
    text = source()
    assert "function Resolve-CanonicalPersonLibrary" in text
    assert "$env:PYTHONPATH = $RepoRoot" in text
    assert "from bodyrig.storage import person_library" in text
    assert "bodyrig.__file__" in text
    assert '$expectedModulePath = [IO.Path]::GetFullPath((Join-Path $RepoRoot "bodyrig\\__init__.py"))' in text
    assert "did not import the exact current-checkout package" in text
    assert 'Need-Directory -Path $rootText -Label "Canonical BodyRig person library root"' in text
    assert '$hfnRootPath = Resolve-CanonicalPersonLibrary -Python $BodyRigPython -RepoRoot $repoRoot' in text
    assert "$env:PYTHONPATH = $previousPythonPath" in text
'''
test = replace_once(test, marker, new_test + marker, "person-library test insertion")
test = replace_once(
    test,
    '    assert "ExecutionContext cannot be combined with HfnRoot/HfnPersonId/HfnBodyRevision" in text\n',
    '    assert "ExecutionContext cannot be combined with HfnPersonId/HfnBodyRevision" in text\n',
    "mutual exclusion regression",
)
test = replace_once(
    test,
    '    assert \'$hfnExplicitCount -eq 3 -and $expectedActionId -ne "source-bound-hfn-continuation"\' in text\n',
    '    assert \'$hfnExplicitCount -eq 2 -and $expectedActionId -ne "source-bound-hfn-continuation"\' in text\n',
    "two-field action regression",
)
DERIVATION_TEST.write_text(test, encoding="utf-8", newline="\n")


execution = EXECUTION_TEST.read_text(encoding="utf-8")
if not execution.startswith("from pathlib import Path\n"):
    raise SystemExit("unexpected component-gap execution test imports")
execution = execution.replace("from pathlib import Path\n", "import re\nfrom pathlib import Path\n", 1)
needle = '    assert \'$contextPath = Need-File -Path $ExecutionContext\' in text\n'
execution = replace_once(
    execution,
    needle,
    needle + '    assert re.search(r"person-[0-9a-f]{32}", text) is None\n',
    "canonical person literal regression",
)
execution = replace_once(execution, "        'person-',\n", "", "overbroad person forbidden token")
EXECUTION_TEST.write_text(execution, encoding="utf-8", newline="\n")
