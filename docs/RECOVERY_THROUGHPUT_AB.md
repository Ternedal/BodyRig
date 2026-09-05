# Recovery throughput physical A/B — v3

This runbook validates the recovery-only PHALP temporal-sampling candidate in PR #60. The candidate is a performance experiment, not production or physical authority. CI or speed alone can never promote it.

## Exact software authorities

Two **succeeded** Person Studio `body-build` jobs for the same person are required:

1. **Baseline** — uncapped recovery on exact Person Studio revision `0b8f61b6f369e0d63ed006d808e316798121f79f` from `agent/person-studio-photoreal-20260902`.
2. **Candidate** — sampled recovery from the exact clean HEAD of `agent/recovery-throughput-v3-20260903`.

The failed historical job `job-8a5bece5df0f4707a1186b53e01eb4db` is useful diagnostic evidence, but it is not an A/B baseline because it never reached succeeded body/Gate-A/fidelity-review state.

The physical build already running on `0b8f61b6f369e0d63ed006d808e316798121f79f` may be used as the baseline **if and only if it succeeds** and all evidence required by the comparator remains authoritative. Do not start the candidate until the baseline has succeeded.

The comparator is fail-closed: baseline `job.bodyrig_revision` must be the exact baseline SHA, candidate `job.bodyrig_revision` must equal the current clean comparator checkout HEAD, and a dirty comparator checkout is refused. The candidate cannot be used to hide a baseline functional failure.

## Baseline run

The canonical baseline runner is `run-recovery-throughput-baseline.ps1`. When starting a fresh baseline it verifies exact checkout authority with `git rev-parse HEAD`, clean Git state, the running BodyRig service root/revision/PID, physical readiness, Stash health/performer-read, Person Stash binding, and absence of another queued/running body build. It starts **only** `/body/build` and follows the canonical `watch-body-build.ps1` monitor.

The runner is pinned to:

```text
0b8f61b6f369e0d63ed006d808e316798121f79f
```

For the baseline already running manually through Person Studio, do not touch the rig. If it succeeds, record its exact job id and use that existing job as the baseline. There is no reason to start a second uncapped run.

`-NoWatch` may be used when intentionally starting a future baseline to return after a safely-started job; it does not skip any pre-start authority/readiness gate and it does not stop the physical job.

## Candidate run

Only after a valid baseline has succeeded, switch with the normal updater:

```powershell
.\update-windows.ps1 -Branch "agent/recovery-throughput-v3-20260903"
```

Record the exact `Revision:` printed by the updater. Do not edit files or move the checkout after the candidate job starts.

Start the sampled candidate with:

```powershell
.\run-recovery-throughput-candidate.ps1 -PersonId "person-<32 hex>"
```

The candidate runner rejects the uncapped baseline revision, requires a clean exact candidate HEAD, proves the running service is on that same HEAD, requires `RECOVERY_TEMPORAL_SAMPLING_REVISION == 15fps-v1`, checks BodyRig/Stash/person/active-job gates, starts only the body build, and verifies the persisted job revision.

## Candidate invariant: identity bytes stay native

The candidate changes only PHALP/HMR2 temporal input density. It **must not rewrite or spatially downscale** the selected native observation MP4 segments used by identity capture and high-fidelity fitting.

Sampling policy:

```text
stride = ceil(source_fps / 15)
effective_fps = source_fps / stride
```

Examples:

```text
10 fps    -> stride 1 -> 10 fps
15 fps    -> stride 1 -> 15 fps
25 fps    -> stride 2 -> 12.5 fps
29.97 fps -> stride 2 -> 14.985 fps
30 fps    -> stride 2 -> 15 fps
60 fps    -> stride 4 -> 15 fps
```

Sampled recovery checkpoints/cache are versioned independently from uncapped evidence. An uncapped PHALP result must never be accepted as sampled-candidate evidence.

## Machine A/B gate

After both jobs succeed, and while the rig is still on the exact candidate checkout, use fail-closed auto-discovery:

```powershell
.\compare-recovery-throughput-auto.ps1 -PersonId "person-<32 hex>"
```

For an exact recorded pair:

```powershell
.\compare-recovery-throughput.ps1 `
  -BaselineJobId "job-<baseline>" `
  -CandidateJobId "job-<candidate>"
```

The machine gate blocks unless all of these hold:

- baseline `job.bodyrig_revision` is exact `0b8f61b6f369e0d63ed006d808e316798121f79f`;
- candidate revision equals current clean comparator checkout HEAD;
- same `person_id` and Stash performer authority;
- same exact source-file SHA evidence;
- same observation analyzer adapter/revision;
- same exact selected observation windows and quality evidence;
- same native observation segment identities and SHA-256 bytes;
- candidate recovery revision is exactly the baseline recovery revision plus `;s:15fps-v1`;
- same recovery adapter and same selected recovery track;
- candidate has fewer `observed_frames`;
- source binding, recovery proof, visual identity, Gate A, fidelity output and persisted review independently validate for both jobs.

A machine PASS means only:

```text
decision = eligible-for-human-ab-review
human_visual_review_required = true
promotion_authority = false
production_activation = false
```

## Hash-bound human review

Only after the machine A/B gate passes, build the create-only review bundle:

```powershell
.\build-recovery-throughput-review-bundle.ps1 `
  -BaselineJobId "job-<baseline>" `
  -CandidateJobId "job-<candidate>"
```

If the machine gate is blocked, no bundle is created. The bundle contains `index.html`, verified baseline/candidate PNG bytes, `machine-audit.json`, and `review-bundle.json`; persisted SHA-256 values are revalidated before copying. It is an immutable review aid and does not record an approval.

Review the exact canonical views:

- `front-full`
- `three-quarter-full`
- `side-full`
- `face-front`

Record the decision as a separate create-only receipt outside the immutable bundle:

```powershell
.\record-recovery-throughput-human-review.ps1 `
  -BundleDir "<review-bundle-directory>" `
  -IdentityShape pass `
  -FaceIdentity pass `
  -SkinTextureAlignment pass `
  -GrossAnatomy pass `
  -Note "No material visual regression across all four canonical views."
```

Each criterion must be explicitly `pass` or `fail`; the note is mandatory. The receipt binds the exact `review-bundle.json` and `machine-audit.json` SHA-256 values plus every reviewed view hash. Recording the receipt cannot mutate the hash-manifested bundle.

One failed criterion yields `blocked-material-regression`. All four passing criteria yield only `eligible-for-explicit-promotion-review`. This is structured human evidence, not an authority mutation; the receipt still states `promotion_authority = false` and `production_activation = false`.

## Restore and promotion boundary

After the experiment, regardless of result, restore canonical Person Studio runtime:

```powershell
.\update-windows.ps1 -Branch "agent/person-studio-photoreal-20260902"
```

Do not leave normal BodyRig runtime on the performance-candidate branch.

PR #60 may be proposed for physical authority only after the exact baseline succeeds, the exact candidate succeeds, machine A/B passes, the hash-bound four-view bundle is reviewed, the candidate materially reduces recovery work/wall-clock time, the human receipt records `no-material-regression`, the rig is restored, and the authority change is explicitly reviewed separately.

Never merge PR #60 or move physical authority solely because CI is green or because the candidate is faster.
