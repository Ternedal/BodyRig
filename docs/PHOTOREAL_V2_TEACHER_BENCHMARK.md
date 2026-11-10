# BodyRig Photoreal V2 - teacher benchmark

Status: benchmark decision record. No photoreal, human or production authority.

## Benchmark #1: ExAvatar

The first teacher implementation to reproduce on performer 42 is **ExAvatar** (ECCV 2024), pinned by exact upstream commit when the adapter workspace is materialized.

This is a benchmark choice, not an architecture dependency.

Why it is first:

- it is explicitly designed to create an expressive whole-body avatar from a casual single-person monocular video;
- it combines SMPL-X whole-body control with 3D Gaussian appearance rather than collapsing visual identity into the SMPL-X mesh;
- it models body, face and hands in one representation;
- the public implementation includes a custom-video preprocessing/fitting path;
- the implementation is publicly available under MIT terms;
- it can be evaluated first as a PC teacher, independent of Quest runtime constraints.

Upstream:

- https://github.com/mks0601/ExAvatar_RELEASE
- https://arxiv.org/abs/2407.21686

## Why not make ExAvatar the architecture

ExAvatar still has assumptions that may fail on the BodyRig source universe:

- its documented custom path starts from one coherent single-person video, while Stash contains many asynchronous recordings;
- preprocessing depends on multiple external models and COLMAP/virtual-camera fitting;
- source lighting, hairstyle, clothing and body appearance may vary across recordings;
- the first physical BodyRig target has a 12 GB GPU, so memory/performance must be measured rather than assumed;
- no paper result is evidence that performer 42 will preserve identity under our held-out views.

Therefore the BodyRig contract remains representation-agnostic. ExAvatar receives only an approved coherent appearance epoch and byte-bound training evidence. It cannot decide the epoch, train/evaluation split or acceptance.

## Benchmark #2 controls

If ExAvatar fails static held-out likeness, benchmark the same approved source epoch against at least one independent implementation before changing the acceptance gate.

Current controls:

1. **GaussianAvatar** - animatable 3D Gaussians from a single video, public MIT implementation and custom-video scripts.
2. **HAHA** - hybrid textured SMPL-X mesh plus Gaussians, useful as a control for hair/clothing regions and Gaussian-count efficiency.
3. **RAM-Avatar** - relevant primarily as a later learned/raster runtime direction; do not make P1 depend on it until its release path proves reproducible locally.

Upstreams:

- https://github.com/aipixel/GaussianAvatar
- https://github.com/david-svitov/HAHA
- https://github.com/Xiang-Deng00/RAM-Avatar

## P1 benchmark input

The adapter may only receive data after all of these are true:

1. the complete Stash source universe is inventoried and SHA-256 bound;
2. train/evaluation source groups are disjoint;
3. identity authority is core-derived from source-authoritative or calibrated evidence;
4. cross-split perceptual leakage is clean;
5. required held-out view coverage exists;
6. one coherent appearance epoch has been explicitly human-reviewed and selected.

Evaluation observations are never direct training inputs.

## ExAvatar fitting, spatial camera and pre-train review authority

The ExAvatar custom-video path is now fail-closed at the SMPL-X fitting boundary.

- BodyRig patches both ExAvatar fitting and avatar training to the same explicit `female` / `male` / `neutral` SMPL-X authority. The pinned upstream fitting default of `gender='male'` is never accepted implicitly.
- Scan-authorized spatial video is materialized as exact BodyRig tangent viewports. Every spatial frame carries its matched viewport id, yaw, pitch, horizontal/vertical FOV, derived focal length and principal point.
- Spatial stereo input is reduced to one authoritative eye for an ExAvatar benchmark run. BodyRig does not invent an inter-eye baseline or pretend left/right views share one camera center.
- The spatial virtual-camera stage writes ExAvatar `cam_params` from the BodyRig tangent-camera provenance. It does not use upstream's fixed `focal=[2000,2000]` virtual-camera assumption for deprojected 768x768 VR views.
- After preprocessing, teacher training is blocked until the operator reviews `keypoints_whole_body.mp4`, `smplx_init.mp4`, `smplx_optimized.mp4` and `smplx_optimized_smoothed.mp4`.
- Acceptance creates a hash-bound `smplx-fit-review.json` tied to the workspace, preprocess state, explicit SMPL-X gender, camera mode and exact review-video bytes. Any later drift invalidates the acceptance.
- `-AcceptSmplxFit` and `-RunTeacher` are deliberately mutually exclusive. The expensive teacher stage cannot start in the same invocation that records the human fit decision.

A deliberate `-RebuildWorkspace` archives stale Windows-side ExAvatar derived state, removes an existing Linux workspace only after validating it against its prior provenance, and regenerates the benchmark plan, materialization and isolated workspace. The canonical teacher input and P0 authority are preserved.

## Interrupted ExAvatar teacher resume

The canonical ExAvatar operator is intentionally resumable across an interrupted teacher run. Rerun the same exact operator with `-RunTeacher` and the same teacher input/config/workspace.

BodyRig resumes only when all provenance checks still hold:

- the existing generic teacher `request.json` must be byte-semantically identical to the newly rebuilt canonical request;
- the generic final `output/` path must be absent or an empty legacy directory; adapter artifacts are built in disposable sibling staging and published only after complete manifest/artifact validation;
- a completed `output/teacher-manifest.json` is never resumed and instead goes through strict completed-workspace validation;
- the pinned ExAvatar model directory may contain only non-empty `snapshot_N.pth` files for epochs `0..4`;
- a partial checkpoint set resumes through the pinned upstream `train.py --continue` path, which loads the latest snapshot and continues at the next epoch;
- an existing final `snapshot_4.pth` skips retraining and regenerates the neutral-pose review renders;
- unexpected checkpoint files, out-of-range epochs, empty checkpoints, or neutral-pose output without a final checkpoint fail closed.

This resume path does not rescan Stash, rehash source media, change the approved appearance epoch, disclose held-out evaluation bytes, or grant P1/photoreal/production authority.

## Progress, ETA and the no-output stop

Preprocessing and teacher training run for hours. Every preprocessing stage, `train.py` and the neutral-pose render now run under `bodyrig/photoreal_stage_watch.py`. The adapter carries a byte-identical copy, because it must stay one hash-bound file.

**What it writes**, next to each stage's log in `logs/preprocess/` or `logs/teacher/`:

- `<log stem>.progress.json`, replaced atomically about every 15 s while the stage runs. It records:
  - `state`: `running`, `finished`, `failed`, `stalled` or `stopped`;
  - `completed`/`total` and `percent`;
  - `seconds_per_unit`, measured over the last 15 minutes rather than taken from the upstream running average;
  - `eta_seconds`/`eta_utc`;
  - `seconds_since_output`.
- `stage-timing.jsonl`: one line per stage run, with start, end, elapsed seconds, final state and exit code.

**Where the totals come from:**
- Teacher training: from the upstream line `Epoch e/E itr i/I: speed: …`, so `total = E × I`.
- SMPL-X fit: from `epoch e/E itr_data d/D itr_opt o/O:` and the pinned schedule (500 steps per batch in epoch 0, 250 after). Any other schedule reports the position but no total and no ETA.
- Other stages: no total; only elapsed time and output age.

**Progress in the adapter's own output.** About every 10 minutes the adapter prints a `bodyrig-exavatar-teacher-progress` JSON line with percent, seconds per iteration and ETA. That output is the teacher's `adapter.log` on the Windows side.

**The no-output stop.** A stage that writes nothing for 3600 s is stopped. The control-plane UI already flags 30 minutes without output as `stalled-suspected`; the stop waits twice that.
- Each stage runs in its own session, so the stop terminates its whole process group: DataLoader workers and COLMAP binaries included. It sends SIGTERM, waits up to 30 s, then sends SIGKILL to anything left.
- SIGTERM, SIGHUP or Ctrl+C to the runner stop the stage the same way and record `stopped`.
- What a re-run does after a stop:
  - training resumes from the last snapshot (above);
  - a preprocessing stage starts again at that stage, because completed stages are kept.

**What it does not do.**
- It changes nothing that a stage computes: no training schedule, no resolution, no loss.
- A progress or timing file is diagnostic evidence, never an acceptance authority (`authority: false`).
- It does not limit total run time. The teacher's overall `timeout_seconds` is unchanged.

To read the live state in WSL:

```bash
cat /opt/bodyrig-exavatar/workspaces/<workspace>/logs/teacher/train*.progress.json
tail -n 20 /opt/bodyrig-exavatar/workspaces/<workspace>/logs/*/stage-timing.jsonl
```

## P1 output

The teacher adapter must emit a manifest with exact provenance and a fixed review render set at minimum:

- face front;
- face three-quarter left/right where evidence exists;
- face profile left/right where evidence exists;
- full-body front;
- full-body three-quarter;
- full-body rear where source evidence exists.

Every review render is paired with held-out source evidence selected by BodyRig core, not by the teacher implementation.

For the pinned ExAvatar `get_neutral_pose.py` path, BodyRig also emits `review/neutral-pose/cameras.json`. It binds render indices `0..49` to the exact upstream camera orbit (`azim = pi + 2*pi*i/50`, fixed elevation `-pi/6`) and the pinned upstream commit. The metadata deliberately leaves semantic labels such as front/profile unset.

Before held-out likeness review, run the semantic camera-alignment handoff against strict teacher readback. A human assigns the required `front`, three-quarter, profile and `rear` labels to six unique hash-bound render indices. That receipt grants only semantic camera-alignment authority; it explicitly keeps `human_visual_likeness_acceptance=false`, `photoreal_acceptance_authority=false` and `production_activation=false`. Semantic orientation and likeness acceptance are separate human decisions.

The next P1 handoff binds that semantic teacher receipt to the exact held-out evaluation observations from `teacher-input.json` and the exact-frame appearance review pack. It exposes only selected-epoch evaluation frames whose P0 frame SHA and staged review-PNG SHA are still valid. A human pairs each required P1 coverage criterion with one semantic teacher view and one held-out reference frame. Pairing authority is still not likeness authority: `human_visual_likeness_acceptance=false` remains mandatory until the later comparison review is explicitly completed.

The final P1 review surface copies only those hash-bound teacher/reference bytes into a private side-by-side review pack. The reviewer must record `pass` or `fail` for every required criterion. Any failed criterion records a completed P1 failure and keeps downstream animation blocked. Only an all-PASS receipt sets `p1_static_teacher_acceptance_authority=true`, `human_visual_likeness_acceptance=true` and `p2_animation_authorized=true`. It still keeps the broader `photoreal_acceptance_authority=false` and `production_activation=false`; a static P1 teacher is not a completed animated/runtime digital twin.

## Canonical P1 operator

After the completed ExAvatar teacher, appearance-epoch review pack, semantic camera metadata, and held-out pairing contracts are available on `main`, the canonical human workflow is:

```powershell
.\run-photoreal-v2-p1-review.ps1 `
  -TeacherWorkRoot <TEACHER_WORK_ROOT> `
  -AppearanceReviewRoot <APPEARANCE_REVIEW_ROOT>
```

The operator is deliberately resumable and stops with exit code 2 at each human boundary:

1. **semantic camera alignment** — the human maps the six required semantic orientations to exact neutral teacher render indices;
2. **held-out evidence pairing** — the human pairs every required P1 coverage criterion with one allowed teacher semantic view and one exact held-out reference frame;
3. **likeness review** — the operator materializes the final private side-by-side review pack and the human records `pass` or `fail` for every criterion.

The operator never opens a review automatically and never infers an approval from file existence. Existing semantic and pairing receipts are revalidated by the next strict downstream contract. The final P1 receipt is explicitly revalidated against its canonical review-manifest digest, provenance, criterion universe, PASS/FAIL decisions and authority flags before the operator reports P1 status.

Only an all-PASS final receipt can authorize P2 animation. The operator continues to report the broader `photoreal_acceptance_authority=false` and `production_activation=false`.

Training success, PSNR, SSIM, LPIPS or identity embedding similarity are diagnostics. None of them grants photoreal acceptance.

## P1 hard failure conditions

Any of the following keeps P1 failed:

- obvious mannequin/CG appearance at ordinary viewing distance;
- identity drift in face shape, eyes, mouth, hairline or profile;
- wax/plastic skin caused by baked lighting or missing material response;
- helmet/shell hair or silhouette inconsistent with held-out references;
- collapsed or generic hands;
- missing eye anatomy or generic iris/eyelid appearance;
- unstable geometry/appearance under modest novel view changes;
- evidence that the held-out frame leaked into direct training/projective texture input.

No downstream animation or Quest distillation starts while P1 is failed.

## Hardware policy

The first reproduction runs on the existing PC rig if it fits. The 12 GB GPU is a constraint on implementation scheduling, **not** a reason to lower teacher fidelity.

If the best teacher requires more VRAM, BodyRig records that as a resource blocker and may use CPU offload, lower training batch/resolution for diagnosis, or a stronger training machine later. The accepted teacher quality target is not silently reduced to accommodate the first GPU.

## Quest relationship

ExAvatar/other P1 teachers do not need to run on Quest.

The accepted teacher is the visual truth target. Quest 2/3 students are distilled later and must report their fidelity loss against it.
