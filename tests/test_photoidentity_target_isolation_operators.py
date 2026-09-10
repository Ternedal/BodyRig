from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_prepare_operator_allows_only_ancestor_human_evidence_and_requires_clean_head() -> None:
    text = (ROOT / "prepare-photoidentity-target-isolation.ps1").read_text(encoding="utf-8")
    assert "git -C $repoRoot status --porcelain" in text
    assert "requires an exact clean BodyRig checkout" in text
    assert "git -C $repoRoot merge-base --is-ancestor $attestationRevision $head" in text
    assert "Refusing cross-lineage evidence reuse" in text
    assert "bodyrig.rig_setup" in text
    assert "bodyrig.photoidentity_target_isolation_prepare" in text
    assert "Machine identity choice: FALSE" in text
    assert "Target-isolated source authority:  FALSE" in text
    assert "Photoidentity source authority:    FALSE" in text
    assert "Reconstruction permitted:          FALSE" in text


def test_human_operator_requires_explicit_review_and_grants_only_sampled_frame_scope() -> None:
    text = (ROOT / "record-photoidentity-target-isolation-attestation.ps1").read_text(encoding="utf-8")
    assert "[Parameter(Mandatory = $true)][switch]$ConfirmIsolation" in text
    assert "if (-not $ConfirmIsolation.IsPresent)" in text
    assert "git -C $repoRoot status --porcelain" in text
    assert "bodyrig.photoidentity_target_isolation_attestation" in text
    assert 'authority_scope -ne "isolated-sampled-frame-set-only"' in text
    assert "target_isolated_source_authority -ne $true" in text
    assert "Photoidentity source authority:   FALSE" in text
    assert "Reconstruction permitted:         FALSE" in text
    assert "Production activation:            FALSE" in text
    assert "only to the isolated sampled frame set, not the original multi-person video" in text


def test_target_isolation_bridge_reuses_pinned_recovery_authority_without_identity_model() -> None:
    text = (ROOT / "bodyrig" / "bridges" / "hmr2_target_isolation_bridge.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "base._verify_repo" in text
    assert "base._verify_phalp_install" in text
    assert "base._verify_nmr_install" in text
    assert "base._verify_cuda_loader_env" in text
    assert "base._ensure_phalp_smpl_cache" in text
    assert "canonicalize_target_isolation" in text
    assert '"machine_identity_selection": False' in text
    assert '"appearance_embeddings_exported": False' in text
    assert '"target_isolated_source_authority": False' in text
    assert '"photoidentity_source_evidence_authority": False' in text
    assert "face_recognition" not in lowered
    assert "insightface" not in lowered
    assert "visualizer" not in lowered


def test_target_isolation_path_does_not_call_clone_or_acceptance_runtime() -> None:
    prepare_text = (ROOT / "bodyrig" / "photoidentity_target_isolation_prepare.py").read_text(encoding="utf-8").lower()
    human_text = (ROOT / "bodyrig" / "photoidentity_target_isolation_attestation.py").read_text(encoding="utf-8").lower()
    for forbidden in ("clone-body", "accept-physical", "unity", "quest", "sith_smplx", "production_activation = true"):
        assert forbidden not in prepare_text
        assert forbidden not in human_text
