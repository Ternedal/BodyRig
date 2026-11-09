"""Host-side scene inspector: states, isolation plumbing, cache, failure isolation.

Blender is replaced by a small fake worker (same argv contract, plain Python), so
these run everywhere. The real Blender path is covered by
tests/test_scene_inspector_blender.py when a pinned runtime is configured.
"""

from __future__ import annotations

import gzip
import json
import os
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
        names = {"pose": ["pose.json", "pose.png"], "depth": ["depth.png"], "normal": ["normal.png"]}
        for kind in kinds:
            for name in names[kind]:
                open(os.path.join(out, name), "wb").write(("fake " + name).encode())
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


def test_obj_material_library_is_staged_best_effort(env) -> None:
    (env.root / "m.mtl").write_text("newmtl a\n")
    (env.root / "m.obj").write_text("mtllib m.mtl\nmtllib ../evil.mtl\nv 0 0 0\n")
    result = _run(env, "m.obj")
    assert result["state"] == "FULLY_ANALYZED"
    assert [d["path"] for d in result["dependencies"]] == ["m.mtl"]
    assert any("evil.mtl" in w for w in result["warnings"])


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
