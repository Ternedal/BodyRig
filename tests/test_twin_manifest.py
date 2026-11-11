"""The POSE_READY reader (#1397 item 3): one verified way back into an export_pose output.

Every check in bodyrig.twin_manifest gets one corrupted copy of a real export below. The
corrupted copy must be refused, with a message naming that check, and the untouched export
must pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from bodyrig import twin_manifest as tm
from bodyrig import twin_pose as tp
from bodyrig.twin_pose_cli import main as cli_main
from test_twin_pose import _consent, _export, _workspace

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts" / "bodyrig-digital-twin-manifest-v1.schema.json"


def _out(tmp_path: Path, *, stages: tuple[str, ...] | None = None) -> Path:
    root = _workspace(tmp_path) if stages is None else _workspace(tmp_path, stages=stages)
    _export(tmp_path, root, _consent(tmp_path, root))
    return tmp_path / "out"


def _copy(src: Path, tmp_path: Path, name: str) -> Path:
    dst = tmp_path / name
    shutil.copytree(src, dst)
    return dst


def _manifest(out: Path) -> dict:
    return json.loads((out / tm.MANIFEST_NAME).read_text(encoding="utf-8"))


def _rewrite(out: Path, change, *, redigest: bool = True) -> None:
    """Change the manifest. With redigest, recompute manifest_sha256, so only the targeted check can refuse it."""
    manifest = _manifest(out)
    change(manifest)
    if redigest:
        manifest["manifest_sha256"] = tp._canonical_digest(manifest, omit="manifest_sha256")
    (out / tm.MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rewrite_artifact(out: Path, name: str, data: bytes) -> None:
    """Replace an artifact and re-record its size and hash, so only the cross-checks can refuse it."""
    (out / name).write_bytes(data)

    def change(m: dict) -> None:
        for entry in m["artifacts"]:
            if entry["name"] == name:
                entry["size_bytes"] = len(data)
                entry["sha256"] = hashlib.sha256(data).hexdigest()

    _rewrite(out, change)


def _refused(out: Path, match: str) -> None:
    with pytest.raises(tm.TwinManifestError, match=match):
        tm.verify_twin_output(out)


# --- what passes ---------------------------------------------------------------------------


def test_a_real_export_verifies_and_reads_back_typed(tmp_path: Path) -> None:
    out = _out(tmp_path)
    result = tm.verify_twin_output(out)
    manifest = _manifest(out)
    assert result.manifest_sha256 == manifest["manifest_sha256"]
    assert (result.source, result.preprocess_stage) == ("smoothed", "smplx-smooth")
    assert result.samples == manifest["timing"]["samples"] and result.valid_samples == manifest["timing"]["valid_samples"]
    assert result.subject_relation == manifest["consent"]["subject_relation"]
    assert result.motion_bvh == out.resolve() / "motion.bvh" and result.motion_json == out.resolve() / "motion.json"
    assert set(result.artifacts) == {"motion.bvh", "motion.json"}
    assert result.raw["likeness_authority"] is False
    with pytest.raises(TypeError):
        result.raw["likeness_authority"] = True  # type: ignore[index]


def test_the_verified_manifest_cannot_be_changed_afterwards_at_any_depth(tmp_path: Path) -> None:
    # ChatGPT #1415 6806677589 P2: a shallow proxy left nested objects and lists writable.
    result = tm.verify_twin_output(_out(tmp_path))
    raw = result.raw
    with pytest.raises(TypeError):
        raw["artifacts"][0]["sha256"] = "0" * 64  # type: ignore[index]
    with pytest.raises(TypeError):
        raw["skeleton"]["joint_count"] = 55  # type: ignore[index]
    with pytest.raises(TypeError):
        raw["keypoint_gate"]["applied"] = True  # type: ignore[index]
    with pytest.raises(AttributeError):
        raw["invalid_samples"].append("injected")  # type: ignore[union-attr]
    with pytest.raises(TypeError):
        raw["artifacts"][0] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        result.artifacts["motion.bvh"]["sha256"] = "0" * 64  # type: ignore[index]
    # The values are still plain data a consumer can read and serialise.
    assert raw["artifacts"][0]["name"] in tm.ARTIFACT_NAMES
    assert json.loads(json.dumps(raw["coordinate_system"], default=dict)) == tp.COORDINATE_SYSTEM


def test_an_init_export_verifies_without_the_keypoint_gate(tmp_path: Path) -> None:
    out = _out(tmp_path, stages=("camera", "hand4whole-smplx-init"))
    result = tm.verify_twin_output(out)
    assert result.source == "init" and result.keypoint_gate_applied is False
    # The gate needs the smoothed source's translation: an init export cannot claim it ran.
    _rewrite(out, lambda m: m["keypoint_gate"].update(applied=True, reason_not_applied=None))
    _refused(out, "cannot check")


# --- the manifest itself -------------------------------------------------------------------


@pytest.mark.parametrize(("label", "change", "match"), [
    ("format", lambda m: m.update(format="bodyrig-other"), "format"),
    ("version", lambda m: m.update(version=2), "version"),
    ("version-bool", lambda m: m.update(version=True), "version"),
    ("unknown-key", lambda m: m.update(extra=1), "unexpected"),
    ("missing-key", lambda m: m.pop("eye"), "missing"),
    ("state", lambda m: m.update(state="MESH_READY"), "POSE_READY"),
    ("mesh", lambda m: m.update(mesh="available"), "mesh"),
    ("coordinates", lambda m: m["coordinate_system"].update(up="+Z"), "coordinate"),
    ("source", lambda m: m["motion_source"].update(source="raw"), "init or smoothed"),
    ("stage", lambda m: m["motion_source"].update(preprocess_stage="hand4whole-smplx-init"), "belong together"),
    ("skeleton-name", lambda m: m["skeleton"].update(name="mixamo"), "skeleton"),
    ("joint-count", lambda m: m["skeleton"].update(joint_count=55), "skeleton"),
    ("template-sha", lambda m: m["skeleton"].update(template_model_sha256="ABC"), "template_model_sha256"),
    ("consent-sha", lambda m: m["consent"].update(consent_sha256="0" * 63), "consent_sha256"),
    ("relation", lambda m: m["consent"].update(subject_relation="stranger"), "subject relation"),
    ("workspace-sha", lambda m: m.update(workspace_sha256=None), "workspace_sha256"),
    ("samples", lambda m: m["timing"].update(valid_samples=m["timing"]["samples"] + 1), "sample counts"),
    ("timestamps", lambda m: m["timing"].update(first_timestamp_seconds=float(m["timing"]["last_timestamp_seconds"]) + 1), "timestamps"),
    ("frame-time", lambda m: m["timing"].update(bvh_frame_time_seconds=0.04), "frame time"),
    ("eye", lambda m: m.update(eye="both"), "eye"),
    ("invalid-unsorted", lambda m: m.update(invalid_samples=["b_reason", "a_reason"]), "sorted list"),
    ("invalid-vs-counts", lambda m: m.update(invalid_samples=["not_finite"]), "agree"),
    ("multi-person", lambda m: m.update(multi_person_detection=None), "statement"),
    ("gate-counts", lambda m: m["keypoint_gate"].update(rejected=m["keypoint_gate"]["checked"] + 1), "counts"),
    ("gate-threshold", lambda m: m["keypoint_gate"].update(max_error=5), "thresholds"),
    ("gate-key", lambda m: m["keypoint_gate"].update(extra=True), "keypoint_gate keys"),
    ("timings-payload", lambda m: m["preprocess_stage_timings"].append(
        {"stage": "camera", "state": "done", "elapsed_seconds": 1.0, "prompt": "x"}), "stage, state"),
    ("artifact-extra", lambda m: m["artifacts"].append(dict(m["artifacts"][0])), "exactly"),
    ("artifact-name", lambda m: m["artifacts"][0].update(name="../motion.bvh"), "exactly"),
    ("artifact-twice", lambda m: m["artifacts"][1].update(name=m["artifacts"][0]["name"]), "exactly"),
    ("gate-applied-with-reason", lambda m: m["keypoint_gate"].update(applied=True, reason_not_applied="no keypoints"),
     "cannot check"),
    ("artifact-size", lambda m: m["artifacts"][0].update(size_bytes=0), "size"),
])
def test_each_manifest_check_refuses_its_corruption(tmp_path: Path, label: str, change, match: str) -> None:
    out = _copy(_out(tmp_path), tmp_path, label)
    _rewrite(out, change)
    _refused(out, match)


@pytest.mark.parametrize("flag", tm.SAFETY_FLAGS)
@pytest.mark.parametrize("value", [True, None, 0, "false"])
def test_every_safety_flag_must_be_exactly_false(tmp_path: Path, flag: str, value) -> None:
    out = _copy(_out(tmp_path), tmp_path, f"{flag}-{value!r}")
    _rewrite(out, lambda m: m.update({flag: value}))
    _refused(out, flag)


def test_a_changed_manifest_without_a_new_digest_is_refused(tmp_path: Path) -> None:
    out = _copy(_out(tmp_path), tmp_path, "digest")
    _rewrite(out, lambda m: m.update(multi_person_detection="changed after export"), redigest=False)
    _refused(out, "manifest_sha256 does not match")


@pytest.mark.parametrize(("label", "text", "match"), [
    ("nan", '{"version": NaN}', "strict JSON"),
    ("infinity", '{"version": Infinity}', "strict JSON"),
    ("duplicate", '{"likeness_authority": false, "likeness_authority": true}', "strict JSON"),
    ("array", "[]", "JSON object"),
    ("utf16", '{"a": 1}'.encode("utf-16").decode("latin-1"), "strict JSON"),
])
def test_the_manifest_must_be_strict_json(tmp_path: Path, label: str, text: str, match: str) -> None:
    out = _copy(_out(tmp_path), tmp_path, label)
    (out / tm.MANIFEST_NAME).write_bytes(text.encode("latin-1"))
    _refused(out, match)


def test_an_oversized_manifest_is_refused_before_parsing(tmp_path: Path) -> None:
    out = _copy(_out(tmp_path), tmp_path, "big")
    (out / tm.MANIFEST_NAME).write_bytes(b" " * (tm.MAX_MANIFEST_BYTES + 1))
    _refused(out, "larger than")


# --- the artifacts -------------------------------------------------------------------------


def test_a_tampered_artifact_byte_is_refused(tmp_path: Path) -> None:
    out = _copy(_out(tmp_path), tmp_path, "byte")
    data = bytearray((out / "motion.bvh").read_bytes())
    data[-3] = ord("7") if data[-3] != ord("7") else ord("8")
    (out / "motion.bvh").write_bytes(bytes(data))
    _refused(out, "motion.bvh SHA-256 differs")


def test_a_truncated_artifact_is_refused(tmp_path: Path) -> None:
    out = _copy(_out(tmp_path), tmp_path, "short")
    data = (out / "motion.json").read_bytes()
    (out / "motion.json").write_bytes(data[:-1])
    _refused(out, "motion.json size differs")


def test_a_missing_artifact_is_refused(tmp_path: Path) -> None:
    out = _copy(_out(tmp_path), tmp_path, "missing")
    (out / "motion.json").unlink()
    _refused(out, "motion.json")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
def test_a_symlinked_artifact_or_directory_is_refused(tmp_path: Path) -> None:
    out = _copy(_out(tmp_path), tmp_path, "linked")
    real = tmp_path / "elsewhere.bvh"
    os.replace(out / "motion.bvh", real)
    (out / "motion.bvh").symlink_to(real)
    _refused(out, "motion.bvh path goes through a symlink")
    second = tmp_path / "second"
    second.mkdir()
    linked_dir = tmp_path / "dir-link"
    linked_dir.symlink_to(_out(second), target_is_directory=True)
    _refused(linked_dir, "twin output directory")


def test_motion_json_must_agree_with_the_manifest(tmp_path: Path) -> None:
    base = _out(tmp_path)
    for label, change, match in [
        ("motion-source", lambda j: j.update(source="init"), "source differs"),
        ("motion-skeleton", lambda j: j["skeleton"]["joints"].reverse(), "skeleton differs"),
        ("motion-frames", lambda j: j["frames"].pop(), "frame count"),
        ("motion-valid", lambda j: j["frames"][0].update(valid=False), "valid samples"),
    ]:
        out = _copy(base, tmp_path, label)
        motion = json.loads((out / "motion.json").read_text(encoding="utf-8"))
        change(motion)
        _rewrite_artifact(out, "motion.json", (json.dumps(motion, indent=2) + "\n").encode("utf-8"))
        _refused(out, match)


def test_motion_bvh_must_agree_with_the_manifest(tmp_path: Path) -> None:
    base = _out(tmp_path)
    text = (base / "motion.bvh").read_text(encoding="utf-8")
    first_joint = tp.JOINTS[tp.hierarchy_order()[1]]
    cases = [
        ("bvh-order", text.replace(f"JOINT {first_joint}\n", "JOINT renamed\n", 1), "joint order"),
        ("bvh-frames", text.replace(f"Frames: {_manifest(base)['timing']['valid_samples']}", "Frames: 1", 1), "frame count"),
        ("bvh-channels", text.rstrip("\n").rsplit(" ", 1)[0] + "\n", "number of channels"),
        ("bvh-nan", text.rstrip("\n").rsplit(" ", 1)[0] + " nan\n", "non-finite"),
        ("bvh-sections", text.replace("MOTION\n", "MOTIONS\n", 1), "HIERARCHY/MOTION"),
        # ChatGPT #1415 P3: the header a player uses must carry the manifest's frame time.
        ("bvh-frame-time", text.replace("Frame Time: 0.033333\n", "Frame Time: 0.041667\n", 1), "frame time differs"),
        ("bvh-frame-time-text", text.replace("Frame Time: 0.033333\n", "Frame Time: fast\n", 1), "MOTION header"),
        ("bvh-frames-signed", text.replace(f"Frames: {_manifest(base)['timing']['valid_samples']}\n",
                                           f"Frames: +{_manifest(base)['timing']['valid_samples']}\n", 1), "MOTION header"),
    ]
    for label, new, match in cases:
        assert new != text, label
        out = _copy(base, tmp_path, label)
        _rewrite_artifact(out, "motion.bvh", new.encode("utf-8"))
        _refused(out, match)


# --- the schema and the CLI ----------------------------------------------------------------


def test_the_schema_documents_exactly_what_the_reader_enforces(tmp_path: Path) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    manifest = _manifest(_out(tmp_path))
    assert schema["$id"].endswith("bodyrig-digital-twin-manifest-v1.schema.json")
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"]) == tm.TOP_LEVEL_KEYS == set(manifest)
    props = schema["properties"]
    assert props["format"]["const"] == tp.MANIFEST_FORMAT and props["version"]["const"] == tp.VERSION
    assert props["state"]["const"] == "POSE_READY" and props["mesh"]["const"] == "unavailable"
    assert props["coordinate_system"]["const"] == tp.COORDINATE_SYSTEM
    for flag in tm.SAFETY_FLAGS:
        assert props[flag] == {"const": False}, flag
    for name, keys in (("skeleton", tm.SKELETON_KEYS), ("timing", tm.TIMING_KEYS), ("keypoint_gate", tm.GATE_KEYS)):
        assert props[name]["additionalProperties"] is False, name
        assert set(props[name]["required"]) == set(props[name]["properties"]) == keys, name
    assert props["skeleton"]["properties"]["name"]["const"] == tp.SKELETON
    assert props["skeleton"]["properties"]["joint_count"]["const"] == len(tp.JOINTS)
    assert props["skeleton"]["properties"]["rest_pose"]["const"] == tm.REST_POSE
    assert sorted(props["motion_source"]["properties"]["source"]["enum"]) == sorted(tp.SOURCES)
    assert sorted(props["consent"]["properties"]["subject_relation"]["enum"]) == sorted(tp.RELATIONS)
    assert props["eye"]["enum"] == list(tm.EYES)
    item = props["artifacts"]["items"]
    assert sorted(item["properties"]["name"]["enum"]) == sorted(tm.ARTIFACT_NAMES)
    assert props["artifacts"]["minItems"] == props["artifacts"]["maxItems"] == len(tm.ARTIFACT_NAMES)


def test_the_cli_verifies_and_names_the_first_failure(tmp_path: Path, capsys) -> None:
    out = _out(tmp_path)
    assert cli_main(["verify", "--out", str(out)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verified"] is True and report["manifest_sha256"] == _manifest(out)["manifest_sha256"]
    bad = _copy(out, tmp_path, "bad")
    (bad / "motion.bvh").write_bytes(b"HIERARCHY\n")
    assert cli_main(["verify", "--out", str(bad)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["verified"] is False and "motion.bvh" in report["reason"]
