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
    core = WRAPPER.index('& $pwshAuthority.Source @coreArgs')
    marker = WRAPPER.index('$stagingMarker = Join-Path $staging "bodyrig-acceptance.json"')
    structural = WRAPPER.index('-m bodyrig.rig_window_acceptance $staging')
    authority = WRAPPER.index('Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head', structural)
    race = WRAPPER.index('if (Test-Path -LiteralPath $OutputDir)', authority)
    publish = WRAPPER.index('[System.IO.Directory]::Move($staging, $OutputDir)')
    assert core < marker < structural < authority < race < publish


def test_transactional_wrapper_cleans_only_unpublished_staging_on_failure() -> None:
    assert '$published = $false' in WRAPPER
    assert '$published = $true' in WRAPPER
    assert 'if (-not $published -and (Test-Path -LiteralPath $staging))' in WRAPPER
    assert 'Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue' in WRAPPER
    assert 'Remove-Item -LiteralPath $OutputDir -Recurse -Force' not in WRAPPER


def test_gate_a_evidence_core_retains_existing_high_fidelity_contract() -> None:
    assert '-m bodyrig.physical_session validate' in CORE
    assert '-m bodyrig.skin_qa $packagePath --out $skinQaPath' in CORE
    assert '-m bodyrig.mesh_topology_qa $packagePath --out $topologyQaPath' in CORE
    assert '-m bodyrig.materialize_cli $packagePath --out $runtimeDir' in CORE
    assert 'format = "bodyrig-rig-acceptance"' in CORE
    assert 'production_activation = $false' in CORE
