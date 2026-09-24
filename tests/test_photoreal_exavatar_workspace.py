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


def test_workspace_local_clone_uses_bundle_instead_of_root_owned_source_transport(
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
        if args == ("rev-parse", "HEAD"):
            return workspace.UPSTREAM_COMMIT
        if args == ("status", "--porcelain"):
            return ""
        if args[:2] == ("bundle", "create"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(workspace, "_run", fake_run)
    monkeypatch.setattr(workspace, "_git", fake_git)

    workspace._clone_pinned(source, destination, workspace.UPSTREAM_COMMIT)

    bundle = destination.parent / f".{destination.name}.{workspace.UPSTREAM_COMMIT[:12]}.bundle"
    assert (source.resolve(), ("bundle", "create", str(bundle), "HEAD")) in git_calls
    assert calls[0] == [
        "git",
        "clone",
        "--no-checkout",
        str(bundle),
        str(destination),
    ]
    assert str(source.resolve()) not in calls[0]


def test_clone_bundle_is_removed_even_when_clone_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "workspace" / "repo"
    source.mkdir()
    bundle = destination.parent / f".{destination.name}.{'a' * 12}.bundle"

    def fake_git(path: Path, *args: str):
        if args == ("rev-parse", "HEAD"):
            return "a" * 40
        if args == ("status", "--porcelain"):
            return ""
        if args[:2] == ("bundle", "create"):
            Path(args[2]).write_bytes(b"bundle")
            return ""
        raise AssertionError(args)

    def fake_run(argv, *, label):
        raise workspace.PhotorealExAvatarWorkspaceError("clone failed")

    monkeypatch.setattr(workspace, "_git", fake_git)
    monkeypatch.setattr(workspace, "_run", fake_run)

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="clone failed"):
        workspace._clone_from_local_bundle(
            source,
            destination,
            "a" * 40,
            label="clone repo",
        )

    assert not bundle.exists()


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
    assert "process_bbox(bbox, original_img_width, original_img_height)" in patched
    assert "body/foot keypoints insufficient for frame" in patched
    assert receipt["source_sha256"] == _sha(source)
    assert receipt["patched_sha256"] == _sha(destination)
    assert receipt["replaced_sha256"] is not None


def test_hand4whole_patch_fails_closed_if_upstream_detector_block_drifts(tmp_path: Path) -> None:
    source = tmp_path / "run_hand4whole.py"
    destination = tmp_path / "run_hand4whole-destination.py"
    source.write_text("# changed upstream runner\n", encoding="utf-8")

    with pytest.raises(workspace.PhotorealExAvatarWorkspaceError, match="detector marker changed"):
        workspace._copy_hand4whole_with_pinned_keypoint_bbox(source, destination)


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


def test_clone_pinned_materializes_initialized_local_submodules(tmp_path: Path) -> None:
    glm = tmp_path / "glm-source"
    _init_git_repo(glm)
    (glm / "glm.hpp").write_text("// pinned glm\n", encoding="utf-8")
    _run_git(glm, "add", "glm.hpp")
    _run_git(glm, "commit", "-m", "glm")
    glm_head = _run_git(glm, "rev-parse", "HEAD").lower()

    gaussian = tmp_path / "gaussian-source"
    _init_git_repo(gaussian)
    (gaussian / "setup.py").write_text("# gaussian\n", encoding="utf-8")
    _run_git(gaussian, "add", "setup.py")
    _run_git(gaussian, "commit", "-m", "base")
    subprocess.run(
        [
            "git",
            "-C",
            str(gaussian),
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(glm),
            "third_party/glm",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    _run_git(gaussian, "commit", "-am", "pin glm")
    gaussian_head = _run_git(gaussian, "rev-parse", "HEAD").lower()

    destination = tmp_path / "workspace-gaussian"
    workspace._clone_pinned(gaussian, destination, gaussian_head)

    cloned_glm = destination / "third_party" / "glm"
    assert (cloned_glm / "glm.hpp").read_text(encoding="utf-8") == "// pinned glm\n"
    assert workspace._git(cloned_glm, "rev-parse", "HEAD").lower() == glm_head
    assert workspace._git(destination, "status", "--porcelain") == ""
