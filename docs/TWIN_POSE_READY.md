# POSE_READY: body motion from a staged ExAvatar workspace (#1398 slice 1a)

The ExAvatar preprocess already estimates SMPL-X parameters for every training frame. `bodyrig.twin_pose` turns those recorded outputs into a body motion that Blender can import. It adds no new model, detector or download.

Each statement is tagged with its basis:
- **[repo]** this repository's code;
- **[upstream]** ExAvatar at the pinned commit;
- **[measure]** something only a rig run can establish.

**Nothing here has been run on the rig.** The tests use a fake skeleton and fake parameters. They are not physical ExAvatar proof.

## 1. What it produces

The tool writes three files to a private output directory. The directory is mode 0700, and each file is written atomically through a temporary file and a rename.

| File | Content |
|---|---|
| `motion.bvh` | The 22-joint SMPL-X body skeleton, with one BVH frame per valid sample |
| `motion.json` | The same motion with each sample's real timestamp, its validity and its BVH frame number |
| `digital_twin_manifest.json` | `state: "POSE_READY"` and `mesh: "unavailable"`, plus provenance, coordinate system, timings and artifact hashes |

There are two motion sources. With `--source auto`, the smoothed source is used if it is available, otherwise init.

| Source | Preprocess stage | Ready | Root translation |
|---|---|---|---|
| `init` | `hand4whole-smplx-init` | early: after camera, keypoints and DECA | **none**. Hand4Whole does not estimate one, so every sample stands at the origin [upstream: `run_hand4whole.py` writes no `trans`] |
| `smoothed` | `smplx-smooth` | after the full fit | estimated [upstream: `fit.py` writes `trans`] |

## 2. What it refuses rather than infers

- **A workspace that fails any integrity check:**
  - its receipt digest;
  - its preprocess state (format, workspace binding, digest);
  - a recorded output whose bytes no longer match the state [repo: the same check preprocessing uses on resume].
- **A parameter or camera file the state did not record,** or one that changed after it was recorded. Each file is read once, hashed and parsed from the same bytes.
- **A missing or wrong consent record.** It must be bound to this exact workspace (see §4).
- **Symlinks on the read side:** a symlink anywhere on a read path. Every input goes through one reader, once:
  - the workspace root and its receipt;
  - the preprocess state;
  - the consent record;
  - the materialization receipt;
  - every parameter and camera file;
  - the SMPL-X model.
- **Symlinks on the write side:**
  - a symlinked output directory or parent;
  - an output name that already exists as a symlink. Its target is left untouched.
- **An input over its size cap,** checked by the bytes actually read, not only by `fstat`:
  - 1 MiB for each parameter or camera file;
  - 64 MiB for `preprocess-state.json` (#1409). The state records one output per frame for eight of the nine stages, about 3 KB per frame, so 64 MiB holds about 20,000 frames;
  - 16 MiB for the workspace receipt;
  - 64 MiB for the materialization receipt;
  - 2 GiB for the model.
- **The COLMAP camera mode.** A COLMAP world has no fixed up axis, so slice 1a supports only `virtual`.
- **A stereo set that mixes eyes.**

## 3. Coordinate system, joint map and timing

- **Output frame** [repo]:
  - right-handed: +X right, +Y up, −Z forward, in metres;
  - this is BodyRig's own source frame, with the origin at the source's front camera;
  - ExAvatar's world is +X right, +Y down, +Z forward, so the conversion rotates 180° about X.
- **Root:**
  - rotation is `C · Rᵀ_cam · R_root`, where C = diag(1, −1, −1);
  - position is `C · Rᵀ_cam · (pelvis_rest + trans − t_cam)`.
  - An upright subject facing the camera comes out upright, facing +Z (towards the viewer).
- **Joints:** the 21 body joints keep their SMPL-X local rotations, relative to the rest skeleton. They need no conversion.
- **Joint map:** fixed to SMPL-X body joints 0–21 with their parent table. A model whose kinematic tree differs is refused.
  - `motion.bvh` declares the joints depth-first from the pelvis, and its channels follow that order. `motion.json` lists it as `bvh_joint_order`.
  - Each BVH joint has `Zrotation Xrotation Yrotation` channels. The root adds `Xposition Yposition Zposition`, and its OFFSET is zero.
- **Rest skeleton:** taken from the SMPL-X **neutral template with zero shape**.
  - So bone lengths carry nothing of the subject.
  - Only `v_template`, `J_regressor` and `kintree_table` are read from the `.npz`, with `allow_pickle=False`.
  - Because the template pelvis stands in for the subject's own, the root position has an error of a few centimetres **[measure]**.
- **Timing:**
  - The samples are training frames chosen across a clip, not consecutive video frames.
  - BVH needs one fixed frame time, so it holds one frame per valid sample at a nominal 30 fps.
  - `motion.json` has the real `timestamp_seconds` of every sample, in timestamp order.
  - The timestamps and the eye come from `materialization-receipt.json`, which the workspace build copied into the dataset. Its SHA-256 is bound in the digest-checked workspace receipt.
  - `bodyrig-source-map.json` holds the same frames but is bound to nothing, so it is not read.
- **Invalid samples** stay in `motion.json` with `valid: false`, an `invalid_reason` and `bvh_frame: null`. They are left out of `motion.bvh`. The possible reasons are:
  - `unreadable_parameters`
  - `malformed_pose`
  - `malformed_translation`
  - `invalid_camera`
  - `pose_keypoint_mismatch` (§5)

  If no sample is valid, the run is refused.

## 4. Consent

`record-consent` writes a `bodyrig-twin-subject-consent` record and never overwrites one.

- **Binding:** the record is bound to the workspace's `workspace_sha256`, and its own digest detects any later edit.
- **What it states:**
  - the subject is the operator (`self`), or an adult who consented (`consenting-adult`);
  - the subject is an adult. This is required, and there is no way to record otherwise;
  - the scope `pose-motion-local`.
- **Evidence:** a `consenting-adult` record also needs the SHA-256 of the consent document the operator keeps. The document itself stays with the operator.

**The record is the operator's statement.** The tool cannot verify consent. It verifies only that consent was recorded for this exact workspace and has not been changed since.

## 5. What never reaches an output

The following are never written, and the tests check this:
- body shape, expression, jaw, eye and hand parameters;
- source frames, source keys and source names;
- the performer id, subject id and gender;
- the workspace path.

Stage timings carry only stage, state and elapsed seconds. The manifest also states:
- `likeness_authority: false`
- `identity_claim: false`
- `cloud_transfer: false`
- `modelrig_transfer: false`

**Multiple people:** the ExAvatar outputs keep one person per frame and record no others [upstream: mmpose keeps the highest-scoring person, Hand4Whole the largest box]. A general multi-person detector is therefore not possible from these outputs. What can be caught is the case where the two stages picked different people (#1398 slice 1d, the keypoint gate):

- **How it works:** for the `smoothed` source, forward kinematics on the rest skeleton places the body joints in camera space. They are projected with the recorded camera and compared with the recorded 2D whole-body keypoints for shoulders, elbows, wrists, knees and ankles. Only keypoints with a score of at least 0.3 are used.
- **What it reports:** `keypoint_agreement` in `motion.json`, which is the median pixel error divided by the diagonal of the confident 2D body keypoints.
  - **Above 0.25:** the sample is rejected as `pose_keypoint_mismatch`.
  - **Fewer than four confident pairs:** the sample is left unchecked rather than rejected.
- **Where it does not apply:** the `init` source has no root translation, so it is not checked. `keypoint_gate` in the manifest says whether the gate ran, why it did not, and how many samples were checked, unchecked and rejected.
- **Accuracy:** the skeleton is the template, not the subject's shape, so a correct fit still shows a small error. The 0.25 threshold is a starting value, **[measure]** on the rig.
- **Privacy:** the keypoint file is read only as an output the preprocess state recorded, and no keypoint is written to any output.

## 6. The downstream consumer

The isolated scene inspector (`bodyrig.scene_inspector`) now accepts `.bvh`:

- **Before Blender:** its header probe reports the joint count, frame count and frame time [repo, tested].
- **In Blender:** the worker imports the file with Blender's bundled BVH importer (`io_anim_bvh`, `import_anim.bvh`) and reports the armature.
  - **[repo, tested with real Blender]** With the pinned `bpy` 4.5.15 (`requirements/blender-bpy.lock.txt`), the import gives one armature with 22 bones, `pelvis` as the root, and an action. The test is `tests/test_scene_inspector_blender.py::test_a_pose_ready_bvh_imports_as_one_22_bone_armature`, and it runs in the `blender-e2e` CI jobs.
  - **[measure]** Whether the rig uses the same Blender build is still unverified. If the importer is missing there, the inspector fails closed.
- **Conditioning (#1398 slice 1c):** with `--conditioning openpose`, the inspector draws an OpenPose sequence from the motion. It frames the motion on its bones, because there is no mesh, and maps the SMPL-X body joints by a fixed table.
  - **[repo, tested with real Blender]** `test_a_pose_ready_motion_becomes_an_openpose_sequence` checks that a three-frame motion gives three OpenPose JSON/PNG pairs, each with 14 body keypoints, facing the camera. A bent left elbow raises the left wrist keypoint.
  - **Not available:** depth and normal, which need a mesh.
  - **Not done here:** feeding these images to ModelRig. That is the default-off #2296 hand-off, a separate decision.

## 7. Running it on the rig (WSL, the ExAvatar runtime)

```bash
cd <BodyRig checkout in WSL>
W=/opt/bodyrig-exavatar/workspaces/<workspace>
PYTHONPATH=$PWD PYTHONNOUSERSITE=1 /opt/bodyrig-exavatar/bin/python -m bodyrig.twin_pose_cli record-consent \
  --workspace-root "$W" --relation self --subject-is-adult --out "$W/twin-subject-consent.json"
PYTHONPATH=$PWD PYTHONNOUSERSITE=1 /opt/bodyrig-exavatar/bin/python -m bodyrig.twin_pose_cli pose \
  --workspace-root "$W" --consent "$W/twin-subject-consent.json" \
  --smplx-model <asset root in WSL>/human_model_files/smplx/SMPLX_NEUTRAL.npz --out "$W/twin-pose"
```

- **`--smplx-model`** must be the real file in the asset root. The workspace's linked copy is a symlink, and the tool refuses it.
- **Exit codes:**
  - 0: written;
  - 2: not ready yet, because the stage it needs has not completed;
  - 1: refused, with the reason in the printed JSON.
- **Time to first pose [measure]:** this is the wall-clock time from the start of preprocess to the first `motion.bvh` from the `init` source. The manifest carries the recorded stage timings, so it shows where the time went.

## 8. Not in slice 1a

The following come in slice 1b, after measurement:
- mesh and GLB export;
- a rendered preview;
- Stash ingest;
- the COLMAP camera mode;
- hands and face;
- any new pose backend (SAM-3D-Body is a candidate).

Nothing is sent to ModelRig or the cloud. Feeding the motion into generation is a separate decision.
