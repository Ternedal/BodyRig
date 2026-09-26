# ExAvatar Scene-Scale Diagnostic

This note documents the diagnostic-only workflow for the first-iteration non-finite
scene Gaussian gradient observed in ExAvatar teacher training.

This workflow is intentionally isolated from production activation. It performs no
optimizer step, writes no teacher checkpoint, and never mutates the original pinned
Gaussian rasterizer.

## Preconditions

Use the diagnostic branch only:

`diag/exavatar-final-symlink-containment-runner`

The PowerShell operators fail closed unless:

- the current branch is exactly the diagnostic branch;
- the working tree is clean;
- local HEAD exactly matches `origin/diag/exavatar-final-symlink-containment-runner`;
- the diagnostic branch descends from `origin/main`.

The workspace must already contain the validated finite SMPL-X identity and completed
ExAvatar preprocessing.

## Preferred one-command workflow

From the BodyRig repository root:

```powershell
.\run-photoreal-exavatar-scene-scale-ab.ps1 `
  -LinuxWorkspaceRoot '/opt/bodyrig-exavatar/workspaces/bodyrig-42-1d2f658e0fa9'
```

The operator runs one deterministic baseline iteration. It executes the rasterizer
A/B build and patched iteration only when the baseline classification implicates the
rasterizer backward path.

The workflow never calls `optimizer.step()`, never densifies/prunes Gaussians, and
never writes a teacher checkpoint.

## Baseline evidence

The baseline report is written atomically to:

`diagnostics/scene-scale-ab/baseline.json`

It records:

- exact subject, seed, first-frame identity and camera mode;
- background point-cloud SHA-256;
- ExAvatar patched source SHA-256 values;
- scene mean/log-scale tensor SHA-256 values;
- forward scene-render tensor SHA-256 values;
- finite/range health for scene mean, physical scale, rotation, opacity and renders;
- rasterizer extension origin and SHA-256;
- per-loss gradient reports for `rgb_scene` and `ssim_scene`;
- gradients for render output, scene mean, log scale, physical scale input, rotation
  and opacity;
- combined backward status;
- concrete bad Gaussian rows plus geometry/radius/scale evidence when scale gradients
  are non-finite.

## Forward classification

`forward_interpretation` is one of:

- `finite`
- `forward-scene-parameter-nonfinite`
- `forward-render-nonfinite`

A non-finite forward classification stops the conditional A/B before any candidate
CUDA patch is built.

## Backward classification

Per-loss classifications can include:

- `finite`
- `loss-to-render-gradient-nonfinite`
- `physical-scale-rasterizer-backward-nonfinite`
- `broad-rasterizer-backward-nonfinite`
- `log-scale-chain-nonfinite`
- `non-scale-scene-gradient-nonfinite`
- `backward-error`

The conditional A/B is eligible only for the physical-scale or broad rasterizer
backward classifications.

## Rasterizer A/B candidate

When eligible, BodyRig prepares an isolated copy of the pinned rasterizer:

- source commit: `03f0b7d00383d6e96c22b37325ac9e5450947bf5`
- source tree: `74064838bc2383b187fc68693bc95f5df68309a6`
- destination:
  `diagnostics/rasterizer-conic-offdiag-fix`

The candidate applies exactly the documented Graphdeco off-diagonal conic-gradient
correction:

```diff
- atomicAdd(&dL_dconic2D[global_id].y, -0.5f * gdx * d.y * dL_dG);
+ atomicAdd(&dL_dconic2D[global_id].y, -1.0f * gdx * d.y * dL_dG);
```

Reference: Graphdeco `diff-gaussian-rasterization`, issue 94,
"Incorrect Gradient for Off-Diagonal Conic Term in Backward Pass".

The builder verifies the pinned commit/tree, rejects source modifications, builds in a
staging directory, verifies the imported extension origin/hash, and only then atomically
publishes the diagnostic candidate.

## A/B comparability gate

The patched result is accepted for comparison only when baseline and patched reports
match on:

- format/version/subject;
- RNG seed and `cur_itr`;
- exact first-batch frame index;
- camera mode;
- scene point count;
- scene mean/log-scale tensor SHA-256;
- forward scene-render SHA-256 values;
- forward scene parameter/render health reports;
- background point-cloud SHA-256;
- patched ExAvatar source SHA-256 values;
- forward loss values and non-finite-loss set.

The baseline and patched rasterizer extension SHA-256 values must differ.

If any of these invariants drift, the comparison fails closed.

## Outputs

The structured comparison is written to:

`diagnostics/scene-scale-ab/comparison.json`

Possible high-level outcomes include:

- `baseline-forward-nonfinite`
- `baseline-did-not-implicate-rasterizer`
- `candidate-fix-eliminated-observed-rasterizer-nonfinite`
- `candidate-fix-reduced-observed-rasterizer-nonfinite`
- `candidate-fix-did-not-change-observed-rasterizer-nonfinite-count`
- `candidate-fix-changed-observation-without-eliminating-nonfinite`

No A/B outcome grants photoreal acceptance or production activation. A successful
single-iteration candidate is evidence for the next controlled validation step, not
automatic production approval.
