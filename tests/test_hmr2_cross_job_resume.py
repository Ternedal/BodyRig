from __future__ import annotations

import hashlib
from pathlib import Path

from bodyrig.bridges import hmr2_config
from bodyrig.bridges import hmr2_resume_bridge as resume


def test_recovery_routes_through_cross_job_resume_layer() -> None:
    assert hmr2_config.bridge_script_path().name == "hmr2_resume_bridge.py"


def test_global_cache_key_is_source_sha_and_pinned_revision_not_job_index(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BODYRIG_RECOVERY_CACHE_DIR", str(tmp_path))
    source_sha = "a" * 64
    pkl_path, meta_path = resume._global_paths(source_sha)

    assert source_sha in str(pkl_path)
    assert pkl_path.name == "phalp.pkl"
    assert meta_path.name == "meta.json"
    assert resume._revision_namespace() in str(pkl_path)


def test_global_cache_meta_is_bound_to_exact_bytes_and_adapter_revision(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BODYRIG_RECOVERY_CACHE_DIR", str(tmp_path))
    source_sha = "b" * 64
    pkl_path, _ = resume._global_paths(source_sha)
    pkl_path.parent.mkdir(parents=True, exist_ok=True)
    pkl_path.write_bytes(b"raw-phalp-fixture")
    pkl_sha = hashlib.sha256(pkl_path.read_bytes()).hexdigest()

    meta = {
        "format": resume.GLOBAL_FORMAT,
        "version": resume.GLOBAL_VERSION,
        "adapter": resume.ADAPTER_NAME,
        "revision": resume.ADAPTER_REVISION,
        "source_sha256": source_sha,
        "pkl_sha256": pkl_sha,
    }
    assert resume._valid_global_meta(meta, source_sha256=source_sha, pkl_path=pkl_path) is True

    wrong_source = dict(meta, source_sha256="c" * 64)
    assert resume._valid_global_meta(wrong_source, source_sha256=source_sha, pkl_path=pkl_path) is False

    wrong_revision = dict(meta, revision="other-recovery-revision")
    assert resume._valid_global_meta(wrong_revision, source_sha256=source_sha, pkl_path=pkl_path) is False

    pkl_path.write_bytes(b"tampered")
    assert resume._valid_global_meta(meta, source_sha256=source_sha, pkl_path=pkl_path) is False


def test_legacy_import_contract_reuses_raw_phalp_without_reusing_source_index() -> None:
    text = Path(resume.__file__).read_text(encoding="utf-8")
    assert 'meta.get("source_sha256") != source_sha256' in text
    assert 'meta.get("adapter") != ADAPTER_NAME' in text
    assert 'meta.get("revision") != ADAPTER_REVISION' in text
    assert 'meta.get("source_index")' not in text
    assert 'observation_root.glob("*/selected-segments/bodyrig-recovery-checkpoints/*.phalp.json")' in text
    assert "Current source_index is applied only when" in text


def test_workspace_local_checkpoint_layer_remains_authoritative_for_canonical_state() -> None:
    text = Path(resume.__file__).read_text(encoding="utf-8")
    assert "_legacy_load_raw_checkpoint" in text
    assert "_legacy_publish_raw_checkpoint" in text
    assert "checkpoint.main()" in text
    assert "Canonical checkpoints, status and logs remain workspace-local" in text
