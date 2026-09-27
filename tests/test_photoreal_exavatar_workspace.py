from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from bodyrig import photoreal_exavatar_workspace as workspace


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _materialized_dataset(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    dataset = tmp_path / "dataset"
    frames = dataset / "frames"
    frames.mkdir(parents=True)
    frame = frames / "0.png"
    frame.write_bytes(b"png-frame")
    (dataset / "frame_list_all.txt").write_text("0\n", encoding="utf-8")
    (dataset / "frame_list_train.txt").write_text("0\n", encoding="utf-8")
    (dataset / "frame_list_test.txt").write_text("", encoding="utf-8")
    receipt: dict[str, object] = {
        "format": workspace.MATERIALIZATION_FORMAT,
        "version": 1,
        "benchmark_plan_sha256": "a" * 64,
        "teacher_input_sha256": "b" * 64,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "upstream_commit": workspace.UPSTREAM_COMMIT,
        "source_key": "scene:42:E:/train.mp4",
        "source_sha256": "c" * 64,
        "frame_count": 1,
        "frames": [
            {
                "exavatar_frame_index": 0,
                "source_key": "scene:42:E:/train.mp4",
                "source_frame_sha256": "d" * 64,
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "relative_path": "frames/0.png",
                "staged_png_sha256": _sha(frame),
                "width": 1920,
                "height": 1080,
            }
        ],
        "frame_lists_are_training_only": True,
        "bodyrig_held_out_evaluation_is_external": True,
        "held_out_evaluation_disclosed": False,
        "original_video_copied": False,
        "exact_p0_frame_hashes_reproduced": True,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "production_activation": False,
    }
    return dataset, receipt


def _strict_preflight() -> dict[str, object]:
    value: dict[str, object] = {
        "format": workspace.PREFLIGHT_FORMAT,
        "version": 1,
        "upstream_commit": workspace.UPSTREAM_COMMIT,
        "smplx_gender": "female",
        "smplx_gender_explicit": True,
        "upstream_default_gender_accepted": False,
        "strict_upstream_asset_inventory": True,
        "strict_flame_asset_count": 3,
        "benchmark_environment_ready": True,
        "blockers": [],
        "automatic_restricted_asset_download": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "assets": [],
        "reference_vision_assets": [],
    }
    value["preflight_sha256"] = workspace._canonical_digest(value, omit="preflight_sha256")
    return value


def test_avatar_config_patch_forces_custom_and_explicit_female(tmp_path: Path) -> None:
    config = tmp_path / "config.py"
    config.write_text(
        "class Config:\n"
        "    dataset = 'NeuMan' # Custom, NeuMan\n"
        "    smplx_gender = 'male' # only use male version as female version is not very good\n",
        encoding="utf-8",
    )

    receipt = workspace._patch_avatar_config(config, smplx_gender="female")
    patched = config.read_text(encoding="utf-8")

    assert "dataset = 'Custom'" in patched
    assert "smplx_gender = 'female'" in patched
    assert "smplx_gender = 'male'" not in patched
    assert receipt["dataset"] == "Custom"
    assert receipt["smplx_gender"] == "female"
    assert receipt["before_sha256"] != receipt["after_sha256"]


def test_materialization_validation_rejects_original_video(tmp_path: Path) -> None:
    dataset, receipt = _materialized_dataset(tmp_path)
    (dataset / "video.mp4").write_bytes(b"forbidden")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="original video.mp4"):
        workspace._validate_materialization(receipt, dataset)


def test_materialization_validation_rejects_nonempty_exavatar_test_split(tmp_path: Path) -> None:
    dataset, receipt = _materialized_dataset(tmp_path)
    (dataset / "frame_list_test.txt").write_text("0\n", encoding="utf-8")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="test split"):
        workspace._validate_materialization(receipt, dataset)


def test_strict_preflight_requires_explicit_matching_female_prior() -> None:
    preflight = _strict_preflight()
    assert workspace._validate_preflight(preflight, smplx_gender="female") == preflight["preflight_sha256"]

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="gender mismatch"):
        workspace._validate_preflight(preflight, smplx_gender="male")


def test_preflight_without_strict_upstream_assets_cannot_prepare_workspace() -> None:
    preflight = _strict_preflight()
    preflight["strict_upstream_asset_inventory"] = False
    preflight["preflight_sha256"] = workspace._canonical_digest(preflight, omit="preflight_sha256")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="not strict-upstream complete"):
        workspace._validate_preflight(preflight, smplx_gender="female")


def test_pinned_sith_uv_template_requires_exact_clean_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "sith"
    (root / ".git").mkdir(parents=True)
    template = root / "data" / "smplx_uv.obj"
    template.parent.mkdir(parents=True)
    template.write_text(
        "v 0 0 0\nvt 0 0\nf 1/1 1/1 1/1\n",
        encoding="utf-8",
    )

    def fake_git(path: Path, *args: str) -> str:
        assert path.resolve() == root.resolve()
        if args == ("remote", "get-url", "origin"):
            return "https://github.com/SiTH-Diffusion/SiTH.git"
        if args == ("rev-parse", "HEAD"):
            return workspace.SITH_REVISION
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(workspace, "_git", fake_git)
    assert workspace._resolve_pinned_sith_uv_template(root) == template.resolve()


def test_pinned_sith_uv_template_rejects_wrong_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "sith"
    (root / ".git").mkdir(parents=True)
    template = root / "data" / "smplx_uv.obj"
    template.parent.mkdir(parents=True)
    template.write_text("vt 0 0\nf 1/1 1/1 1/1\n", encoding="utf-8")

    def fake_git(path: Path, *args: str) -> str:
        if args == ("remote", "get-url", "origin"):
            return "https://github.com/SiTH-Diffusion/SiTH.git"
        if args == ("rev-parse", "HEAD"):
            return "0" * 40
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(workspace, "_git", fake_git)
    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="revision mismatch"):
        workspace._resolve_pinned_sith_uv_template(root)


def test_workspace_required_validation_helpers_are_present() -> None:
    assert callable(workspace._validate_preflight)
    assert callable(workspace._validate_materialization)
    assert callable(workspace._preflight_asset_map)
    assert callable(workspace._verify_asset)


def test_safe_subject_id_is_deterministic_and_path_safe() -> None:
    assert workspace._safe_subject_id("42") == "bodyrig-42"
    assert workspace._safe_subject_id("performer/42") == "bodyrig-performer-42"


def test_workspace_git_uses_command_local_safe_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "ExAvatar_RELEASE"
    checkout.mkdir()
    captured: dict[str, object] = {}

    def fake_run(argv, *, label):
        captured["argv"] = argv
        captured["label"] = label
        return workspace.UPSTREAM_COMMIT

    monkeypatch.setattr(workspace, "_run", fake_run)

    observed = workspace._git(checkout, "rev-parse", "HEAD")

    resolved = checkout.resolve()
    assert observed == workspace.UPSTREAM_COMMIT
    assert captured["argv"] == [
        "git",
        "-c",
        f"safe.directory={resolved}",
        "-C",
        str(resolved),
        "rev-parse",
        "HEAD",
    ]


def test_workspace_clone_uses_pinned_public_repository_after_local_authority_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "root-owned" / "ExAvatar_RELEASE"
    destination = tmp_path / "workspace" / "ExAvatar_RELEASE"
    source.mkdir(parents=True)
    calls: list[list[str]] = []
    git_calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_run(argv, *, label):
        calls.append(argv)
        return ""

    def fake_git(path: Path, *args: str):
        git_calls.append((path.resolve(), args))
        if path.resolve() == source.resolve() and args == ("rev-parse", "HEAD"):
            return workspace.UPSTREAM_COMMIT
        if args == ("status", "--porcelain"):
            return ""
        if path.resolve() == destination.resolve() and args == ("rev-parse", "HEAD"):
            return workspace.UPSTREAM_COMMIT
        raise AssertionError((path, args))

    monkeypatch.setattr(workspace, "_run", fake_run)
    monkeypatch.setattr(workspace, "_git", fake_git)

    url = "https://github.com/mks0601/ExAvatar_RELEASE"
    workspace._clone_pinned(source, destination, url, workspace.UPSTREAM_COMMIT)

    assert (source.resolve(), ("rev-parse", "HEAD")) in git_calls
    assert calls[0] == [
        "git",
        "clone",
        "--filter=blob:none",
        "--no-checkout",
        url,
        str(destination),
    ]
    assert str(source.resolve()) not in calls[0]
    assert calls[1] == [
        "git",
        "-C",
        str(destination),
        "checkout",
        "--detach",
        workspace.UPSTREAM_COMMIT,
    ]
    assert calls[2] == [
        "git",
        "-C",
        str(destination),
        "submodule",
        "update",
        "--init",
        "--recursive",
    ]


def test_workspace_clone_rejects_non_public_repository_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "workspace"
    source.mkdir()

    monkeypatch.setattr(
        workspace,
        "_git",
        lambda path, *args: workspace.UPSTREAM_COMMIT
        if args == ("rev-parse", "HEAD")
        else "",
    )

    with pytest.raises(
        workspace.PhotorealExAvatarWorkspaceError,
        match="repository URL is invalid",
    ):
        workspace._clone_pinned(
            source,
            destination,
            "ssh://example.invalid/private/repo",
            workspace.UPSTREAM_COMMIT,
        )


def test_internal_workspace_directory_link_survives_stage_publish(tmp_path: Path) -> None:
    stage = tmp_path / ".workspace.stage-123"
    final = tmp_path / "workspace"
    target = stage / "repos" / "mmpose"
    link = stage / "repos" / "ExAvatar_RELEASE" / "fitting" / "tools" / "mmpose"
    target.mkdir(parents=True)
    link.parent.mkdir(parents=True)

    workspace._link_internal_directory(target, link)

    assert link.is_symlink()
    assert not Path(link.readlink()).is_absolute()
    assert link.resolve() == target.resolve()

    stage.rename(final)

    published_target = final / "repos" / "mmpose"
    published_link = final / "repos" / "ExAvatar_RELEASE" / "fitting" / "tools" / "mmpose"
    assert published_link.is_symlink()
    assert published_link.resolve() == published_target.resolve()


def test_internal_workspace_subject_link_survives_stage_publish(tmp_path: Path) -> None:
    stage = tmp_path / ".workspace.stage-456"
    final = tmp_path / "workspace"
    dataset = stage / "dataset" / "bodyrig-42"
    link = (
        stage
        / "repos"
        / "ExAvatar_RELEASE"
        / "fitting"
        / "data"
        / "Custom"
        / "data"
        / "bodyrig-42"
    )
    dataset.mkdir(parents=True)
    link.parent.mkdir(parents=True)

    workspace._link_internal_directory(dataset, link)
    stage.rename(final)

    published_dataset = final / "dataset" / "bodyrig-42"
    published_link = (
        final
        / "repos"
        / "ExAvatar_RELEASE"
        / "fitting"
        / "data"
        / "Custom"
        / "data"
        / "bodyrig-42"
    )
    assert published_link.is_symlink()
    assert published_link.resolve() == published_dataset.resolve()


def test_injected_patch_destinations_are_published_relative_to_workspace(tmp_path: Path) -> None:
    stage = tmp_path / ".workspace.stage"
    destination = stage / "repos" / "DECA" / "run_deca.py"
    destination.parent.mkdir(parents=True)
    destination.write_text("patched", encoding="utf-8")
    records = [
        {
            "destination": destination.as_posix(),
            "source_sha256": "1" * 64,
            "replaced_sha256": "2" * 64,
            "patched_sha256": "3" * 64,
        }
    ]

    workspace._relativize_injected_patch_destinations(records, workspace_root=stage)

    assert records[0]["destination"] == "repos/DECA/run_deca.py"


def test_injected_patch_destination_cannot_escape_workspace(tmp_path: Path) -> None:
    stage = tmp_path / ".workspace.stage"
    stage.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("patched", encoding="utf-8")
    records = [
        {
            "destination": outside.as_posix(),
            "source_sha256": "1" * 64,
            "replaced_sha256": None,
            "patched_sha256": "3" * 64,
        }
    ]

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="escapes workspace staging root"):
        workspace._relativize_injected_patch_destinations(records, workspace_root=stage)


def test_avatar_checkpoint_patch_writes_snapshots_atomically(tmp_path: Path) -> None:
    base = tmp_path / "base.py"
    base.write_text(
        "import os\n"
        "import os.path as osp\n"
        "import torch\n"
        "\n"
        "class Trainer:\n"
        "    def save_model(self, state, epoch):\n"
        "        file_path = osp.join(cfg.model_dir,'snapshot_{}.pth'.format(str(epoch)))\n"
        "        torch.save(state, file_path)\n"
        "        self.logger.info(\"Write snapshot into {}\".format(file_path))\n",
        encoding="utf-8",
    )

    receipt = workspace._patch_avatar_checkpoint_save(base)
    patched = base.read_text(encoding="utf-8")

    assert "temp_path = file_path + '.bodyrig-tmp'" in patched
    assert "torch.save(state, temp_path)" in patched
    assert "os.replace(temp_path, file_path)" in patched
    assert "torch.save(state, file_path)" not in patched
    assert receipt["replaced_sha256"] != receipt["patched_sha256"]
    assert receipt["patched_sha256"] == _sha(base)


def test_avatar_checkpoint_patch_refuses_drifted_upstream_marker(tmp_path: Path) -> None:
    base = tmp_path / "base.py"
    base.write_text("def save_model():\n    pass\n", encoding="utf-8")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="checkpoint save marker changed"):
        workspace._patch_avatar_checkpoint_save(base)


def test_flame_static_embedding_staging_normalizes_legacy_crlf_without_mutating_source(tmp_path: Path) -> None:
    source = tmp_path / "flame_static_embedding.pkl"
    destination = tmp_path / "workspace" / "flame_static_embedding.pkl"
    original = b"(dp0\r\nS'lmk_face_idx'\r\np1\r\nS'lmk_b_coords'\r\np2\r\n."
    source.write_bytes(original)

    staged_sha = workspace._stage_flame_static_embedding(source, destination)

    assert source.read_bytes() == original
    assert destination.read_bytes() == b"(dp0\nS'lmk_face_idx'\np1\nS'lmk_b_coords'\np2\n.\n"
    assert staged_sha == _sha(destination)


def test_flame_static_embedding_staging_fails_closed_on_wrong_asset(tmp_path: Path) -> None:
    source = tmp_path / "flame_static_embedding.pkl"
    destination = tmp_path / "workspace" / "flame_static_embedding.pkl"
    source.write_bytes(b"not a FLAME landmark embedding\r\n")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="expected landmark keys"):
        workspace._stage_flame_static_embedding(source, destination)


def test_sam_patch_preserves_strong_points_and_adds_box_only_temporal_fallback(tmp_path: Path) -> None:
    source = tmp_path / "run_sam.py"
    destination = tmp_path / "destination" / "run_sam.py"
    source.write_text(
        "frame_idx_list = sorted([int(x.split('/')[-1][:-4]) for x in img_path_list])\n"
        "img_height, img_width = cv2.imread(img_path_list[0]).shape[:2]\n"
        "video_save = cv2.VideoWriter(osp.join(root_path, 'masks.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 30, (img_width*2, img_height))\n"
        "    # load keypoints\n"
        "    kpt_path = osp.join(root_path, 'keypoints_whole_body', str(frame_idx) + '.json')\n"
        "    with open(kpt_path) as f:\n"
        "        kpt = np.array(json.load(f), dtype=np.float32)\n"
        "    kpt = kpt[kpt[:,2] > 0.5,:2]\n"
        "    bbox = get_bbox(kpt, np.ones_like(kpt[:,0]))\n"
        "    bbox[2:] += bbox[:2] # xywh -> xyxy\n"
        "    masks, scores, logits = predictor.predict(point_coords=kpt, point_labels=np.ones_like(kpt[:,0]), box=bbox[None,:], multimask_output=False)\n"
        "    mask_input = logits[np.argmax(scores), :, :]\n"
        "    masks, _, _ = predictor.predict(point_coords=kpt, point_labels=np.ones_like(kpt[:,0]), box=bbox[None,:], multimask_output=False, mask_input=mask_input[None])\n",
        encoding="utf-8",
    )

    receipt = workspace._copy_sam_with_temporal_bbox_fallback(source, destination)
    patched = destination.read_text(encoding="utf-8")

    assert "bodyrig_all_kpt[:,2] > 0.5" in patched
    assert "BodyRig ExAvatar SAM bbox fallback: {} for frame {}" in patched
    assert "point_coords = kpt if kpt.shape[0] > 0 else None" in patched
    assert "point_labels = np.ones_like(kpt[:,0]) if kpt.shape[0] > 0 else None" in patched
    assert "point_coords=point_coords" in patched
    assert "BodyRig ExAvatar SAM has no valid >0.5 bbox seeds" in patched
    assert receipt["patched_sha256"] == _sha(destination)


def test_custom_dataset_patch_reuses_authoritative_body_bboxes_for_sparse_frames(tmp_path: Path) -> None:
    source = tmp_path / "Custom.py"
    source.write_text(
        "        self.cam_params, self.img_paths, self.kpts, self.smplx_params, self.flame_params, self.flame_shape_param, self.frame_idx_list = self.load_data()\n"
        "        self.get_smplx_trans_init() # get initial smplx translation \n"
        "    def get_smplx_trans_init(self):\n"
        "        for i in range(len(self.frame_idx_list)):\n"
        "            frame_idx = self.frame_idx_list[i]\n"
        "            cam_param = self.cam_params[frame_idx]\n"
        "            focal, princpt = cam_param['focal'], cam_param['princpt']\n"
        "\n"
        "            kpt = self.kpts[frame_idx]\n"
        "            kpt_img = kpt[:,:2]\n"
        "            kpt_valid = (kpt[:,2:] > 0.2).astype(np.float32)\n"
        "            bbox = get_bbox(kpt_img, kpt_valid[:,0])\n"
        "            bbox = set_aspect_ratio(bbox)\n"
        "\n"
        "            t_z = math.sqrt(focal[0]*focal[1]*cfg.body_3d_size*cfg.body_3d_size/(bbox[2]*bbox[3])) # meter\n"
        "            t_x = bbox[0] + bbox[2]/2 # pixel\n"
        "            t_y = bbox[1] + bbox[3]/2 # pixel\n"
        "            t_x = (t_x - princpt[0]) / focal[0] * t_z # meter\n"
        "            t_y = (t_y - princpt[1]) / focal[1] * t_z # meter\n"
        "            t_xyz = torch.FloatTensor([t_x, t_y, t_z]) \n"
        "            self.smplx_params[frame_idx]['trans'] = t_xyz\n"
        "        img_height, img_width = img_orig.shape[0], img_orig.shape[1]\n"
        "        bbox = get_bbox(kpt_img, kpt_valid[:,0])\n"
        "        bbox = set_aspect_ratio(bbox)\n"
        "        if np.sum(kpt_valid[smpl_x.kpt['part_idx']['face'],0]) == 0:\n"
        "            self.flame_params[frame_idx]['is_valid'] = False\n"
        "            bbox_face = np.array([0,0,1,1], dtype=np.float32)\n"
        "        else:\n"
        "            bbox_face = get_bbox(kpt_img[smpl_x.kpt['part_idx']['face'],:], kpt_valid[smpl_x.kpt['part_idx']['face'],0])\n"
        "        bbox_face = set_aspect_ratio(bbox_face)\n",
        encoding="utf-8",
    )

    receipt = workspace._patch_exavatar_custom_dataset_body_bboxes(source)
    patched = source.read_text(encoding="utf-8")

    assert "self.body_bboxes = self.get_body_bbox_init()" in patched
    assert "kpt[:,2:] > 0.2" in patched
    assert "BodyRig ExAvatar body bbox fallback: {} for frame {}" in patched
    assert "bbox = self.body_bboxes[frame_idx]" in patched
    assert "bbox = self.body_bboxes[frame_idx].copy()" in patched
    assert "float(bbox[2]) <= 1e-6" in patched
    assert "int(np.sum(face_valid)) < 2" in patched
    assert receipt["patched_sha256"] == _sha(source)


def test_fitting_edge_length_patch_stabilizes_zero_length_gradients(tmp_path: Path) -> None:
    path = tmp_path / "loss.py"
    path.write_text(
        "        d1_out = torch.sqrt(torch.sum((coord_out[:,face[:,0],:] - coord_out[:,face[:,1],:])**2,2,keepdim=True))\n"
        "        d2_out = torch.sqrt(torch.sum((coord_out[:,face[:,0],:] - coord_out[:,face[:,2],:])**2,2,keepdim=True))\n"
        "        d3_out = torch.sqrt(torch.sum((coord_out[:,face[:,1],:] - coord_out[:,face[:,2],:])**2,2,keepdim=True))\n"
        "\n"
        "        d1_gt = torch.sqrt(torch.sum((coord_gt[:,face[:,0],:] - coord_gt[:,face[:,1],:])**2,2,keepdim=True))\n"
        "        d2_gt = torch.sqrt(torch.sum((coord_gt[:,face[:,0],:] - coord_gt[:,face[:,2],:])**2,2,keepdim=True))\n"
        "        d3_gt = torch.sqrt(torch.sum((coord_gt[:,face[:,1],:] - coord_gt[:,face[:,2],:])**2,2,keepdim=True))\n",
        encoding="utf-8",
    )

    receipt = workspace._patch_fitting_edge_length_loss(path)
    patched = path.read_text(encoding="utf-8")

    assert "bodyrig_edge_eps = 1e-12" in patched
    assert patched.count("+ bodyrig_edge_eps)") == 6
    assert receipt["replaced_sha256"] != receipt["patched_sha256"]
    assert receipt["patched_sha256"] == _sha(path)


def test_fitting_edge_length_patch_fails_closed_on_upstream_drift(tmp_path: Path) -> None:
    path = tmp_path / "loss.py"
    path.write_text("class EdgeLengthLoss: pass\n", encoding="utf-8")

    with pytest.raises(
        workspace.PhotorealExAvatarWorkspaceError,
        match="EdgeLengthLoss marker changed",
    ):
        workspace._patch_fitting_edge_length_loss(path)


def test_hand4whole_patch_uses_pinned_wholebody_keypoints_without_pretrained_detector(tmp_path: Path) -> None:
    source = tmp_path / "run_hand4whole.py"
    destination = tmp_path / "destination" / "run_hand4whole.py"
    source.write_text(
        "import os.path as osp\n"
        "import json\n"
        "import numpy as np\n"
        "from torchvision import transforms as T\n"
        "from torchvision.models.detection import fasterrcnn_resnet50_fpn\n"
        "\n"
        "def get_one_box(det_output):\n"
        "    max_score = 0\n"
        "    max_bbox = None\n"
        "\n"
        "    for i in range(det_output['boxes'].shape[0]):\n"
        "        bbox = det_output['boxes'][i]\n"
        "        score = det_output['scores'][i]\n"
        "        if float(score) > max_score:\n"
        "            max_bbox = [float(x) for x in bbox]\n"
        "            max_score = score\n"
        "\n"
        "    return max_bbox\n"
        "\n"
        "for frame_idx in frame_idx_list:\n"
        "    original_img = cv2.cvtColor(cv2.imread(img_path), cv2.COLOR_BGR2RGB)\n"
        "    original_img_height, original_img_width = original_img.shape[:2]\n"
        "\n"
        "    # prepare bbox\n"
        "    det_model = fasterrcnn_resnet50_fpn(pretrained=True).cuda().eval()\n"
        "    det_transform = T.Compose([T.ToTensor()])\n"
        "    det_input = det_transform(original_img).cuda()\n"
        "    det_output = det_model([det_input])[0]\n"
        "    bbox = get_one_box(det_output) # xyxy\n"
        "    if bbox is None:\n"
        "        continue\n"
        "    bbox = [bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1]] # xywh\n"
        "    bbox = process_bbox(bbox, original_img_width, original_img_height)\n",
        encoding="utf-8",
    )
    destination.parent.mkdir(parents=True)
    destination.write_text("upstream destination", encoding="utf-8")

    receipt = workspace._copy_hand4whole_with_pinned_keypoint_bbox(source, destination)
    patched = destination.read_text(encoding="utf-8")

    assert "fasterrcnn_resnet50_fpn" not in patched
    assert "from torchvision import transforms as T" not in patched
    assert "def get_one_box" not in patched
    assert "keypoints_whole_body" in patched
    assert "bodyrig_person = bodyrig_kpt[:23]" in patched
    assert "bodyrig_person[:,2] > 0.5" in patched
    assert "bodyrig_person[:,2] > 0.2" in patched
    assert "bodyrig_confidence_mode = 'weak'" in patched
    assert "reuse previous valid bbox for frame" in patched
    assert "full-frame bootstrap fallback for frame" in patched
    assert "process_bbox(bodyrig_candidate_bbox, original_img_width, original_img_height)" in patched
    assert "body/foot keypoints insufficient for frame" not in patched
    assert receipt["source_sha256"] == _sha(source)
    assert receipt["patched_sha256"] == _sha(destination)
    assert receipt["replaced_sha256"] is not None


def test_hand4whole_patch_fails_closed_if_upstream_detector_block_drifts(tmp_path: Path) -> None:
    source = tmp_path / "run_hand4whole.py"
    destination = tmp_path / "run_hand4whole-destination.py"
    source.write_text("# changed upstream runner\n", encoding="utf-8")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="detector marker changed"):
        workspace._copy_hand4whole_with_pinned_keypoint_bbox(source, destination)


def test_hand4whole_inference_patch_avoids_unused_classic_smpl_initialization(tmp_path: Path) -> None:
    root = tmp_path / "Hand4Whole_RELEASE"
    human_models = root / "common" / "utils" / "human_models.py"
    preprocessing = root / "common" / "utils" / "preprocessing.py"
    human_models.parent.mkdir(parents=True)
    human_models.write_text(
        "class SMPLX: pass\nclass SMPL: pass\nsmpl_x = SMPLX()\nsmpl = SMPL()\n",
        encoding="utf-8",
    )
    preprocessing.write_text(
        "from utils.human_models import smpl_x, smpl\n",
        encoding="utf-8",
    )

    receipts = workspace._patch_hand4whole_inference_only_human_models(root)

    human_patched = human_models.read_text(encoding="utf-8")
    prep_patched = preprocessing.read_text(encoding="utf-8")
    assert "smpl_x = SMPLX()" in human_patched
    assert "smpl = SMPL()" not in human_patched
    assert "does not instantiate classic SMPL" in human_patched
    assert "from utils.human_models import smpl_x, smpl" not in prep_patched
    assert "from utils.human_models import smpl_x" in prep_patched
    assert len(receipts) == 2
    assert all(item["patched_sha256"] for item in receipts)


def test_deca_patch_uses_pinned_wholebody_face_keypoints_without_fan(tmp_path: Path) -> None:
    source = tmp_path / "datasets.py"
    destination = tmp_path / "destination" / "datasets.py"
    source.write_text(
        "import os, sys\n"
        "import numpy as np\n"
        "import scipy.io\n"
        "from . import detectors\n"
        "\n"
        "class TestData:\n"
        "    def __init__(self, face_detector='fan'):\n"
        "        if face_detector == 'fan':\n"
        "            self.face_detector = detectors.FAN()\n"
        "        # elif face_detector == 'mtcnn':\n"
        "        #     self.face_detector = detectors.MTCNN()\n"
        "        else:\n"
        "            print(f'please check the detector: {face_detector}')\n"
        "            exit()\n"
        "\n"
        "    def item(self):\n"
        "            else:\n"
        "                bbox, bbox_type = self.face_detector.run(image)\n"
        "                if len(bbox) < 4:\n"
        "                    print('no face detected! run original image')\n"
        "                    left = 0; right = h-1; top=0; bottom=w-1\n"
        "                    is_valid = False\n"
        "                else:\n"
        "                    left = bbox[0]; right=bbox[2]\n"
        "                    top = bbox[1]; bottom=bbox[3]\n"
        "                old_size, center = self.bbox2point(left, right, top, bottom, type=bbox_type)\n",
        encoding="utf-8",
    )
    destination.parent.mkdir(parents=True)
    destination.write_text("original destination", encoding="utf-8")

    receipt = workspace._copy_deca_dataset_with_pinned_face_keypoints(source, destination)
    patched = destination.read_text(encoding="utf-8")

    assert "import json" in patched
    assert "detectors.FAN()" not in patched
    assert "from . import detectors" not in patched
    assert "keypoints_whole_body" in patched
    assert "bodyrig_face = bodyrig_kpt[23:91]" in patched
    assert "bodyrig_face[:,2] > 0.5" in patched
    assert "raise RuntimeError('BodyRig face keypoints insufficient" not in patched
    assert "BodyRig face keypoints insufficient; mark DECA frame invalid and use original image" in patched
    assert "left = 0; right = w-1; top = 0; bottom = h-1" in patched
    assert "is_valid = False" in patched
    assert "type='bbox'" in patched
    assert "type='kpt68'" in patched
    assert receipt["source_sha256"] == _sha(source)
    assert receipt["patched_sha256"] == _sha(destination)
    assert receipt["replaced_sha256"] is not None


def test_deca_patch_fails_closed_if_detector_markers_drift(tmp_path: Path) -> None:
    source = tmp_path / "datasets.py"
    destination = tmp_path / "destination.py"
    source.write_text("import scipy.io\n# changed detector path\n", encoding="utf-8")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="face-detector markers changed"):
        workspace._copy_deca_dataset_with_pinned_face_keypoints(source, destination)



def _run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _run_git(path, "init")
    _run_git(path, "config", "user.email", "bodyrig-tests@example.invalid")
    _run_git(path, "config", "user.name", "BodyRig Tests")


def test_clone_pinned_initializes_submodules_via_workspace_clone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    calls: list[list[str]] = []

    def fake_run(argv, *, label):
        calls.append(argv)
        return ""

    def fake_git(path: Path, *args: str):
        if path.resolve() == source.resolve() and args == ("rev-parse", "HEAD"):
            return "a" * 40
        if args == ("status", "--porcelain"):
            return ""
        if path.resolve() == destination.resolve() and args == ("rev-parse", "HEAD"):
            return "a" * 40
        raise AssertionError((path, args))

    monkeypatch.setattr(workspace, "_run", fake_run)
    monkeypatch.setattr(workspace, "_git", fake_git)

    workspace._clone_pinned(
        source,
        destination,
        "https://github.com/example/public-repo",
        "a" * 40,
    )

    assert [
        "git",
        "-C",
        str(destination),
        "submodule",
        "update",
        "--init",
        "--recursive",
    ] in calls


