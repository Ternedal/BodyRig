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

## Interrupted ExAvatar teacher resume

The canonical ExAvatar operator is intentionally resumable across an interrupted teacher run. Rerun the same exact operator with `-RunTeacher` and the same teacher input/config/workspace.

BodyRig resumes only when all provenance checks still hold:

- the existing generic teacher `request.json` must be byte-semantically identical to the newly rebuilt canonical request;
- the generic `output/` directory must still be empty and contain no ambiguous partial teacher artifacts;
- a completed `output/teacher-manifest.json` is never resumed and instead goes through strict completed-workspace validation;
- the pinned ExAvatar model directory may contain only non-empty `snapshot_N.pth` files for epochs `0..4`;
- a partial checkpoint set resumes through the pinned upstream `train.py --continue` path, which loads the latest snapshot and continues at the next epoch;
- an existing final `snapshot_4.pth` skips retraining and regenerates the neutral-pose review renders;
- unexpected checkpoint files, out-of-range epochs, empty checkpoints, or neutral-pose output without a final checkpoint fail closed.

This resume path does not rescan Stash, rehash source media, change the approved appearance epoch, disclose held-out evaluation bytes, or grant P1/photoreal/production authority.

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
