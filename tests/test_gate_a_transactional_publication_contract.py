from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (ROOT / "accept-physical-clone.ps1").read_text(encoding="utf-8")
CORE = (ROOT / "accept-physical-clone-core.ps1").read_text(encoding="utf-8")


def test_transactional_wrapper_never_gives_canonical_output_to_gate_a_core() -> None:
    assert 'Join-Path $repoRoot "accept-physical-clone-core.ps1"' in WRAPPER
    assert '"-OutputDir", $staging' in WRAPPER
    assert '"-OutputDir", $OutputDir' not in WRAPPER
    assert 'New-Item -ItemType Directory -Path $OutputDir' not in WRAPPER
    assert '$staging = Join-Path $outputParent' in WRAPPER
    assert '[Guid]::NewGuid().ToString("N")' in WRAPPER


def test_transactional_wrapper_validates_staging_before_same_parent_publication() -> None:
    core = WRAPPER.index('$coreOutput = @(& $pwshAuthority.Source @coreArgs 2>&1)')
    marker = WRAPPER.index('$stagingMarker = Join-Path $staging "bodyrig-acceptance.json"')
    structural = WRAPPER.index('-m bodyrig.rig_window_acceptance $staging')
    authority = WRAPPER.index('Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head', structural)
    race = WRAPPER.index('if (Test-Path -LiteralPath $OutputDir)', authority)
    publish = WRAPPER.index('[System.IO.Directory]::Move($staging, $OutputDir)')
    post_publish_authority = WRAPPER.index(
        'Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head',
        publish,
    )
    success = WRAPPER.index('Write-Host "BodyRig transactional Gate A publication: PASS"')
    assert core < marker < structural < authority < race < publish < post_publish_authority < success


def test_transactional_wrapper_cleans_failed_staging_and_non_authoritative_publication() -> None:
    assert '$published = $false' in WRAPPER
    assert '$published = $true' in WRAPPER
    assert 'if (-not $published -and (Test-Path -LiteralPath $staging))' in WRAPPER
    assert 'Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue' in WRAPPER
    publish = WRAPPER.index('[System.IO.Directory]::Move($staging, $OutputDir)')
    canonical_cleanup = WRAPPER.index(
        'Remove-Item -LiteralPath $OutputDir -Recurse -Force -ErrorAction SilentlyContinue',
        publish,
    )
    published_flag = WRAPPER.index('$published = $true', publish)
    assert publish < canonical_cleanup < published_flag


def test_transactional_wrapper_does_not_report_core_staging_success_as_canonical_success() -> None:
    capture = WRAPPER.index('$coreOutput = @(& $pwshAuthority.Source @coreArgs 2>&1)')
    failure_output = WRAPPER.index('foreach ($line in $coreOutput)', capture)
    publish = WRAPPER.index('[System.IO.Directory]::Move($staging, $OutputDir)')
    success = WRAPPER.index('Write-Host "BodyRig transactional Gate A publication: PASS"')
    assert capture < failure_output < publish < success
    assert WRAPPER.count('foreach ($line in $coreOutput)') == 1


def test_gate_a_evidence_core_retains_existing_high_fidelity_contract() -> None:
    assert '-m bodyrig.physical_session validate' in CORE
    assert '-m bodyrig.skin_qa $packagePath --out $skinQaPath' in CORE
    assert '-m bodyrig.mesh_topology_qa $packagePath --out $topologyQaPath' in CORE
    assert '-m bodyrig.materialize_cli $packagePath --out $runtimeDir' in CORE
    assert 'format = "bodyrig-rig-acceptance"' in CORE
    assert 'production_activation = $false' in CORE
