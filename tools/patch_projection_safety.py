from pathlib import Path

p = Path('bodyrig/stash_source.py')
s = p.read_text(encoding='utf-8')

anchor = '''def _number(value: Any) -> float:\n    try:\n        parsed = float(value or 0)\n    except (TypeError, ValueError):\n        return 0.0\n    return parsed if math.isfinite(parsed) and parsed >= 0 else 0.0\n\n\n'''
assert s.count(anchor) == 1
addition = r'''def _projection_is_unsupported(*, width: int, height: int, tags: Iterable[str]) -> bool:
    """Fail closed on source geometry the flat-frame analyzer cannot interpret safely."""
    normalized_tags = {str(value or "").strip().lower() for value in tags if str(value or "").strip()}
    joined_tags = " ".join(sorted(normalized_tags))
    explicit_tokens = (
        "vr180",
        "vr360",
        "virtual reality",
        "side-by-side",
        "side by side",
        "over-under",
        "over under",
        "equirect",
        "spherical",
        "panorama",
        "panoramic",
    )
    if (
        any(tag in {"vr", "sbs"} or tag.startswith("vr ") or tag.endswith(" vr") for tag in normalized_tags)
        or any(token in joined_tags for token in explicit_tokens)
    ):
        return True

    # The current observation analyzer consumes raw flat frames and has no
    # equirectangular/VR reprojection. High-resolution ~2:1 material is therefore
    # projection-ambiguous even when Stash has no useful VR tags. These exact
    # geometries are common for 180/360 exports and include the real rig sources
    # that produced a severely distorted human-fidelity result.
    if width >= 3840 and height >= 1800:
        ratio = float(width) / float(height) if height > 0 else 0.0
        if 1.95 <= ratio <= 2.05:
            return True
    return False


'''
s = s.replace(anchor, anchor + addition)

anchor2 = '''            width = int(_number(file_info.get("width")))\n            height = int(_number(file_info.get("height")))\n            duration = _number(file_info.get("duration"))\n'''
replacement2 = '''            width = int(_number(file_info.get("width")))\n            height = int(_number(file_info.get("height")))\n            if _projection_is_unsupported(width=width, height=height, tags=tags):\n                # Never feed unsupported panoramic/stereo geometry into the raw\n                # flat-frame observation analyzer. Prefer an explicit source\n                # failure over producing physically misleading reconstruction.\n                continue\n            duration = _number(file_info.get("duration"))\n'''
assert s.count(anchor2) == 1
s = s.replace(anchor2, replacement2)
p.write_text(s, encoding='utf-8')


t = Path('tests/test_stash_source.py')
ts = t.read_text(encoding='utf-8')
old = '''    ranked = rank_sources(scenes, performer_id="7", max_sources=4)\n    assert ranked[0].path == str(best.resolve())\n    assert ranked[0].performer_count == 1\n    assert ranked[-1].path == str(low.resolve())\n    assert next(item for item in ranked if item.path == str(multi.resolve())).score < ranked[0].score\n    assert next(item for item in ranked if item.path == str(vr.resolve())).score < ranked[0].score\n\n\n'''
new = '''    ranked = rank_sources(scenes, performer_id="7", max_sources=4)\n    assert ranked[0].path == str(best.resolve())\n    assert ranked[0].performer_count == 1\n    assert ranked[-1].path == str(low.resolve())\n    assert next(item for item in ranked if item.path == str(multi.resolve())).score < ranked[0].score\n    assert all(item.path != str(vr.resolve()) for item in ranked)\n\n\ndef test_rank_rejects_untagged_high_resolution_two_to_one_projection_ambiguous_sources(tmp_path: Path):\n    flat = tmp_path / "flat-4k.mp4"\n    panoramic = []\n    for width, height in ((8192, 4096), (7168, 3584), (5120, 2560), (4320, 2160)):\n        path = tmp_path / f"pano-{width}x{height}.mp4"\n        path.write_bytes(b"fixture")\n        panoramic.append((path, width, height))\n    flat.write_bytes(b"fixture")\n\n    scenes = [_scene("flat", flat, width=3840, height=2160, framerate=60)]\n    scenes.extend(\n        _scene(f"pano-{width}", path, width=width, height=height, framerate=60)\n        for path, width, height in panoramic\n    )\n\n    ranked = rank_sources(scenes, performer_id="7", max_sources=10)\n    assert [item.path for item in ranked] == [str(flat.resolve())]\n\n\ndef test_projection_unsafe_only_sources_fail_closed_instead_of_falling_back(tmp_path: Path):\n    tagged = tmp_path / "tagged-vr.mp4"\n    ambiguous = tmp_path / "untagged-8k-2to1.mp4"\n    tagged.write_bytes(b"fixture")\n    ambiguous.write_bytes(b"fixture")\n    scenes = [\n        _scene("tagged", tagged, width=3840, height=2160, framerate=60, tags=("VR180", "SBS")),\n        _scene("ambiguous", ambiguous, width=8192, height=4096, framerate=60),\n    ]\n\n    ranked = rank_sources(scenes, performer_id="7", max_sources=10)\n    assert ranked == []\n    with pytest.raises(StashSourceError, match="no usable"):\n        build_source_manifest(\n            performer={"id": "7", "name": "Alice"},\n            candidates=ranked,\n            stash_version="x",\n            candidate_count=2,\n        )\n\n\n'''
assert ts.count(old) == 1
ts = ts.replace(old, new)
t.write_text(ts, encoding='utf-8')
