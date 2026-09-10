from __future__ import annotations

from pathlib import Path

from bodyrig.bridges import hmr2_resume_bridge as resume


def test_resume_loaders_accept_and_forward_full_checkpoint_timing_contract(monkeypatch, tmp_path: Path) -> None:
    source_sha = "a" * 64
    timing = (30.0, 2, 15.0)
    resume._CURRENT_TIMING.set(timing)
    monkeypatch.setattr(
        resume.checkpoint,
        "_read_json",
        lambda _path: {
            "source_fps": timing[0],
            "sampling_stride": timing[1],
            "effective_fps": timing[2],
        },
    )

    canonical_seen: dict[str, object] = {}
    raw_seen: dict[str, object] = {}

    def fake_canonical(root, **kwargs):
        canonical_seen.update(kwargs)
        return [{"track_id": "fixture"}]

    def fake_raw(root, **kwargs):
        raw_seen.update(kwargs)
        return {"fixture": True}

    monkeypatch.setattr(resume, "_legacy_load_canonical_checkpoint", fake_canonical)
    monkeypatch.setattr(resume, "_legacy_load_raw_checkpoint", fake_raw)

    canonical = resume._load_canonical_checkpoint(
        tmp_path,
        source_index=1,
        source_sha256=source_sha,
        source_fps=timing[0],
        sampling_stride=timing[1],
        effective_fps=timing[2],
    )
    raw = resume._load_raw_checkpoint(
        tmp_path,
        source_index=1,
        source_sha256=source_sha,
        source_fps=timing[0],
        sampling_stride=timing[1],
        effective_fps=timing[2],
    )

    expected = {
        "source_index": 1,
        "source_sha256": source_sha,
        "source_fps": 30.0,
        "sampling_stride": 2,
        "effective_fps": 15.0,
    }
    assert canonical == [{"track_id": "fixture"}]
    assert raw == {"fixture": True}
    assert canonical_seen == expected
    assert raw_seen == expected


def test_resume_loaders_fail_closed_when_explicit_timing_differs_from_sampling_snapshot(monkeypatch, tmp_path: Path) -> None:
    resume._CURRENT_TIMING.set((30.0, 2, 15.0))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("mismatched timing must not reach legacy checkpoint loaders")

    monkeypatch.setattr(resume, "_legacy_load_canonical_checkpoint", forbidden)
    monkeypatch.setattr(resume, "_legacy_load_raw_checkpoint", forbidden)
    monkeypatch.setattr(resume, "_load_global_raw", forbidden)
    monkeypatch.setattr(resume, "_discover_legacy_raw", forbidden)

    assert resume._load_canonical_checkpoint(
        tmp_path,
        source_index=0,
        source_sha256="b" * 64,
        source_fps=29.97,
        sampling_stride=2,
        effective_fps=14.985,
    ) is None
    assert resume._load_raw_checkpoint(
        tmp_path,
        source_index=0,
        source_sha256="b" * 64,
        source_fps=29.97,
        sampling_stride=2,
        effective_fps=14.985,
    ) is None
