"""Host-side scene inspector: states, isolation plumbing, cache, failure isolation.

Blender is replaced by a small fake worker (same argv contract, plain Python), so
these run everywhere. The real Blender path is covered by
tests/test_scene_inspector_blender.py when a pinned runtime is configured.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import struct
import sys
import time
from pathlib import Path

import pytest

from bodyrig import scene_inspector as si
from bodyrig import scene_inspector_cli

FAKE_WORKER = r'''
import json, os, sys, time
args = sys.argv[sys.argv.index("--") + 1:]
opt = {args[i]: args[i + 1] for i in range(0, len(args), 2)}
text = open(opt["--input"], "rb").read().decode("utf-8", "replace")
out = os.path.dirname(opt["--output"])
with open(COUNTER, "a") as handle:
    handle.write(os.path.basename(opt["--input"]) + "\n")
if "FLAKYSTART" in text and not os.path.exists(COUNTER + ".started"):
    open(COUNTER + ".started", "w").write("1")
    sys.stderr.write("ImportError: DLL load failed while importing bpy: The specified module could not be found.\n")
    sys.exit(1)
if "BADSTART" in text:
    sys.stderr.write("ImportError: DLL load failed while importing bpy: The specified module could not be found.\n")
    sys.exit(1)
if "PROGRESS" in text:
    for done in range(3):
        json.dump({"stage": "conditioning", "frames_done": done, "frames_total": 3}, open(os.path.join(out, "progress.json"), "w"))
        time.sleep(0.8)
if "STALLFRAMES" in text:  # finishes two frames, half-writes the third, then hangs
    kinds = [k for k in opt["--conditioning"].split(",") if k]
    names = {"pose": ["pose.json", "pose.png"], "openpose": ["openpose.json", "openpose.png"],
             "depth": ["depth.png"], "normal": ["normal.png"]}
    total = int(text.split("STALLFRAMES ")[1].split()[0]) if "STALLFRAMES " in text else 4
    def publish(done):
        state = {"stage": "conditioning", "frames_done": done, "frames_total": total,
                 "camera": {"type": "orthographic", "view": "front"}}
        if "BADPROGRESS" in text:
            state["frames_done"] = total + 5
        json.dump(state, open(os.path.join(out, ".p"), "w"))
        os.replace(os.path.join(out, ".p"), os.path.join(out, "progress.json"))
    for index in range(2):
        publish(index)
        for kind in kinds:
            for name in names[kind]:
                if not ("GAP" in text and index == 0 and name == "depth.png"):
                    open(os.path.join(out, f"f{index:06d}_" + name), "wb").write(b"frame %d" % index)
    publish(2)
    open(os.path.join(out, "f000002_depth.png"), "wb").write(b"half")
    time.sleep(600)
if "HANG" in text:
    time.sleep(600)
if "CRASH" in text:
    sys.exit(7)
document = {"contract": "bodyrig-scene-worker-v1", "warnings": [], "timings_ms": {"total": 1},
            "blender": {"version": "fake"}, "security": {"autoexec_enabled": False}}
if "WORKERERROR" in text:
    document["error"] = {"type": "RuntimeError", "message": "importer failed"}
else:
    document["scene"] = {"totals": {"triangles": 1}, "env": sorted(os.environ),
                         "home": os.environ.get("HOME"), "proxy": os.environ.get("HTTPS_PROXY"),
                         "cuda": os.environ.get("CUDA_VISIBLE_DEVICES"),
                         "staged": sorted(os.listdir(opt["--staging-root"]))}
    kinds = [k for k in opt["--conditioning"].split(",") if k]
    if kinds:
        if opt.get("--yaw") not in (None, "0.0"):
            document["yaw_seen"] = opt["--yaw"]
        names = {"pose": ["pose.json", "pose.png"], "openpose": ["openpose.json", "openpose.png"],
                 "depth": ["depth.png"], "normal": ["normal.png"]}
        frames = opt.get("--frames", "")
        if frames:
            start, end, step = (int(v) for v in frames.split(":"))
            prefixes = [f"f{i:06d}_" for i in range(len(range(start, end + 1, step)))]
        else:
            prefixes = [""]
        if "DROPFRAME" in text:
            prefixes = prefixes[:-1]
        for prefix in prefixes:
            for kind in kinds:
                for name in names[kind]:
                    open(os.path.join(out, prefix + name), "wb").write(("fake " + prefix + name).encode())
        document["conditioning"] = {"camera": {"type": "orthographic"}, "outputs": {}}
if "INCOMPLETE" not in text:
    document["complete"] = True
json.dump(document, open(opt["--output"], "w"))
sys.exit(3 if "WORKERERROR" in text else (139 if "TEARDOWN" in text else 0))
'''


@pytest.fixture()
def env(tmp_path: Path):
    root = tmp_path / "assets"
    root.mkdir()
    counter = tmp_path / "worker-calls.txt"
    counter.write_text("")
    worker = tmp_path / "fake_worker.py"
    worker.write_text(f"COUNTER = {str(counter)!r}\n" + FAKE_WORKER, encoding="utf-8")
    runtime = si.BlenderRuntime("module", Path(sys.executable), "fake-1", worker_script=worker)
    work = tmp_path / "work"
    work.mkdir()

    class Env:
        pass

    e = Env()
    e.root, e.counter, e.runtime, e.work = root, counter, runtime, work
    e.cache = si.SceneCache(tmp_path / "cache")
    e.out = tmp_path / "out"
    e.calls = lambda: [line for line in counter.read_text().splitlines() if line]
    return e


def _opts(**kw) -> si.InspectOptions:
    base = {"wall_seconds": 30.0, "isolation": "none", "memory_bytes": None}
    base.update(kw)
    return si.InspectOptions(**base).validate()


def _run(e, rel: str, **kw) -> dict:
    return si.inspect_asset(e.root, rel, e.out / rel.replace("/", "_"), runtime=e.runtime, cache=e.cache,
                            options=_opts(**kw), work_root=e.work)


def test_full_run_reaches_fully_analyzed_and_removes_staging(env) -> None:
    (env.root / "m.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    result = _run(env, "m.obj")
    assert result["state"] == "FULLY_ANALYZED", result["error"]
    assert result["states_reached"] == ["DISCOVERED", "SAFE_TO_INSPECT", "MINIMUM_READY", "FULLY_ANALYZED"]
    assert result["likeness_authority"] is False and result["production_activation"] is False
    assert result["minimum"]["vertices"] == 3 and result["minimum"]["faces"] == 1
    assert result["cleanup"] == {"staging_removed": True}
    assert list(env.work.iterdir()) == []
    assert result["timings_ms"]["minimum_ready_at"] <= result["timings_ms"]["fully_analyzed_at"]
    written = json.loads((env.out / "m.obj" / "scene.json").read_text())
    assert written["state"] == "FULLY_ANALYZED"


def test_child_environment_is_scrubbed(env, monkeypatch) -> None:
    monkeypatch.setenv("BODYRIG_TEST_SECRET_TOKEN", "do-not-leak")
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
    (env.root / "m.obj").write_text("v 0 0 0\n")
    scene = _run(env, "m.obj")["scene"]
    assert "BODYRIG_TEST_SECRET_TOKEN" not in scene["env"]
    assert "PYTHONPATH" not in scene["env"]
    assert scene["proxy"] == si.DEAD_PROXY
    assert scene["cuda"] == ""
    assert scene["home"] and "bodyrig-scene-" in scene["home"]
    assert {"BLENDER_USER_SCRIPTS", "BLENDER_USER_CONFIG", "BLENDER_USER_EXTENSIONS"} <= set(scene["env"])


def test_cached_repeat_does_not_start_the_worker(env) -> None:
    (env.root / "m.obj").write_text("v 0 0 0\n")
    first = _run(env, "m.obj", conditioning=("depth",))
    second = _run(env, "m.obj", conditioning=("depth",))
    assert first["cache"]["hit"] is False and second["cache"]["hit"] is True
    assert second["state"] == "FULLY_ANALYZED" and second["scene"] == first["scene"]
    assert env.calls() == ["m.obj"]
    assert (env.out / "m.obj" / "depth.png").read_bytes() == b"fake depth.png"
    assert second["timings_ms"]["total"] < 2000


def test_cache_key_changes_with_content_and_options(env) -> None:
    (env.root / "m.obj").write_text("v 0 0 0\n")
    _run(env, "m.obj")
    _run(env, "m.obj", conditioning=("pose",))
    time.sleep(0.01)
    (env.root / "m.obj").write_text("v 0 0 1\n")
    os.utime(env.root / "m.obj", ns=(time.time_ns(), time.time_ns()))
    _run(env, "m.obj")
    assert len(env.calls()) == 3


def test_tampered_cache_entry_is_ignored(env) -> None:
    (env.root / "m.obj").write_text("v 0 0 0\n")
    first = _run(env, "m.obj", conditioning=("depth",))
    entry = env.cache.objects / first["cache"]["key"][:2] / first["cache"]["key"]
    (entry / "depth.png").write_bytes(b"tampered")
    second = _run(env, "m.obj", conditioning=("depth",))
    assert second["cache"]["hit"] is False and len(env.calls()) == 2


def test_timeout_fails_only_that_asset(env) -> None:
    (env.root / "slow.obj").write_text("# HANG\nv 0 0 0\n")
    (env.root / "ok.obj").write_text("v 0 0 0\n")
    started = time.perf_counter()
    summary = si.inspect_batch(env.root, ["slow.obj", "ok.obj"], env.out, runtime=env.runtime, cache=env.cache,
                               options=_opts(wall_seconds=2.0), jobs=2, work_root=env.work)
    assert time.perf_counter() - started < 20
    states = {a["path"]: a for a in summary["assets"]}
    assert states["slow.obj"]["state"] == "FAILED" and states["slow.obj"]["error"]["code"] == "timeout"
    assert states["ok.obj"]["state"] == "FULLY_ANALYZED"
    assert summary["states"] == {"FAILED": 1, "FULLY_ANALYZED": 1}
    assert list(env.work.iterdir()) == []


@pytest.mark.parametrize("marker, code", [("CRASH", "worker_failed"), ("WORKERERROR", "worker_failed")])
def test_worker_failure_is_reported_not_raised(env, marker: str, code: str) -> None:
    (env.root / "bad.obj").write_text(f"# {marker}\n")
    result = _run(env, "bad.obj")
    assert result["state"] == "FAILED" and result["error"]["code"] == code
    assert result["cleanup"] == {"staging_removed": True}
    assert env.cache.load(result["cache"]["key"]) is None


def test_incomplete_worker_document_is_rejected(env) -> None:
    (env.root / "m.obj").write_text("# INCOMPLETE\n")
    assert _run(env, "m.obj")["error"]["code"] == "worker_contract"


def test_teardown_crash_after_a_complete_result_keeps_the_result(env) -> None:
    (env.root / "m.obj").write_text("# TEARDOWN\nv 0 0 0\n")
    result = _run(env, "m.obj")
    assert result["state"] == "FULLY_ANALYZED" and result["process"]["returncode"] == 139
    assert any("exited 139 after writing a complete result" in w for w in result["warnings"])


def test_worker_runs_from_a_copy_inside_the_job_dir(env) -> None:
    (env.root / "m.obj").write_text("v 0 0 0\n")
    seen = {}
    real = si.run_bounded

    def spy(argv, **kw):
        seen["argv"] = list(argv)
        seen["cwd"] = str(kw["cwd"])
        return real(argv, **kw)

    si.run_bounded, saved = spy, si.run_bounded
    try:
        assert _run(env, "m.obj")["state"] == "FULLY_ANALYZED"
    finally:
        si.run_bounded = saved
    script = seen["argv"][seen["argv"].index("-B") + 1]
    assert script.startswith(seen["cwd"]) and script.endswith("fake_worker.py")
    assert str(env.runtime.worker_script) not in seen["argv"]


def _gltf(uri: str) -> str:
    return json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": uri, "byteLength": 4}]})


@pytest.mark.parametrize("uri", ["../secret.bin", "%2e%2e/secret.bin", "/etc/passwd", "C:/secret.bin",
                                 "https://example.org/x.bin", "//server/share/x.bin", "sub\\x.bin", "a.bin?x=1"])
def test_unsafe_gltf_reference_fails_before_any_copy_or_worker(env, uri: str) -> None:
    (env.root / "secret.bin").write_bytes(b"SECRET")
    (env.root / "m.gltf").write_text(_gltf(uri))
    result = _run(env, "m.gltf")
    assert result["state"] == "FAILED" and result["error"]["code"] == "unsafe_reference", result["error"]
    assert "MINIMUM_READY" not in result["states_reached"]
    assert env.calls() == []


def test_glb_json_chunk_references_are_checked(env) -> None:
    payload = _gltf("../secret.bin").encode()
    payload += b" " * (-len(payload) % 4)
    glb = struct.pack("<III", 0x46546C67, 2, 20 + len(payload)) + struct.pack("<II", len(payload), 0x4E4F534A) + payload
    (env.root / "m.glb").write_bytes(glb)
    result = _run(env, "m.glb")
    assert result["error"]["code"] == "unsafe_reference"


def test_gltf_dependencies_are_staged_missing_image_only_warns(env) -> None:
    (env.root / "tex").mkdir()
    (env.root / "tex" / "geo.bin").write_bytes(b"1234")
    doc = {"asset": {"version": "2.0"}, "buffers": [{"uri": "tex/geo.bin"}, {"uri": "data:application/octet-stream;base64,AAAA"}],
           "images": [{"uri": "tex/missing.png"}]}
    (env.root / "m.gltf").write_text(json.dumps(doc))
    result = _run(env, "m.gltf")
    assert result["state"] == "FULLY_ANALYZED"
    assert [d["path"] for d in result["dependencies"]] == ["tex/geo.bin"]
    assert result["scene"]["staged"] == ["m.gltf", "tex"]
    assert any("tex/missing.png" in w for w in result["warnings"])


def test_missing_gltf_buffer_fails(env) -> None:
    (env.root / "m.gltf").write_text(_gltf("gone.bin"))
    assert _run(env, "m.gltf")["error"]["code"] == "missing_dependency"


@pytest.mark.parametrize("document", ['{"buffers": {"uri": "../x"}}', '{"buffers": ["x.bin"]}', "[1]", "{bad json"])
def test_malformed_gltf_is_invalid_not_a_crash(env, document: str) -> None:
    (env.root / "m.gltf").write_text(document)
    assert _run(env, "m.gltf")["error"]["code"] == "invalid_asset"


def test_asset_paths_are_contained(env, tmp_path: Path) -> None:
    (tmp_path / "outside.obj").write_text("v 0 0 0\n")
    assert _run(env, "../outside.obj")["error"]["code"] == "unsafe_path"
    assert _run(env, "nope.obj")["error"]["code"] == "missing_file"
    (env.root / "m.stl").write_text("solid")
    assert _run(env, "m.stl")["error"]["code"] == "unsupported_format"


def test_symlinked_asset_or_folder_is_rejected(env, tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "m.obj").write_text("v 0 0 0\n")
    try:
        (env.root / "link.obj").symlink_to(tmp_path / "real" / "m.obj")
        (env.root / "dir").symlink_to(tmp_path / "real", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert _run(env, "link.obj")["error"]["code"] == "unsafe_path"
    assert _run(env, "dir/m.obj")["error"]["code"] == "unsafe_path"


@pytest.mark.parametrize("line", ["mtllib ../outside.mtl", "mtllib /etc/outside.mtl", "mtllib C:\\x\\outside.mtl",
                                  "mtllib http://example.org/outside.mtl", "mtllib good.mtl ../outside.mtl",
                                  "mtllib %2e%2e/outside.mtl"])
def test_unsafe_obj_material_library_fails_before_blender(env, tmp_path: Path, line: str) -> None:
    (tmp_path / "outside.mtl").write_text("newmtl secret\n")
    (env.root / "good.mtl").write_text("newmtl a\n")
    (env.root / "m.obj").write_text(f"{line}\nv 0 0 0\n")
    result = _run(env, "m.obj")
    assert result["state"] == "FAILED" and result["error"]["code"] == "unsafe_reference", result["error"]
    assert env.calls() == []


def test_symlinked_material_library_or_parent_fails(env, tmp_path: Path) -> None:
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "x.mtl").write_text("newmtl secret\n")
    try:
        (env.root / "link.mtl").symlink_to(tmp_path / "outside" / "x.mtl")
        (env.root / "sub").symlink_to(tmp_path / "outside", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    for line in ("mtllib link.mtl", "mtllib sub/x.mtl"):
        (env.root / "m.obj").write_text(f"{line}\nv 0 0 0\n")
        assert _run(env, "m.obj")["error"]["code"] == "unsafe_reference", line
    assert env.calls() == []


def test_obj_material_libraries_missing_multiple_spaces_and_unsafe_textures(env) -> None:
    (env.root / "a.mtl").write_text("newmtl a\nmap_Kd -bm 1.0 skin.png\n")
    (env.root / "b.mtl").write_text("newmtl b\n")
    (env.root / "my lib.mtl").write_text("newmtl c\n")
    (env.root / "abs.mtl").write_text("newmtl d\nmap_Kd C:\\Users\\artist\\skin.png\n")
    (env.root / "m.obj").write_text("mtllib a.mtl b.mtl\nmtllib my lib.mtl\nmtllib gone.mtl\nmtllib abs.mtl\nv 0 0 0\n")
    result = _run(env, "m.obj")
    assert result["state"] == "FULLY_ANALYZED", result["error"]
    assert [d["path"] for d in result["dependencies"]] == ["a.mtl", "b.mtl", "my lib.mtl"]
    assert any("not found" in w and "gone.mtl" in w for w in result["warnings"])
    assert any("abs.mtl" in w and "may leave the asset folder" in w for w in result["warnings"])
    assert sorted(result["scene"]["staged"]) == ["a.mtl", "b.mtl", "m.obj", "my lib.mtl"]


def _prime(env, conditioning=("depth",)) -> tuple[dict, Path]:
    (env.root / "m.obj").write_text("v 0 0 0\n")
    first = _run(env, "m.obj", conditioning=conditioning)
    key = first["cache"]["key"]
    return first, env.cache.objects / key[:2] / key


def test_poisoned_cache_manifest_cannot_read_or_write_outside(env, tmp_path: Path) -> None:
    first, entry = _prime(env)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    manifest = json.loads((entry / "result.json").read_text())
    manifest["files"] = {"../../../../outside.txt": si.hashing.sha256_file(outside)}
    (entry / "result.json").write_text(json.dumps(manifest))
    second = _run(env, "m.obj", conditioning=("depth",))
    assert second["cache"]["hit"] is False and len(env.calls()) == 2
    assert outside.read_bytes() == b"outside"
    assert sorted(p.name for p in (env.out / "m.obj").iterdir()) == ["depth.png", "scene.json"]


def test_cache_file_or_entry_links_are_not_trusted(env, tmp_path: Path) -> None:
    first, entry = _prime(env)
    outside = tmp_path / "outside.png"
    outside.write_bytes((entry / "depth.png").read_bytes())
    (entry / "depth.png").unlink()
    try:
        (entry / "depth.png").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert env.cache.load(first["cache"]["key"]) is None
    moved = tmp_path / "moved-entry"
    (entry / "depth.png").unlink()
    entry.rename(moved)
    (moved / "depth.png").write_bytes(outside.read_bytes())
    entry.symlink_to(moved, target_is_directory=True)
    assert env.cache.load(first["cache"]["key"]) is None


def test_cache_store_refuses_unexpected_names(env, tmp_path: Path) -> None:
    source = tmp_path / "x"
    source.write_bytes(b"x")
    with pytest.raises(si.SceneInspectionError):
        env.cache.store("a" * 64, {}, {"../escape.png": source})
    with pytest.raises(si.SceneInspectionError):
        env.cache.load("../" + "a" * 61)
    with pytest.raises(si.SceneInspectionError):
        env.cache.load("a" * 64 + "\n")  # "$" alone would accept a trailing newline


def test_output_link_is_not_written_through(env, tmp_path: Path) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"keep")
    (env.out / "m.obj").mkdir(parents=True)
    try:
        (env.out / "m.obj" / "depth.png").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    (env.root / "m.obj").write_text("v 0 0 0\n")
    result = _run(env, "m.obj", conditioning=("depth",))
    assert result["state"] == "FAILED" and result["error"]["code"] == "unsafe_path"
    assert outside.read_bytes() == b"keep"


def test_conditioning_ready_is_timed_separately_from_metadata(env) -> None:
    (env.root / "m.obj").write_text("v 0 0 0\n")
    cold = _run(env, "m.obj", conditioning=("depth", "normal"))
    warm = _run(env, "m.obj", conditioning=("depth", "normal"))
    for result in (cold, warm):
        t = result["timings_ms"]
        assert "conditioning_ready_at" in t and t["conditioning_ready_at"] <= t["total"]
    assert cold["timings_ms"]["minimum_ready_at"] <= cold["timings_ms"]["conditioning_ready_at"]
    assert "conditioning_ready_at" not in _run(env, "m.obj")["timings_ms"]


def _inventory(env, entries: list[dict]) -> Path:
    path = env.root.parent / "inventory.json"
    path.write_text(json.dumps({"schema_version": 2, "likeness_authority": False, "assets": entries}))
    return path


def test_inventory_handoff_statuses(env) -> None:
    for index, name in enumerate(("ok.obj", "degraded.obj", "rejected.obj", "changed.obj", "unlisted.obj")):
        (env.root / name).write_text(f"v 0 0 {index}\n")  # distinct content, so no shared cache entry
    sha = si.hashing.sha256_file(env.root / "ok.obj")
    degraded_sha = si.hashing.sha256_file(env.root / "degraded.obj")
    manifest = _inventory(env, [
        {"path": "ok.obj", "status": "ok", "reasons": [], "sha256": sha, "dependencies": [], "readiness": "INVENTORIED"},
        {"path": "degraded.obj", "status": "degraded", "reasons": ["missing dependency: skin.png"], "sha256": degraded_sha,
         "dependencies": [], "readiness": "INVENTORIED"},
        {"path": "rejected.obj", "status": "rejected", "reasons": ["ValueError: path traversal"], "sha256": None,
         "dependencies": []},
        {"path": "changed.obj", "status": "ok", "reasons": [], "sha256": "0" * 64, "dependencies": []},
    ])
    inventory = si.load_inventory(manifest)
    summary = si.inspect_batch(env.root, list(inventory) + ["unlisted.obj"], env.out, runtime=env.runtime,
                               cache=env.cache, options=_opts(), inventory=inventory, work_root=env.work)
    states = {a["path"]: (a["state"], (a["error"] or {}).get("code")) for a in summary["assets"]}
    assert states == {"ok.obj": ("FULLY_ANALYZED", None), "degraded.obj": ("FULLY_ANALYZED", None),
                      "rejected.obj": ("FAILED", "inventory_rejected"), "changed.obj": ("FAILED", "inventory_mismatch"),
                      "unlisted.obj": ("FAILED", "inventory_mismatch")}
    assert sorted(env.calls()) == ["degraded.obj", "ok.obj"]
    degraded = json.loads((env.out / "degraded.obj" / "scene.json").read_text())
    assert degraded["inventory"]["status"] == "degraded" and any("inventory: degraded" in w for w in degraded["warnings"])


def test_inventory_dependencies_are_compared_not_trusted(env) -> None:
    (env.root / "a" / "tex").mkdir(parents=True)
    (env.root / "a" / "tex" / "geo.bin").write_bytes(b"1234")
    doc = {"asset": {"version": "2.0"}, "buffers": [{"uri": "tex/geo.bin"}], "images": [{"uri": "tex/skin.png"}]}
    (env.root / "a" / "m.gltf").write_text(json.dumps(doc))
    sha = si.hashing.sha256_file(env.root / "a" / "m.gltf")
    geo = si.hashing.sha256_file(env.root / "a" / "tex" / "geo.bin")
    entry = {"path": "a/m.gltf", "status": "degraded", "reasons": ["missing dependency: skin.png"], "sha256": sha,
             "dependencies": [{"path": "a/tex/geo.bin", "sha256": geo, "bytes": 4}, {"path": "a/tex/skin.png", "sha256": "1" * 64}]}
    result = si.inspect_asset(env.root, "a/m.gltf", env.out / "g", runtime=env.runtime, cache=env.cache,
                              options=_opts(), inventory_entry=entry, work_root=env.work)
    assert result["state"] == "FULLY_ANALYZED", result["error"]
    assert result["inventory"]["dependencies_not_staged"] == ["tex/skin.png"]
    entry["dependencies"][0]["sha256"] = "2" * 64
    changed = si.inspect_asset(env.root, "a/m.gltf", env.out / "g2", runtime=env.runtime, cache=env.cache,
                               options=_opts(), inventory_entry=entry, work_root=env.work)
    assert changed["error"]["code"] == "inventory_mismatch"


def test_cli_runs_from_an_inventory(tmp_path: Path) -> None:
    root = tmp_path / "a"
    root.mkdir()
    (root / "ok.obj").write_text("v 0 0 0\n")
    (root / "bad.obj").write_text("v 0 0 0\n")
    manifest = tmp_path / "inv.json"
    manifest.write_text(json.dumps({"schema_version": 2, "likeness_authority": False, "assets": [
        {"path": "ok.obj", "status": "ok", "sha256": si.hashing.sha256_file(root / "ok.obj"), "dependencies": []},
        {"path": "bad.obj", "status": "rejected", "reasons": ["x"], "sha256": None, "dependencies": []}]}))
    common = ["inspect", "--root", str(root), "--out", str(tmp_path / "o"), "--cache", str(tmp_path / "c"),
              "--minimum-only", "--inventory", str(manifest)]
    assert scene_inspector_cli.main(common) == 1
    summary = json.loads((tmp_path / "o" / "summary.json").read_text())
    assert {a["path"]: a["state"] for a in summary["assets"]} == {"ok.obj": "MINIMUM_READY", "bad.obj": "FAILED"}
    manifest.write_text(json.dumps({"schema_version": 1, "assets": []}))
    assert scene_inspector_cli.main(common) == 2


def test_source_changed_while_staging_fails(env, monkeypatch) -> None:
    (env.root / "m.obj").write_text("v 0 0 0\n")
    real_copy = si.shutil.copyfile

    def swapping_copy(src, dst, *a, **k):
        real_copy(src, dst, *a, **k)
        Path(dst).write_text("v 9 9 9\n")
        return dst

    monkeypatch.setattr(si.shutil, "copyfile", swapping_copy)
    result = _run(env, "m.obj")
    assert result["error"]["code"] == "source_changed" and env.calls() == []
    assert result["cleanup"] == {"staging_removed": True}


def test_minimum_only_needs_no_runtime(env) -> None:
    (env.root / "m.obj").write_text("v 0 0 0\n")
    result = si.inspect_asset(env.root, "m.obj", env.out, runtime=None, cache=env.cache,
                              options=_opts(minimum_only=True))
    assert result["state"] == "MINIMUM_READY" and result["minimum"]["vertices"] == 1


def test_header_probes(tmp_path: Path) -> None:
    fbx = tmp_path / "a.fbx"
    fbx.write_bytes(b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", 7400) + b"\x00" * 40)
    assert si.minimum_metadata(fbx, "fbx", 0) == {"encoding": "binary", "fbx_version": 7400}
    fbx.write_bytes(b"; FBX 7.4.0 project file\n")
    assert si.minimum_metadata(fbx, "fbx", 0)["encoding"] == "ascii"
    blend = tmp_path / "a.blend"
    blend.write_bytes(b"BLENDER-v405REND" + b"\x00" * 16)
    assert si.minimum_metadata(blend, "blend", 0)["blender_version"] == "4.5"
    blend.write_bytes(b"BLENDER17-01v0500" + b"\x00" * 16)
    assert si.minimum_metadata(blend, "blend", 0)["blender_version"] == "5.0"
    blend.write_bytes(gzip.compress(b"BLENDER_v279" + b"\x00" * 30))
    meta = si.minimum_metadata(blend, "blend", 0)
    assert meta["compression"] == "gzip" and meta["blender_version"] == "2.79" and meta["pointer_size"] == 4
    blend.write_bytes(b"\x28\xb5\x2f\xfd" + b"\x00" * 30)
    assert si.minimum_metadata(blend, "blend", 0)["compression"] == "zstd"
    blend.write_bytes(b"not a blend")
    with pytest.raises(si.SceneInspectionError):
        si.minimum_metadata(blend, "blend", 0)


def test_blender_cli_command_flags() -> None:
    exe = Path("/opt/blender/blender")
    runtime = si.BlenderRuntime("cli", exe, "4.5.15", offline_flag=True)
    argv = runtime.command(["--input", "x"], threads=3)
    assert argv[:4] == [str(exe), "--background", "--factory-startup", "--disable-autoexec"]
    assert "--offline-mode" in argv and argv[argv.index("--threads") + 1] == "3"
    assert argv[argv.index("--python") + 1] == str(si.WORKER_SCRIPT)
    assert argv.index("--") > argv.index("--python") and argv[-2:] == ["--input", "x"]
    assert not {"--enable-autoexec", "-y", "--python-use-system-env"} & set(argv)
    plain = si.BlenderRuntime("cli", Path("/b"), "4.1.0").command([], threads=1)
    assert "--offline-mode" not in plain
    venv_python = Path("/venv/bin/python")
    module = si.BlenderRuntime("module", venv_python, "4.5.15").command(["a"], threads=1)
    assert module[:3] == [str(venv_python), "-I", "-B"] and module[-2:] == ["--", "a"]


def test_bwrap_prefix_binds_only_the_job_dir_writable(tmp_path: Path) -> None:
    job = tmp_path / "job"
    blender_dir = Path("/opt/blender")
    argv = si.bwrap_prefix(job, [blender_dir], {"HOME": str(job / "home")})
    assert {"--unshare-all", "--clearenv", "--die-with-parent", "--new-session"} <= set(argv)
    writable = [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"]
    assert writable == [str(job)]
    read_only = [argv[i + 1] for i, a in enumerate(argv) if a in ("--ro-bind", "--ro-bind-try")]
    assert str(blender_dir) in read_only and "/home" not in read_only and "/mnt" not in read_only
    assert argv[-1] == "--" and argv[argv.index("--setenv") + 1] == "HOME"


def test_options_validation() -> None:
    with pytest.raises(si.SetupError):
        si.InspectOptions(conditioning=("texture",)).validate()
    with pytest.raises(si.SetupError):
        si.InspectOptions(isolation="docker").validate()
    with pytest.raises(si.SetupError):
        si.InspectOptions(resolution=4).validate()
    assert si.InspectOptions(conditioning=("pose", "depth", "pose")).validate().conditioning == ("depth", "pose")


def test_isolation_bwrap_required_but_missing_is_a_setup_error(env, monkeypatch) -> None:
    monkeypatch.setattr(si, "bwrap_available", lambda: False)
    (env.root / "m.obj").write_text("v 0 0 0\n")
    with pytest.raises(si.SetupError):
        _run(env, "m.obj", isolation="bwrap")
    assert list(env.work.iterdir()) == []


def test_percentiles_and_stats() -> None:
    assert si.percentile([], 50) is None
    assert si.percentile([5, 1, 3, 2, 4], 50) == 3
    assert si.percentile(list(range(1, 101)), 95) == 95
    stats = si.timing_stats([
        {"state": "FULLY_ANALYZED", "asset": {"format": "glb"}, "cache": {"hit": True}, "timings_ms": {"total": 4}},
        {"state": "FAILED", "asset": {"format": "obj"}, "cache": {"hit": False}, "timings_ms": {"total": 10}},
    ])
    assert stats["all"]["n"] == 2 and stats["all"]["failed"] == 1 and stats["all"]["cache_hits"] == 1
    assert stats["glb"]["total"] == {"p50": 4, "p95": 4, "max": 4}


def test_cli_exit_codes(tmp_path: Path, capsys) -> None:
    root = tmp_path / "a"
    root.mkdir()
    (root / "ok.obj").write_text("v 0 0 0\n")
    common = ["inspect", "--root", str(root), "--out", str(tmp_path / "o"), "--cache", str(tmp_path / "c"),
              "--minimum-only"]
    assert scene_inspector_cli.main(common + ["--all"]) == 0
    (root / "bad.gltf").write_text(_gltf("../x.bin"))
    assert scene_inspector_cli.main(common + ["--all"]) == 1
    assert scene_inspector_cli.main(["inspect", "--root", str(tmp_path / "empty-does-not-exist"), "--out", "o",
                                     "--cache", "c", "--all", "--minimum-only"]) == 2
    assert scene_inspector_cli.main(["inspect", "--root", str(root), "--out", str(tmp_path / "o"), "--cache",
                                     str(tmp_path / "c"), "--asset", "ok.obj"]) == 2
    out = capsys.readouterr().out
    assert "MINIMUM_READY" in out and "unsafe_reference" in out
    assert "speed metadata      PASS" in out and "speed analysis      NOT MEASURED" in out


def _check_contract(result: dict, schema: dict) -> None:
    for key in schema["required"]:
        assert key in result, key
    props = schema["properties"]
    assert result["schema"] == props["schema"]["const"]
    assert result["state"] in props["state"]["enum"]
    assert set(result["states_reached"]) <= set(props["states_reached"]["items"]["enum"])
    assert result["likeness_authority"] is False and result["production_activation"] is False
    if result["error"] is not None:
        assert result["error"]["code"] in props["error"]["properties"]["code"]["enum"]
    assert all(isinstance(v, int) and v >= 0 for v in result["timings_ms"].values())
    json.dumps(result, allow_nan=False)


def test_results_match_the_published_contract(env) -> None:
    schema = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "bodyrig-scene-inspection-v1.schema.json")
                        .read_text(encoding="utf-8"))
    (env.root / "ok.obj").write_text("v 0 0 0\n")
    (env.root / "bad.gltf").write_text(_gltf("../x.bin"))
    (env.root / "crash.obj").write_text("# CRASH\n")
    for rel in ("ok.obj", "bad.gltf", "crash.obj"):
        result = _run(env, rel, conditioning=("pose",))
        _check_contract(result, schema)
        _check_contract(json.loads((env.out / rel / "scene.json").read_text(encoding="utf-8")), schema)
    _check_contract(_run(env, "ok.obj", conditioning=("pose",)), schema)  # cache hit


@pytest.mark.parametrize("name, ok", [
    ("depth.png", True), ("openpose.json", True), ("f000000_depth.png", True), ("f000599_openpose.png", True),
    ("f1_depth.png", False), ("f0000001_depth.png", False), ("../depth.png", False), ("frames/depth.png", False),
    ("f000000_scene.json", False), ("depth.png.exe", False), ("F000000_depth.png", False), (None, False),
    ("depth.png\n", False), ("f000000_openpose.json\n", False), ("\ndepth.png", False), ("depth.png\r", False),
])
def test_output_name_allowlist(name, ok: bool) -> None:
    assert si.is_output_name(name) is ok


def test_frames_option_parsing_and_limits() -> None:
    assert si.parse_frames("") is None
    assert si.parse_frames("1:24") == (1, 24, 1) and si.parse_frames("1:24:4") == (1, 24, 4)
    for bad in ("1", "a:b", "1:2:3:4"):
        with pytest.raises(si.SetupError):
            si.parse_frames(bad)
    assert si.InspectOptions(conditioning=("depth",), frames=(1, 24, 4)).validate().frame_list() == [1, 5, 9, 13, 17, 21]
    for frames in ((5, 1, 1), (1, 5, 0), (1, 10000, 1)):
        with pytest.raises(si.SetupError):
            si.InspectOptions(conditioning=("depth",), frames=frames).validate()
    with pytest.raises(si.SetupError):
        si.InspectOptions(frames=(1, 2, 1)).validate()  # a sequence without outputs makes no sense


def test_frame_sequence_files_are_collected_cached_and_keyed(env) -> None:
    (env.root / "m.obj").write_text("v 0 0 0\n")
    first = _run(env, "m.obj", conditioning=("depth", "openpose"), frames=(1, 9, 4))
    assert first["state"] == "FULLY_ANALYZED", first["error"]
    expected = sorted(f"f{i:06d}_{n}" for i in range(3) for n in ("depth.png", "openpose.json", "openpose.png"))
    assert sorted(first["conditioning"]["files"]) == expected
    assert sorted(p.name for p in (env.out / "m.obj").iterdir() if p.name != "scene.json") == expected
    again = _run(env, "m.obj", conditioning=("depth", "openpose"), frames=(1, 9, 4))
    assert again["cache"]["hit"] is True and again["conditioning"]["files"] == first["conditioning"]["files"]
    other = _run(env, "m.obj", conditioning=("depth", "openpose"), frames=(1, 9, 2))
    assert other["cache"]["key"] != first["cache"]["key"] and len(env.calls()) == 2


def test_missing_frame_outputs_are_reported(env) -> None:
    (env.root / "m.obj").write_text("# DROPFRAME\nv 0 0 0\n")
    result = _run(env, "m.obj", conditioning=("depth",), frames=(1, 3, 1))
    assert result["state"] == "FULLY_ANALYZED"
    assert any("conditioning output missing (1): f000002_depth.png" in w for w in result["warnings"])


def _worker_module():
    import importlib.util
    import types

    sys.modules.setdefault("bpy", types.ModuleType("bpy"))
    spec = importlib.util.spec_from_file_location("blender_scene_worker_under_test", si.WORKER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name, expected", [
    ("mixamorig:LeftArm", ("upperarm", "L")), ("mixamorig:LeftForeArm", ("forearm", "L")),
    ("mixamorig:RightHand", ("hand", "R")), ("mixamorig:LeftShoulder", ("clavicle", "L")),
    ("mixamorig:LeftUpLeg", ("thigh", "L")), ("mixamorig:LeftLeg", ("shin", "L")), ("mixamorig:RightFoot", ("foot", "R")),
    ("mixamorig:Neck", ("neck", None)), ("mixamorig:Head", ("head", None)), ("mixamorig:HeadTop_End", (None, None)),
    ("mixamorig:LeftHandIndex1", (None, None)), ("mixamorig:LeftToeBase", (None, None)),
    ("upperarm_l", ("upperarm", "L")), ("lowerarm_r", ("forearm", "R")), ("hand_l", ("hand", "L")),
    ("clavicle_r", ("clavicle", "R")), ("thigh_l", ("thigh", "L")), ("calf_r", ("shin", "R")), ("foot_l", ("foot", "L")),
    ("neck_01", ("neck", None)), ("upperarm_twist_01_l", (None, None)),
    ("DEF-upper_arm.L", ("upperarm", "L")), ("DEF-forearm.R", ("forearm", "R")), ("DEF-hand.L", ("hand", "L")),
    ("DEF-thigh.R", ("thigh", "R")), ("DEF-shin.L", ("shin", "L")), ("DEF-foot.R", ("foot", "R")),
    ("DEF-shoulder.L", ("clavicle", "L")), ("ORG-eye.L", ("eye", "L")),
    ("J_Bip_L_UpperArm", ("upperarm", "L")), ("J_Bip_R_LowerArm", ("forearm", "R")), ("J_Bip_L_Hand", ("hand", "L")),
    ("J_Bip_L_UpperLeg", ("thigh", "L")), ("J_Bip_R_LowerLeg", ("shin", "R")), ("J_Bip_C_Neck", ("neck", None)),
    ("arm left shoulder 2", ("upperarm", "L")), ("arm left elbow", ("forearm", "L")), ("arm right wrist", ("hand", "R")),
    ("leg left thigh", ("thigh", "L")), ("leg right knee", ("shin", "R")), ("leg left ankle", ("foot", "L")),
    ("Bip01 L UpperArm", ("upperarm", "L")), ("Bip01 R Forearm", ("forearm", "R")),
    ("spine", (None, None)), ("hips", (None, None)), ("root", (None, None)), ("arm", (None, None)),
    # generic numbered chains (Khronos CesiumMan / RiggedFigure, Fox)
    ("arm_joint_L_1", ("armchain", "L")), ("Skeleton_arm_joint_R__3_", ("armchain", "R")),
    ("Skeleton_arm_joint_R", ("armchain", "R")), ("leg_joint_L_5", ("legchain", "L")),
    ("b_LeftLeg01_015", ("legchain", "L")), ("b_RightLeg02_020", ("legchain", "R")),
    ("Skeleton_neck_joint_2", ("neck", None)), ("b_Head_05", ("head", None)), ("b_RightHand_08", ("hand", "R")),
    ("b_LeftUpperArm_09", ("upperarm", "L")), ("b_LeftFoot01_017", ("foot", "L")), ("torso_joint_1", (None, None)),
    ("Node_12", (None, None)), ("b_Tail01_012", (None, None)),
])
def test_bone_names_map_to_openpose_roles(name: str, expected) -> None:
    assert _worker_module().classify_bone(name) == expected


def test_a_failed_blender_start_is_retried_once(env) -> None:
    (env.root / "m.obj").write_text("# FLAKYSTART\nv 0 0 0\n")
    result = _run(env, "m.obj")
    assert result["state"] == "FULLY_ANALYZED", result["error"]
    assert result["process"]["attempts"] == 2 and len(env.calls()) == 2
    assert any("retried once" in w for w in result["warnings"])


def test_a_persistent_start_failure_still_fails(env) -> None:
    (env.root / "m.obj").write_text("# BADSTART\nv 0 0 0\n")
    result = _run(env, "m.obj")
    assert result["state"] == "FAILED" and result["error"]["code"] == "worker_failed"
    assert result["process"]["attempts"] == 2


def test_an_asset_failure_is_not_retried(env) -> None:
    (env.root / "m.obj").write_text("# CRASH\n")
    assert _run(env, "m.obj")["process"]["attempts"] == 1


def test_cancelled_batch_stops_running_workers_and_cleans_up(env) -> None:
    import threading

    (env.root / "slow.obj").write_text("# HANG\nv 0 0 0\n")
    cancel = threading.Event()
    threading.Timer(2.0, cancel.set).start()
    started = time.perf_counter()
    result = si.inspect_asset(env.root, "slow.obj", env.out / "s", runtime=env.runtime, cache=env.cache,
                              options=_opts(wall_seconds=60), work_root=env.work, cancel=cancel)
    assert time.perf_counter() - started < 15
    assert result["state"] == "FAILED" and result["error"]["code"] == "cancelled"
    assert result["cleanup"] == {"staging_removed": True} and list(env.work.iterdir()) == []
    later = si.inspect_asset(env.root, "slow.obj", env.out / "t", runtime=env.runtime, cache=env.cache,
                             options=_opts(), work_root=env.work, cancel=cancel)
    assert later["error"]["code"] == "cancelled" and len(env.calls()) == 1


def test_worker_progress_is_relayed_into_scene_json_while_running(env, monkeypatch) -> None:
    (env.root / "m.obj").write_text("# PROGRESS\nv 0 0 0\n")
    seen = []
    real_write = si._atomic_write_json

    def spy(path, value):
        if path.name == "scene.json" and value.get("progress"):
            seen.append(dict(value["progress"]))
        real_write(path, value)

    monkeypatch.setattr(si, "_atomic_write_json", spy)
    result = _run(env, "m.obj", conditioning=("depth",), frames=(1, 3, 1))
    assert result["state"] == "FULLY_ANALYZED" and "progress" not in result
    assert seen and seen[0]["stage"] == "conditioning" and seen[0]["frames_total"] == 3
    assert [p["frames_done"] for p in seen] == sorted(p["frames_done"] for p in seen)


def test_a_broken_progress_relay_never_breaks_the_run(tmp_path: Path) -> None:
    from bodyrig.process_limits import Limits, run_bounded

    def explode():
        raise RuntimeError("relay bug")

    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")}
    result = run_bounded([sys.executable, "-c", "import time; time.sleep(0.5)"], cwd=tmp_path, env=env,
                         limits=Limits(wall_seconds=30), stdout_path=tmp_path / "o", stderr_path=tmp_path / "e",
                         on_poll=explode)
    assert result.returncode == 0 and not result.timed_out


@pytest.mark.parametrize("name, expected", [
    ("mixamorig:LeftHandIndex1", ("index", 1, "L")), ("mixamorig1:LeftHandIndex2", ("index", 2, "L")),
    ("mixamorig:RightHandThumb3", ("thumb", 3, "R")), ("mixamorig:LeftHandPinky4", ("pinky", 4, "L")),
    ("index_02_l", ("index", 2, "L")), ("thumb_01_r", ("thumb", 1, "R")), ("ring_03_l", ("ring", 3, "L")),
    ("DEF-f_middle.02.L", ("middle", 2, "L")), ("DEF-thumb.01.R", ("thumb", 1, "R")),
    ("J_Bip_L_Little2", ("pinky", 2, "L")), ("J_Bip_R_Index1", ("index", 1, "R")),
    ("index_metacarpal_l", (None, None, None)), ("mixamorig:LeftHand", (None, None, None)),
    ("LeftHandIndex", (None, None, None)), ("index_01", (None, None, None)), ("LeftToeBase", (None, None, None)),
    ("mixamorig:LeftHandIndex4_end", (None, None, None)),
])
def test_finger_bones_map_to_openpose_hand_points(name: str, expected) -> None:
    assert _worker_module().classify_finger(name) == expected


def test_hand_edges_follow_the_openpose_hand_layout() -> None:
    edges = _worker_module().HAND_EDGES
    assert len(edges) == 20
    assert edges[:4] == ((0, 1), (1, 2), (2, 3), (3, 4)) and edges[4] == (0, 5) and edges[-1] == (19, 20)


def test_view_yaw_is_passed_validated_and_keyed(env) -> None:
    (env.root / "m.obj").write_text("v 0 0 0\n")
    front = _run(env, "m.obj", conditioning=("depth",))
    side = _run(env, "m.obj", conditioning=("depth",), yaw_deg=90.0)
    assert side["cache"]["key"] != front["cache"]["key"] and len(env.calls()) == 2
    with pytest.raises(si.SetupError):
        si.InspectOptions(yaw_deg=400.0).validate()


def test_time_budget_stops_the_run_keeps_what_finished_and_a_rerun_continues(env) -> None:
    (env.root / "a.obj").write_text("v 0 0 0\n")
    (env.root / "slow.obj").write_text("# HANG\nv 0 0 0\n")
    (env.root / "b.obj").write_text("v 1 0 0\n")
    started = time.perf_counter()
    summary = si.inspect_batch(env.root, ["a.obj", "slow.obj", "b.obj"], env.out, runtime=env.runtime,
                               cache=env.cache, options=_opts(wall_seconds=120, conditioning=("depth",)), jobs=1,
                               work_root=env.work, budget_seconds=4.0)
    assert time.perf_counter() - started < 20  # the 120 s per-asset limit never applied
    by = {a["path"]: a for a in summary["assets"]}
    assert by["a.obj"]["state"] == "FULLY_ANALYZED"
    assert by["slow.obj"]["error"]["code"] == "budget_exhausted" and "time budget" in by["slow.obj"]["error"]["message"]
    assert by["b.obj"]["error"]["code"] == "budget_exhausted" and "not started" in by["b.obj"]["error"]["message"]
    assert env.calls() == ["a.obj", "slow.obj"]  # b.obj never started a worker
    slow = json.loads((env.out / "slow.obj" / "scene.json").read_text())
    assert "MINIMUM_READY" in slow["states_reached"] and slow["minimum"]["vertices"] == 1  # metadata kept
    assert slow["cleanup"] == {"staging_removed": True} and list(env.work.iterdir()) == []
    assert (env.out / "a.obj" / "depth.png").is_file()
    assert summary["budget"] == {"seconds": 4.0, "not_reached": 2}
    assert summary["slo"]["first_usable"]["verdict"] == "PASS"
    assert summary["slo"]["analysis"]["value_ms"] >= 3000  # the stopped asset counts with its elapsed time

    again = si.inspect_batch(env.root, ["a.obj", "b.obj"], env.out / "again", runtime=env.runtime, cache=env.cache,
                             options=_opts(wall_seconds=120, conditioning=("depth",)), jobs=1, work_root=env.work,
                             budget_seconds=30.0)
    assert [a["cache_hit"] for a in again["assets"]] == [True, False]
    assert again["states"] == {"FULLY_ANALYZED": 2} and again["budget"]["not_reached"] == 0
    assert env.calls() == ["a.obj", "slow.obj", "b.obj"]  # finished work was not redone


def test_an_asset_timeout_inside_the_budget_is_still_a_timeout(env) -> None:
    (env.root / "slow.obj").write_text("# HANG\nv 0 0 0\n")
    summary = si.inspect_batch(env.root, ["slow.obj"], env.out, runtime=env.runtime, cache=env.cache,
                               options=_opts(wall_seconds=2.0), work_root=env.work, budget_seconds=60.0)
    assert summary["assets"][0]["error"]["code"] == "timeout" and summary["budget"]["not_reached"] == 0
    assert summary["slo"]["first_usable"]["verdict"] == "FAIL"  # nothing became usable


def test_budget_must_be_positive(env) -> None:
    with pytest.raises(si.SetupError):
        si.inspect_batch(env.root, ["a.obj"], env.out, runtime=None, cache=env.cache, options=_opts(),
                         budget_seconds=0)


def test_batch_reports_first_result_and_speed_verdicts(env) -> None:
    for index, name in enumerate(("a.obj", "b.obj")):
        (env.root / name).write_text(f"v {index} 0 0\n")  # different content: no cache hit inside the run
    first = si.inspect_batch(env.root, ["a.obj", "b.obj"], env.out, runtime=env.runtime, cache=env.cache,
                             options=_opts(conditioning=("depth",)), work_root=env.work)
    ready = first["first_result_ms"]
    assert ready["minimum_ready_at"] <= ready["conditioning_ready_at"] <= first["wall_ms"]
    slo = first["slo"]
    assert {slo[k]["verdict"] for k in ("metadata", "analysis", "first_usable")} == {"PASS"}
    assert slo["cached"]["verdict"] == "NOT_MEASURED" and slo["analysis"]["target_ms"] == 90_000
    assert "physical rig" in slo["note"]
    second = si.inspect_batch(env.root, ["a.obj", "b.obj"], env.out, runtime=env.runtime, cache=env.cache,
                              options=_opts(conditioning=("depth",)), work_root=env.work)
    assert second["slo"]["cached"]["verdict"] == "PASS" and second["slo"]["cached"]["n"] == 2
    assert second["slo"]["metadata"]["verdict"] == "NOT_MEASURED"  # nothing uncached this time


def test_slo_report_counts_slow_failures_and_flags_misses() -> None:
    def item(**timings):
        return {"cache": {"hit": False}, "states_reached": ["DISCOVERED", "SAFE_TO_INSPECT", "MINIMUM_READY"],
                "error": None, "timings_ms": timings}
    fast = item(minimum_ready_at=3, fully_analyzed_at=900, total=900)
    stuck = item(minimum_ready_at=4, total=45_000)
    stuck["error"] = {"code": "timeout", "message": ""}
    stuck["process"] = {"timed_out": True}
    unstarted = item(minimum_ready_at=2, total=6)  # budget ran out before Blender: not an analysis sample
    unstarted["error"] = {"code": "budget_exhausted", "message": ""}
    broken = item(total=5)
    broken["error"] = {"code": "invalid_asset", "message": ""}
    broken["states_reached"] = ["DISCOVERED"]
    report = si.slo_report([fast, stuck, broken, unstarted], conditioning=(), first_usable_ms=900)
    assert report["metadata"] == {"verdict": "PASS", "target_ms": 5000, "value_ms": 4, "n": 3,
                                  "what": report["metadata"]["what"]}
    assert report["analysis"]["verdict"] == "FAIL" and report["analysis"]["value_ms"] == 45_000
    assert report["analysis"]["n"] == 2  # neither the invalid nor the unstarted asset is an analysis sample
    assert report["first_usable"]["verdict"] == "PASS" and report["cached"]["verdict"] == "NOT_MEASURED"
    late = si.slo_report([fast], conditioning=("pose",), first_usable_ms=130_000)
    assert late["first_usable"]["verdict"] == "FAIL" and late["analysis"]["target_ms"] == 90_000
    never = si.slo_report([stuck], conditioning=(), first_usable_ms=None, nothing_usable_after_ms=45_100)
    assert never["first_usable"]["verdict"] == "FAIL" and never["first_usable"]["value_ms"] == 45_100


@pytest.mark.parametrize("text, seconds", [("90", 90.0), ("90s", 90.0), ("15m", 900.0), ("1.5h", 5400.0),
                                           ("0", None), ("none", None)])
def test_budget_durations(text: str, seconds) -> None:
    assert scene_inspector_cli.parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "m", "abc", "-5m", "nan", "10d"])
def test_bad_budget_durations(text: str) -> None:
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        scene_inspector_cli.parse_duration(text)


def test_a_stopped_frame_sequence_keeps_the_finished_frames_only(env) -> None:
    (env.root / "walk.obj").write_text("# STALLFRAMES 4\nv 0 0 0\n")
    options = _opts(wall_seconds=3.0, conditioning=("depth", "pose"), frames=(1, 4, 1))
    result = si.inspect_asset(env.root, "walk.obj", env.out / "w", runtime=env.runtime, cache=env.cache,
                              options=options, work_root=env.work)
    assert result["state"] == "FAILED" and result["error"]["code"] == "timeout"
    assert "2 of 4 frames were finished and are kept" in result["error"]["message"]
    partial = result["partial"]
    assert partial["frames_done"] == 2 and partial["frames_total"] == 4 and partial["frames"] == [1, 2]
    assert partial["camera"] == {"type": "orthographic", "view": "front"}
    kept = sorted(p.name for p in (env.out / "w").iterdir() if p.name != "scene.json")
    assert kept == ["f000000_depth.png", "f000000_pose.json", "f000000_pose.png",
                    "f000001_depth.png", "f000001_pose.json", "f000001_pose.png"]  # never the half-written frame 2
    assert sorted(partial["files"]) == kept
    written = json.loads((env.out / "w" / "scene.json").read_text())
    assert written["partial"]["frames_done"] == 2 and written["state"] == "FAILED"
    assert list(env.work.iterdir()) == []
    si.inspect_asset(env.root, "walk.obj", env.out / "w2", runtime=env.runtime, cache=env.cache,
                     options=options, work_root=env.work)
    assert len(env.calls()) == 2  # a partial result is never cached


def test_a_budget_stop_keeps_finished_frames_too(env) -> None:
    (env.root / "walk.obj").write_text("# STALLFRAMES 4\nv 0 0 0\n")
    summary = si.inspect_batch(env.root, ["walk.obj"], env.out, runtime=env.runtime, cache=env.cache,
                               options=_opts(wall_seconds=120, conditioning=("depth",), frames=(1, 4, 1)),
                               work_root=env.work, budget_seconds=3.0)
    asset = json.loads((env.out / "walk.obj" / "scene.json").read_text())
    assert summary["assets"][0]["error"]["code"] == "budget_exhausted"
    assert asset["partial"]["frames_done"] == 2 and sorted(asset["partial"]["files"]) == [
        "f000000_depth.png", "f000001_depth.png"]


@pytest.mark.parametrize("marker", ["BADPROGRESS", "GAP"])
def test_untrustworthy_or_gappy_progress_keeps_no_frames_past_the_gap(env, marker: str) -> None:
    (env.root / "walk.obj").write_text(f"# STALLFRAMES 4 {marker}\nv 0 0 0\n")
    result = si.inspect_asset(env.root, "walk.obj", env.out / "w", runtime=env.runtime, cache=env.cache,
                              options=_opts(wall_seconds=3.0, conditioning=("depth",), frames=(1, 4, 1)),
                              work_root=env.work)
    assert result["error"]["code"] == "timeout" and "partial" not in result
    assert [p.name for p in (env.out / "w").iterdir()] == ["scene.json"]


def test_partial_frames_match_the_published_contract(env) -> None:
    schema = json.loads((Path(__file__).resolve().parents[1] / "contracts" /
                         "bodyrig-scene-inspection-v1.schema.json").read_text(encoding="utf-8"))
    (env.root / "walk.obj").write_text("# STALLFRAMES 4\nv 0 0 0\n")
    result = si.inspect_asset(env.root, "walk.obj", env.out / "w", runtime=env.runtime, cache=env.cache,
                              options=_opts(wall_seconds=3.0, conditioning=("depth",), frames=(1, 4, 1)),
                              work_root=env.work)
    _check_contract(result, schema)
    spec = schema["properties"]["partial"]
    assert set(spec["required"]) <= set(result["partial"])
    assert result["partial"]["frames_done"] >= spec["properties"]["frames_done"]["minimum"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", sha) for sha in result["partial"]["files"].values())
    assert all(si.is_output_name(name) for name in result["partial"]["files"])
