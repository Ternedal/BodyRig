"""POSE_READY motion export (#1398 slice 1a). Offline fixtures only: a fake skeleton and fake
SMPL-X parameters. None of this is physical ExAvatar proof."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_preprocess as preprocess
from bodyrig import scene_inspector as si
from bodyrig import twin_pose as tp
from bodyrig.twin_pose_cli import main as cli

N = 4
REST = [[0.0, 0.0, 0.0]] + [[0.01 * i, 0.05 * i, -0.01 * i] for i in range(1, 22)]
MODEL_SHA = "9" * 64


def _rx(angle: float) -> list[list[float]]:
    c, s = math.cos(angle), math.sin(angle)
    return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]


def _write(path: Path, value: object) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value).encode("utf-8")
    path.write_bytes(raw)
    return {"path": path.as_posix(), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _params(rng: random.Random, *, trans: bool) -> dict:
    value = {
        "root_pose": [math.pi, 0.0, 0.0],
        "body_pose": [[rng.uniform(-0.5, 0.5) for _ in range(3)] for _ in range(21)],
        # These must never reach any output.
        "shape": [0.123456] * 10,
        "expr": [0.654321] * 10,
        "jaw_pose": [0.1, 0.0, 0.0],
        "lhand_pose": [[0.2, 0.0, 0.0]] * 15,
        "rhand_pose": [[0.2, 0.0, 0.0]] * 15,
    }
    if trans:
        value["trans"] = [0.0, 0.0, 2.0]
    return value


def _workspace(tmp_path: Path, *, stages: tuple[str, ...] = ("camera", "hand4whole-smplx-init", "smplx-smooth"),
               camera_mode: str = "virtual", eyes: tuple[str, ...] = ("left",), params: dict | None = None,
               relative: str = "dataset/bodyrig-42") -> Path:
    root = tmp_path / "workspace"
    dataset = root / relative
    dataset.mkdir(parents=True)
    receipt: dict = {
        "format": preprocess.WORKSPACE_FORMAT, "version": 1, "performer_id": "42", "subject_id": "bodyrig-42",
        "teacher_input_sha256": "b" * 64, "materialization_receipt_sha256": "c" * 64, "smplx_gender": "female",
        "smplx_gender_explicit": True, "upstream_default_gender_accepted": False, "dataset": "Custom",
        "frame_count": N, "working_dataset_relative_path": relative, "held_out_evaluation_disclosed": False,
        "original_video_copied": False, "dependency_root_modified": False, "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["workspace_sha256"] = preprocess._digest(receipt, omit="workspace_sha256")
    (root / "workspace-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    (dataset / "bodyrig-source-map.json").write_text(json.dumps({
        "format": tp.SOURCE_MAP_FORMAT, "version": 1, "teacher_input_sha256": "b" * 64, "source_key": "SECRET-SOURCE-KEY",
        "frames": [{"exavatar_frame_index": i, "timestamp_seconds": 10.0 + 3 * (N - i), "eye": eyes[i % len(eyes)]}
                   for i in range(N)],
    }), encoding="utf-8")
    rng = random.Random(3)
    outputs: dict[str, list[dict]] = {name: [] for name in stages}
    for i in range(N):
        if "camera" in stages:
            record = _write(dataset / "cam_params" / f"{i}.json",
                            {"R": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], "t": [0.0, 0.0, 0.0],
                             "focal": [1000.0, 1000.0], "princpt": [384.0, 384.0]})
            record.update({"camera_frame_index": i, "rotation_determinant": 1.0, "rotation_max_orthogonality_error": 0.0,
                           "translation": [0.0, 0.0, 0.0], "focal": [1000.0, 1000.0], "principal_point": [384.0, 384.0],
                           "semantic_camera_validation": True})
            outputs["camera"].append(record)
        if "hand4whole-smplx-init" in stages:
            value = (params or {}).get(("init", i)) or _params(rng, trans=False)
            outputs["hand4whole-smplx-init"].append(_write(dataset / "smplx_init" / f"{i}.json", value))
        if "smplx-smooth" in stages:
            value = (params or {}).get(("smoothed", i)) or _params(rng, trans=True)
            outputs["smplx-smooth"].append(
                _write(dataset / "smplx_optimized" / "smplx_params_smoothed" / f"{i}.json", value))
    state = {
        "format": preprocess.STATE_FORMAT, "version": 1, "preprocess_plan_sha256": "a" * 64,
        "workspace_sha256": receipt["workspace_sha256"], "camera_mode": camera_mode,
        "completed_stages": [{"name": name, "outputs": outputs[name]} for name in stages],
        "photoreal_acceptance_authority": False, "production_activation": False,
    }
    (root / "preprocess-state.json").write_text(json.dumps(state), encoding="utf-8")
    logs = root / "logs" / "preprocess"
    logs.mkdir(parents=True)
    (logs / "stage-timing.jsonl").write_text(
        json.dumps({"format": "bodyrig-exavatar-stage-timing", "stage": "hand4whole-smplx-init", "state": "completed",
                    "elapsed_seconds": 61.5, "log": "03-SECRET-LOG-NAME.log"}) + "\nnot json\n", encoding="utf-8")
    return root


def _consent(tmp_path: Path, root: Path, **overrides) -> Path:
    path = tmp_path / "consent.json"
    tp.record_consent(workspace_root=root, out_path=path, relation=overrides.get("relation", "self"),
                      subject_is_adult=True, consent_evidence_sha256=overrides.get("evidence"))
    return path


def _export(tmp_path: Path, root: Path, consent: Path, *, source: str = "auto", out: Path | None = None) -> dict:
    return tp.export_pose(workspace_root=root, consent_path=consent, out_dir=out or tmp_path / "out",
                          rest_joints=REST, template_model_sha256=MODEL_SHA, source=source)


def _bvh(path: Path) -> tuple[list[str], int, list[list[float]]]:
    head, motion = path.read_text(encoding="utf-8").split("MOTION\n")
    names = [line.split()[1] for line in head.splitlines() if line.strip().startswith(("ROOT", "JOINT"))]
    lines = motion.splitlines()
    return names, int(lines[0].split()[1]), [[float(v) for v in line.split()] for line in lines[2:]]


# --- the export ----------------------------------------------------------------------------


def test_smoothed_motion_is_written_in_the_documented_frame(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    manifest = _export(tmp_path, root, _consent(tmp_path, root))
    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir()) == sorted(tp.OUTPUT_NAMES)
    assert manifest["state"] == "POSE_READY" and manifest["mesh"] == "unavailable"
    assert manifest["motion_source"] == {"source": "smoothed", "preprocess_stage": "smplx-smooth"}
    assert manifest["likeness_authority"] is False and manifest["modelrig_transfer"] is False
    names, frames, rows = _bvh(out / "motion.bvh")
    assert names == [tp.JOINTS[i] for i in tp.hierarchy_order()] and sorted(names) == sorted(tp.JOINTS)
    assert frames == N and all(len(r) == 6 + 3 * 21 for r in rows)
    motion = json.loads((out / "motion.json").read_text(encoding="utf-8"))
    # Upright in an ExAvatar camera (root = 180 degrees about X) is upright in the output frame,
    # and 2 m in front of the camera is at -Z (the output's forward).
    first = motion["frames"][0]
    assert first["root_rotation_axis_angle"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)
    assert first["root_position"] == pytest.approx([0.0, 0.0, -2.0])
    assert rows[0][:6] == pytest.approx([0.0, 0.0, -2.0, 0.0, 0.0, 0.0], abs=1e-6)
    # Samples are ordered by their real timestamp, which runs opposite to the frame index here.
    assert [f["exavatar_frame_index"] for f in motion["frames"]] == [3, 2, 1, 0]
    assert [f["bvh_frame"] for f in motion["frames"]] == [0, 1, 2, 3]
    artifacts = {a["name"]: a["sha256"] for a in manifest["artifacts"]}
    assert artifacts["motion.bvh"] == hashlib.sha256((out / "motion.bvh").read_bytes()).hexdigest()
    assert manifest["manifest_sha256"] == tp._canonical_digest(manifest, omit="manifest_sha256")


def test_init_motion_has_no_root_translation(tmp_path: Path) -> None:
    root = _workspace(tmp_path, stages=("camera", "hand4whole-smplx-init"))
    manifest = _export(tmp_path, root, _consent(tmp_path, root))
    assert manifest["motion_source"]["source"] == "init"
    motion = json.loads((tmp_path / "out" / "motion.json").read_text(encoding="utf-8"))
    assert all(f["root_position"] is None for f in motion["frames"])
    assert _bvh(tmp_path / "out" / "motion.bvh")[2][0][:3] == [0.0, 0.0, 0.0]


def test_no_shape_face_hand_identity_or_source_data_reaches_any_output(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _export(tmp_path, root, _consent(tmp_path, root))
    for path in (tmp_path / "out").iterdir():
        text = path.read_text(encoding="utf-8")
        for forbidden in ("0.123456", "0.654321", '"shape"', '"expr"', "hand_pose", "jaw", "bodyrig-42", "performer",
                          "subject_id", "SECRET", "female"):
            assert forbidden not in text, (path.name, forbidden)


def test_the_export_is_deterministic(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    _export(tmp_path, root, consent, out=tmp_path / "a")
    _export(tmp_path, root, consent, out=tmp_path / "b")
    for name in tp.OUTPUT_NAMES:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


def test_stage_timings_carry_only_stage_state_and_elapsed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    manifest = _export(tmp_path, root, _consent(tmp_path, root))
    assert manifest["preprocess_stage_timings"] == [
        {"stage": "hand4whole-smplx-init", "state": "completed", "elapsed_seconds": 61.5}]


def test_a_malformed_sample_is_invalid_and_the_rest_are_kept(tmp_path: Path) -> None:
    bad = {"root_pose": [0.0, 0.0], "body_pose": [[0.0, 0.0, 0.0]] * 21, "trans": [0.0, 0.0, 1.0]}
    nan = {"root_pose": [0.0, 0.0, 0.0], "body_pose": [[0.0, 0.0, 0.0]] * 21, "trans": [0.0, float("nan"), 1.0]}
    root = _workspace(tmp_path, params={("smoothed", 1): bad, ("smoothed", 2): nan})
    manifest = _export(tmp_path, root, _consent(tmp_path, root))
    motion = json.loads((tmp_path / "out" / "motion.json").read_text(encoding="utf-8"))
    by_index = {f["exavatar_frame_index"]: f for f in motion["frames"]}
    assert (by_index[1]["valid"], by_index[1]["invalid_reason"], by_index[1]["bvh_frame"]) == (False, "malformed_pose", None)
    assert by_index[2]["invalid_reason"] == "malformed_translation"
    assert manifest["timing"]["valid_samples"] == 2 and manifest["invalid_samples"] == ["malformed_pose", "malformed_translation"]
    assert _bvh(tmp_path / "out" / "motion.bvh")[1] == 2


def test_no_valid_sample_is_refused(tmp_path: Path) -> None:
    bad = {"root_pose": "x", "body_pose": []}
    root = _workspace(tmp_path, stages=("camera", "hand4whole-smplx-init"), params={("init", i): bad for i in range(N)})
    with pytest.raises(tp.TwinPoseError, match="no frame has a valid pose"):
        _export(tmp_path, root, _consent(tmp_path, root))
    assert not (tmp_path / "out").exists()


# --- readiness and workspace integrity -----------------------------------------------------


def test_a_workspace_without_the_needed_stage_is_not_ready(tmp_path: Path) -> None:
    root = _workspace(tmp_path, stages=("camera",))
    consent = _consent(tmp_path, root)
    with pytest.raises(tp.TwinPoseNotReady):
        _export(tmp_path, root, consent)
    with pytest.raises(tp.TwinPoseNotReady):
        _export(tmp_path, root, consent, source="smoothed")


def test_colmap_mode_is_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path, camera_mode="colmap")
    with pytest.raises(tp.TwinPoseError, match="virtual camera mode"):
        _export(tmp_path, root, _consent(tmp_path, root))


def test_a_parameter_file_changed_after_recording_is_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    target = root / "dataset/bodyrig-42/smplx_optimized/smplx_params_smoothed/2.json"
    target.write_bytes(target.read_bytes().replace(b"2.0", b"3.0"))
    with pytest.raises(tp.TwinPoseError, match="drifted"):
        _export(tmp_path, root, consent)


def test_a_file_the_state_did_not_record_is_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    state_path = root / "preprocess-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    smooth = next(s for s in state["completed_stages"] if s["name"] == "smplx-smooth")
    smooth["outputs"] = smooth["outputs"][:-1]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(tp.TwinPoseError, match="not an output the preprocess state recorded"):
        _export(tmp_path, root, _consent(tmp_path, root))


def test_a_tampered_receipt_or_state_is_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    receipt_path = root / "workspace-receipt.json"
    original = receipt_path.read_text(encoding="utf-8")
    receipt_path.write_text(original.replace('"female"', '"male"'), encoding="utf-8")
    with pytest.raises(tp.TwinPoseError, match="workspace receipt"):
        _export(tmp_path, root, consent)
    receipt_path.write_text(original, encoding="utf-8")
    state_path = root / "preprocess-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["workspace_sha256"] = "f" * 64
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(tp.TwinPoseError, match="different workspace"):
        _export(tmp_path, root, consent)


def test_mixed_eyes_or_a_foreign_source_map_are_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path, eyes=("left", "right"))
    with pytest.raises(tp.TwinPoseError, match="mixes stereo eyes"):
        _export(tmp_path, root, _consent(tmp_path, root))


def test_a_dataset_path_that_escapes_the_workspace_is_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path, stages=("camera", "hand4whole-smplx-init"), relative="../outside/bodyrig-42")
    with pytest.raises(tp.TwinPoseError, match="outside the workspace|escapes|drifted"):
        _export(tmp_path, root, _consent(tmp_path, root))


# --- symlinks at the read and write boundaries ---------------------------------------------


def test_a_symlinked_workspace_root_is_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(tp.TwinPoseError, match="symlink|real directory"):
        _export(tmp_path, link, consent)


def test_a_symlinked_parameter_file_is_refused_even_with_matching_bytes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    target = root / "dataset/bodyrig-42/smplx_optimized/smplx_params_smoothed/1.json"
    copy = tmp_path / "copy.json"
    copy.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(copy)
    with pytest.raises(tp.TwinPoseError):
        _export(tmp_path, root, consent)


def test_a_symlinked_consent_record_is_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    link = tmp_path / "consent-link.json"
    link.symlink_to(consent)
    with pytest.raises(tp.TwinPoseError, match="symlink|cannot be opened"):
        _export(tmp_path, root, link)


def test_a_symlinked_output_directory_or_parent_is_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "out-link").symlink_to(real, target_is_directory=True)
    with pytest.raises(tp.TwinPoseError, match="symlink"):
        _export(tmp_path, root, consent, out=tmp_path / "out-link")
    with pytest.raises(tp.TwinPoseError, match="symlink"):
        _export(tmp_path, root, consent, out=tmp_path / "out-link" / "inner")
    assert list(real.iterdir()) == []


def test_an_output_file_that_is_a_symlink_is_refused_and_its_target_untouched(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    out = tmp_path / "out"
    out.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    (out / "motion.bvh").symlink_to(victim)
    with pytest.raises(tp.TwinPoseError, match="not a regular file"):
        _export(tmp_path, root, consent)
    assert victim.read_text(encoding="utf-8") == "keep"
    assert not any(p.name.endswith(".tmp") for p in out.iterdir())


def test_the_output_directory_is_private(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _export(tmp_path, root, _consent(tmp_path, root))
    if os.name == "posix":
        assert (tmp_path / "out").stat().st_mode & 0o777 == 0o700


# --- consent -------------------------------------------------------------------------------


def test_no_consent_record_no_export(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    with pytest.raises(tp.TwinPoseError, match="cannot be opened"):
        _export(tmp_path, root, tmp_path / "missing.json")


def test_a_consent_record_for_another_workspace_or_altered_is_refused(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    document = json.loads(consent.read_text(encoding="utf-8"))
    other = tp.build_consent(workspace_sha256="e" * 64, relation="self", subject_is_adult=True)
    consent.write_text(json.dumps(other), encoding="utf-8")
    with pytest.raises(tp.TwinPoseError, match="different workspace"):
        _export(tmp_path, root, consent)
    altered = {**document, "subject_relation": "consenting-adult", "consent_evidence_sha256": "1" * 64}
    consent.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(tp.TwinPoseError, match="changed after it was recorded"):
        _export(tmp_path, root, consent)


@pytest.mark.parametrize("kwargs, problem", [
    ({"relation": "self", "subject_is_adult": False}, "adult"),
    ({"relation": "consenting-adult", "subject_is_adult": True}, "required for a consenting adult"),
    ({"relation": "stranger", "subject_is_adult": True}, "relation"),
])
def test_consent_without_an_adult_or_evidence_cannot_be_recorded(kwargs: dict, problem: str) -> None:
    with pytest.raises(tp.TwinPoseError, match=problem):
        tp.build_consent(workspace_sha256="a" * 64, **kwargs)


def test_a_consenting_adult_needs_evidence_and_then_exports(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root, relation="consenting-adult", evidence="2" * 64)
    assert _export(tmp_path, root, consent)["consent"]["subject_relation"] == "consenting-adult"


def test_a_consent_record_is_never_overwritten(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    before = consent.read_bytes()
    with pytest.raises(tp.TwinPoseError, match="already exists"):
        _consent(tmp_path, root)
    assert consent.read_bytes() == before


def test_extra_fields_in_a_consent_record_are_refused() -> None:
    document = tp.build_consent(workspace_sha256="a" * 64, relation="self", subject_is_adult=True)
    with pytest.raises(tp.TwinPoseError, match="unknown fields"):
        tp.validate_consent({**document, "note": "x"}, workspace_sha256="a" * 64)


# --- CLI -----------------------------------------------------------------------------------


def test_cli_requires_the_adult_flag_and_reports_not_ready_as_2(tmp_path: Path, capsys, monkeypatch) -> None:
    root = _workspace(tmp_path, stages=("camera",))
    assert cli(["record-consent", "--workspace-root", str(root), "--relation", "self", "--out", str(tmp_path / "c.json")]) == 1
    assert not (tmp_path / "c.json").exists()
    assert cli(["record-consent", "--workspace-root", str(root), "--relation", "self", "--subject-is-adult",
                "--out", str(tmp_path / "c.json")]) == 0
    monkeypatch.setattr("bodyrig.twin_pose_cli.load_template_rest_joints", lambda _p: (REST, MODEL_SHA))
    code = cli(["pose", "--workspace-root", str(root), "--consent", str(tmp_path / "c.json"),
                "--smplx-model", "unused.npz", "--out", str(tmp_path / "out")])
    assert code == 2
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["ready"] is False


# --- rotations, BVH and the rest skeleton --------------------------------------------------


def test_euler_and_axis_angle_round_trip() -> None:
    rng = random.Random(7)
    for _ in range(500):
        v = [rng.uniform(-3, 3) for _ in range(3)]
        m = tp.axis_angle_to_matrix(v)
        z, x, y = (math.radians(a) for a in tp.matrix_to_zxy_degrees(m))
        cz, sz, cx, sx, cy, sy = math.cos(z), math.sin(z), math.cos(x), math.sin(x), math.cos(y), math.sin(y)
        rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
        rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
        ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
        back = tp._mul(tp._mul(rz, rx), ry)
        assert max(abs(back[i][j] - m[i][j]) for i in range(3) for j in range(3)) < 1e-9
        again = tp.axis_angle_to_matrix(tp.matrix_to_axis_angle(m))
        assert max(abs(again[i][j] - m[i][j]) for i in range(3) for j in range(3)) < 1e-6
    half = tp.axis_angle_to_matrix([0.0, math.pi, 0.0])
    back = tp.axis_angle_to_matrix(tp.matrix_to_axis_angle(half))
    assert [v for row in back for v in row] == pytest.approx([v for row in half for v in row], abs=1e-6)


def test_the_rest_skeleton_comes_from_the_template_and_the_kinematic_tree_is_checked(tmp_path: Path) -> None:
    np = pytest.importorskip("numpy")
    template = np.random.default_rng(1).normal(size=(30, 3))
    regressor = np.zeros((55, 30))
    for joint in range(55):
        regressor[joint, joint % 30] = 1.0
    tree = np.zeros((2, 55), dtype=np.int64)
    tree[0, :22] = [4294967295, *tp.PARENTS[1:]]
    path = tmp_path / "SMPLX_NEUTRAL.npz"
    # Real SMPL-X archives also hold object arrays; they are never read, so no pickle is needed.
    np.savez(path, v_template=template, J_regressor=regressor, kintree_table=tree,
             joint2num=np.array([{"pelvis": 0}], dtype=object))
    joints, sha = tp.load_template_rest_joints(path)
    assert joints[3] == pytest.approx(template[3].tolist()) and sha == hashlib.sha256(path.read_bytes()).hexdigest()
    tree[0, 5] = 0
    np.savez(path, v_template=template, J_regressor=regressor, kintree_table=tree)
    with pytest.raises(tp.TwinPoseError, match="kinematic tree"):
        tp.load_template_rest_joints(path)


def test_bvh_offsets_follow_the_rest_skeleton_and_the_root_offset_is_zero() -> None:
    sample = {"root_rotation": tp.axis_angle_to_matrix([0, 0, 0]), "root_position": None,
              "local_rotations": [[0.0, 0.0, 0.0]] * 21}
    text = tp.write_bvh(REST, [sample])
    offsets = [line.split()[1:] for line in text.splitlines() if line.strip().startswith("OFFSET")]
    assert offsets[0] == ["0.000000", "0.000000", "0.000000"]
    assert [float(v) for v in offsets[1]] == pytest.approx([0.01, 0.05, -0.01])  # left_hip - pelvis
    assert text.count("{") == text.count("}")


# --- the downstream consumer: the scene inspector reads the BVH ----------------------------


def test_scene_inspector_reads_the_exported_bvh(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _export(tmp_path, root, _consent(tmp_path, root))
    bvh = tmp_path / "out" / "motion.bvh"
    assert si.FORMATS[".bvh"] == "bvh"
    assert si.minimum_metadata(bvh, "bvh", bvh.stat().st_size) == {
        "counted": True, "joints": 22, "frames": N, "frame_time_seconds": pytest.approx(1 / 30, abs=1e-6)}
    not_bvh = tmp_path / "x.bvh"
    not_bvh.write_text("hello\n", encoding="utf-8")
    with pytest.raises(si.SceneInspectionError):
        si.minimum_metadata(not_bvh, "bvh", 6)


def test_bvh_channels_follow_the_declared_joint_order() -> None:
    # Only left_knee (SMPL-X index 4) is bent; its three channels must sit where left_knee is declared.
    local = [[0.0, 0.0, 0.0] for _ in range(21)]
    local[4 - 1] = [0.5, 0.0, 0.0]
    sample = {"root_rotation": tp.axis_angle_to_matrix([0, 0, 0]), "root_position": None, "local_rotations": local}
    row = [float(v) for v in tp.write_bvh(REST, [sample]).splitlines()[-1].split()]
    order = tp.hierarchy_order()
    slot = order.index(4)  # position among declared joints; the root has 6 channels
    knee = row[6 + 3 * (slot - 1): 6 + 3 * slot]
    assert knee == pytest.approx([0.0, math.degrees(0.5), 0.0], abs=1e-6)
    assert sum(abs(v) for v in row) == pytest.approx(math.degrees(0.5), abs=1e-6)
    assert order[:5] == [0, 1, 4, 7, 10]


def test_a_consent_record_reached_through_a_symlinked_folder_is_refused(tmp_path: Path) -> None:
    # O_NOFOLLOW covers only the last component; the resolve check covers the folders above it.
    root = _workspace(tmp_path)
    consent = _consent(tmp_path, root)
    real = tmp_path / "real-folder"
    real.mkdir()
    consent.rename(real / "consent.json")
    (tmp_path / "folder-link").symlink_to(real, target_is_directory=True)
    with pytest.raises(tp.TwinPoseError, match="goes through a symlink"):
        _export(tmp_path, root, tmp_path / "folder-link" / "consent.json")
