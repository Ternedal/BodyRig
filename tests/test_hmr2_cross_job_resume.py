from __future__ import annotations

import hashlib
from pathlib import Path

from bodyrig.bridges import hmr2_config
from bodyrig.bridges import hmr2_resume_bridge as resume


SAMPLING_STRIDE = 2


def test_recovery_routes_through_cross_job_resume_layer() -> None:
    assert hmr2_config.bridge_script_path().name == "hmr2_resume_bridge.py"
    assert f"s:{hmr2_config.RECOVERY_TEMPORAL_SAMPLING_REVISION}" in hmr2_config.ADAPTER_REVISION
    assert hmr2_config.RECOVERY_TEMPORAL_SAMPLING_POLICY == "phalp-frame-stride-max-15fps-v1"


def test_global_cache_key_is_source_sha_and_pinned_revision_not_job_index(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BODYRIG_RECOVERY_CACHE_DIR", str(tmp_path))
    source_sha = "a" * 64
    pkl_path, meta_path = resume._global_paths(source_sha)

    assert source_sha in str(pkl_path)
    assert pkl_path.name == "phalp.pkl"
    assert meta_path.name == "meta.json"
    assert resume._revision_namespace() in str(pkl_path)


def test_global_cache_meta_is_bound_to_exact_bytes_revision_policy_and_stride(monkeypatch, tmp_path: Path) -> None:
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
        "sampling_policy": resume.RECOVERY_TEMPORAL_SAMPLING_POLICY,
        "sampling_stride": SAMPLING_STRIDE,
        "source_sha256": source_sha,
        "pkl_sha256": pkl_sha,
    }
    assert resume._valid_global_meta(
        meta,
        source_sha256=source_sha,
        sampling_stride=SAMPLING_STRIDE,
        pkl_path=pkl_path,
    ) is True

    wrong_source = dict(meta, source_sha256="c" * 64)
    assert resume._valid_global_meta(
        wrong_source,
        source_sha256=source_sha,
        sampling_stride=SAMPLING_STRIDE,
        pkl_path=pkl_path,
    ) is False

    wrong_revision = dict(meta, revision="other-recovery-revision")
    assert resume._valid_global_meta(
        wrong_revision,
        source_sha256=source_sha,
        sampling_stride=SAMPLING_STRIDE,
        pkl_path=pkl_path,
    ) is False

    wrong_policy = dict(meta, sampling_policy="uncapped")
    assert resume._valid_global_meta(
        wrong_policy,
        source_sha256=source_sha,
        sampling_stride=SAMPLING_STRIDE,
        pkl_path=pkl_path,
    ) is False

    assert resume._valid_global_meta(
        meta,
        source_sha256=source_sha,
        sampling_stride=1,
        pkl_path=pkl_path,
    ) is False

    pkl_path.write_bytes(b"tampered")
    assert resume._valid_global_meta(
        meta,
        source_sha256=source_sha,
        sampling_stride=SAMPLING_STRIDE,
        pkl_path=pkl_path,
    ) is False


def test_resume_load_forwards_sampling_stride_to_workspace_checkpoint(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_legacy(root, **kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr(resume, "_legacy_load_raw_checkpoint", fake_legacy)
    monkeypatch.setattr(resume, "_load_global_raw", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(resume, "_discover_legacy_raw", lambda *_args, **_kwargs: None)

    assert resume._load_raw_checkpoint(
        tmp_path,
        source_index=3,
        source_sha256="d" * 64,
        sampling_stride=4,
    ) is None
    assert seen == {
        "source_index": 3,
        "source_sha256": "d" * 64,
        "sampling_stride": 4,
    }


def test_resume_publish_forwards_full_sampling_contract(monkeypatch, tmp_path: Path) -> None:
    source_pkl = tmp_path / "source.pkl"
    source_pkl.write_bytes(b"fixture")
    local = tmp_path / "local.pkl"
    local.write_bytes(b"local")
    seen: dict[str, object] = {}
    published: dict[str, object] = {}

    def fake_legacy(root, **kwargs):
        seen.update(kwargs)
        return local

    def fake_publish_global(**kwargs):
        published.update(kwargs)
        return tmp_path / "global.pkl"

    monkeypatch.setattr(resume, "_legacy_publish_raw_checkpoint", fake_legacy)
    monkeypatch.setattr(resume, "_publish_global_file", fake_publish_global)

    result = resume._publish_raw_checkpoint(
        tmp_path,
        source_index=1,
        source_sha256="e" * 64,
        source_fps=60.0,
        sampling_stride=4,
        effective_fps=15.0,
        source_pkl=source_pkl,
    )

    assert result == local
    assert seen["source_index"] == 1
    assert seen["source_sha256"] == "e" * 64
    assert seen["source_fps"] == 60.0
    assert seen["sampling_stride"] == 4
    assert seen["effective_fps"] == 15.0
    assert published == {
        "source_sha256": "e" * 64,
        "sampling_stride": 4,
        "source_pkl": local,
    }


def test_legacy_import_contract_never_accepts_uncapped_or_wrong_stride() -> None:
    text = Path(resume.__file__).read_text(encoding="utf-8")
    assert 'meta.get("source_sha256") != source_sha256' in text
    assert 'meta.get("adapter") != ADAPTER_NAME' in text
    assert 'meta.get("revision") != ADAPTER_REVISION' in text
    assert 'meta.get("sampling_policy") != RECOVERY_TEMPORAL_SAMPLING_POLICY' in text
    assert 'meta.get("sampling_stride") != sampling_stride' in text
    assert 'observation_root.glob("*/selected-segments/bodyrig-recovery-checkpoints/*.phalp.json")' in text


def test_workspace_local_checkpoint_layer_remains_authoritative_for_canonical_state() -> None:
    text = Path(resume.__file__).read_text(encoding="utf-8")
    assert "_legacy_load_raw_checkpoint" in text
    assert "_legacy_publish_raw_checkpoint" in text
    assert "checkpoint.main()" in text
    assert "Canonical checkpoints, status and logs remain workspace-local" in text
