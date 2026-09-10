from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bodyrig.bridges import hmr2_config
from bodyrig.bridges import hmr2_resume_bridge as resume


SOURCE_FPS = 30.0
SAMPLING_STRIDE = 2
EFFECTIVE_FPS = 15.0


def _timing_meta(*, source_fps: float = SOURCE_FPS, effective_fps: float = EFFECTIVE_FPS) -> dict:
    return {
        "source_fps": source_fps,
        "sampling_stride": SAMPLING_STRIDE,
        "effective_fps": effective_fps,
    }


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


def test_global_cache_meta_is_bound_to_exact_bytes_revision_policy_and_timing(monkeypatch, tmp_path: Path) -> None:
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
        "source_fps": SOURCE_FPS,
        "sampling_stride": SAMPLING_STRIDE,
        "effective_fps": EFFECTIVE_FPS,
        "source_sha256": source_sha,
        "pkl_sha256": pkl_sha,
    }

    def valid(payload: dict, **overrides) -> bool:
        kwargs = {
            "source_sha256": source_sha,
            "source_fps": SOURCE_FPS,
            "sampling_stride": SAMPLING_STRIDE,
            "effective_fps": EFFECTIVE_FPS,
            "pkl_path": pkl_path,
        }
        kwargs.update(overrides)
        return resume._valid_global_meta(payload, **kwargs)

    assert valid(meta) is True
    assert valid(dict(meta, source_sha256="c" * 64)) is False
    assert valid(dict(meta, revision="other-recovery-revision")) is False
    assert valid(dict(meta, sampling_policy="uncapped")) is False
    assert valid(meta, sampling_stride=1) is False
    assert valid(meta, source_fps=29.97, effective_fps=14.985) is False
    assert valid(dict(meta, effective_fps=14.99)) is False

    pkl_path.write_bytes(b"tampered")
    assert valid(meta) is False


def test_sampling_probe_records_timing_for_follow_on_cache_validation(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "segment.mp4"
    monkeypatch.setattr(resume, "_legacy_sampling_details", lambda _source: (60.0, 4, 15.0))

    assert resume._sampling_details(source) == (60.0, 4, 15.0)
    assert resume._current_timing(4) == (60.0, 4, 15.0)
    assert resume._current_timing(2) is None


def test_workspace_canonical_cache_rejects_same_stride_with_different_fps(monkeypatch, tmp_path: Path) -> None:
    source_sha = "c" * 64
    path = resume.checkpoint._canonical_path(tmp_path, 0)
    path.write_text(json.dumps(_timing_meta()) + "\n", encoding="utf-8")
    resume._CURRENT_TIMING.set((29.97, SAMPLING_STRIDE, 14.985))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("timing-mismatched canonical checkpoint must not reach legacy reuse")

    monkeypatch.setattr(resume, "_legacy_load_canonical_checkpoint", forbidden)
    assert resume._load_canonical_checkpoint(
        tmp_path,
        source_index=0,
        source_sha256=source_sha,
        sampling_stride=SAMPLING_STRIDE,
    ) is None


def test_workspace_raw_cache_forwards_only_after_timing_matches(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}
    source_sha = "d" * 64
    raw_meta = resume.checkpoint._raw_meta_path(tmp_path, 3)
    raw_meta.write_text(json.dumps(_timing_meta()) + "\n", encoding="utf-8")
    resume._CURRENT_TIMING.set((SOURCE_FPS, SAMPLING_STRIDE, EFFECTIVE_FPS))

    def fake_legacy(root, **kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr(resume, "_legacy_load_raw_checkpoint", fake_legacy)
    monkeypatch.setattr(resume, "_load_global_raw", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(resume, "_discover_legacy_raw", lambda *_args, **_kwargs: None)

    assert resume._load_raw_checkpoint(
        tmp_path,
        source_index=3,
        source_sha256=source_sha,
        sampling_stride=SAMPLING_STRIDE,
    ) is None
    assert seen == {
        "source_index": 3,
        "source_sha256": source_sha,
        "sampling_stride": SAMPLING_STRIDE,
    }


def test_workspace_raw_cache_rejects_fps_drift_before_joblib_load(monkeypatch, tmp_path: Path) -> None:
    raw_meta = resume.checkpoint._raw_meta_path(tmp_path, 0)
    raw_meta.write_text(json.dumps(_timing_meta()) + "\n", encoding="utf-8")
    resume._CURRENT_TIMING.set((29.97, SAMPLING_STRIDE, 14.985))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("timing-mismatched raw checkpoint must not reach legacy load")

    monkeypatch.setattr(resume, "_legacy_load_raw_checkpoint", forbidden)
    monkeypatch.setattr(resume, "_load_global_raw", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(resume, "_discover_legacy_raw", lambda *_args, **_kwargs: None)

    assert resume._load_raw_checkpoint(
        tmp_path,
        source_index=0,
        source_sha256="e" * 64,
        sampling_stride=SAMPLING_STRIDE,
    ) is None


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
        source_sha256="f" * 64,
        source_fps=60.0,
        sampling_stride=4,
        effective_fps=15.0,
        source_pkl=source_pkl,
    )

    assert result == local
    assert seen == {
        "source_index": 1,
        "source_sha256": "f" * 64,
        "source_fps": 60.0,
        "sampling_stride": 4,
        "effective_fps": 15.0,
        "source_pkl": source_pkl,
    }
    assert published == {
        "source_sha256": "f" * 64,
        "source_fps": 60.0,
        "sampling_stride": 4,
        "effective_fps": 15.0,
        "source_pkl": local,
    }


def test_legacy_import_contract_never_accepts_uncapped_wrong_stride_or_timing() -> None:
    text = Path(resume.__file__).read_text(encoding="utf-8")
    assert 'meta.get("source_sha256") != source_sha256' in text
    assert 'meta.get("adapter") != ADAPTER_NAME' in text
    assert 'meta.get("revision") != ADAPTER_REVISION' in text
    assert 'meta.get("sampling_policy") != RECOVERY_TEMPORAL_SAMPLING_POLICY' in text
    assert "_timing_meta_matches(" in text
    assert 'observation_root.glob("*/selected-segments/bodyrig-recovery-checkpoints/*.phalp.json")' in text


def test_workspace_local_checkpoint_layer_remains_authoritative_for_canonical_state() -> None:
    text = Path(resume.__file__).read_text(encoding="utf-8")
    assert "_legacy_load_canonical_checkpoint" in text
    assert "_legacy_load_raw_checkpoint" in text
    assert "_legacy_publish_raw_checkpoint" in text
    assert "checkpoint._sampling_details = _sampling_details" in text
    assert "checkpoint._load_canonical_checkpoint = _load_canonical_checkpoint" in text
    assert "checkpoint.main()" in text
    assert "Canonical checkpoints, status and logs remain workspace-local" in text
