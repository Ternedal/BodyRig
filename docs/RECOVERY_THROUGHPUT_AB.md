# Recovery throughput physical A/B

This procedure validates the recovery-only PHALP temporal-sampling candidate before it may be considered for BodyRig physical authority.

The candidate is a performance change, not a quality or release authority. CI alone cannot promote it.

## Required runs

Two **succeeded** Person Studio `body-build` jobs for the same person are required:

1. **Baseline** — uncapped recovery from exact Person Studio authority `76c64a9546238663dedf750a1da4a230cc1e7fa4` on `agent/person-studio-photoreal-20260902`.
2. **Candidate** — recovery-only sampling from the exact clean HEAD being reviewed on `agent/recovery-throughput-v2-20260903`.

The failed 2026-09-02 job `job-8a5bece5df0f4707a1186b53e01eb4db` is useful diagnostic evidence, but it is not an A/B baseline because it never reached succeeded body/Gate-A/fidelity-review state.

Do not start the candidate until the baseline has succeeded. If the baseline fails, diagnose/fix the baseline first; do not use the performance candidate to hide a functional failure.

## Software authority and safe switching

The canonical comparator binds the baseline job to exact BodyRig revision `76c64a9546238663dedf750a1da4a230cc1e7fa4`. It also reads the current clean candidate checkout with `git rev-parse HEAD` and requires the candidate job's persisted `bodyrig_revision` to equal that exact SHA. A dirty comparator checkout is refused.

### 1. Put the rig on the uncapped baseline authority

From the BodyRig checkout:

```powershell
.\update-windows.ps1 `
  -Branch "agent/person-studio-photoreal-20260902"
```

The updater must finish `BodyRig update: READY`, and the printed revision must be exactly:

```text
76c64a9546238663dedf750a1da4a230cc1e7fa4
```

If the remote Person Studio branch has moved to another revision, stop. PR #58 must be rebuilt/revalidated on that new base before an A/B run is accepted.

#### Preferred baseline runner

The baseline checkout intentionally does not contain performance-candidate tooling. Bootstrap the reviewed baseline runner into `%TEMP%` without changing the checked-out baseline revision:

```powershell
$repo = (Get-Location).Path
$branch = "agent/recovery-throughput-v2-20260903"
$tmp = Join-Path $env:TEMP "bodyrig-run-recovery-throughput-baseline.ps1"

git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}"
if ($LASTEXITCODE -ne 0) { throw "Could not fetch BodyRig A/B tooling." }

git show "origin/${branch}:run-recovery-throughput-baseline.ps1" |
    Set-Content -LiteralPath $tmp -Encoding utf8

& "C:\Program Files\PowerShell\7\pwsh.exe" `
    -NoProfile `
    -ExecutionPolicy Bypass `
    -File $tmp `
    -PersonId "person-<32 hex>" `
    -RepoRoot $repo
```

The runner is fail-closed before the build POST. It verifies:

- disk checkout HEAD is exact `76c64a9546238663dedf750a1da4a230cc1e7fa4` and clean;
- `%LOCALAPPDATA%\BodyRig\ui-service.json` points to the same checkout and exact revision and its PID is alive;
- BodyRig physical readiness is green;
- Stash health + performer-read is green;
- the requested Person has a Stash performer binding;
- no body-build is already queued/running for that Person.

It then starts **only** `/body/build`, verifies the returned job is persisted with exact baseline `bodyrig_revision`, and follows the canonical `watch-body-build.ps1` monitor until terminal state. It exits 0 only for `succeeded` and prints the persisted diagnostic tail on failure.

`-NoWatch` may be used to return after a safely-started job; it does not skip any pre-start authority/readiness gate and it does not stop the physical job.

Record the succeeded baseline body-job id.

### 2. Switch to the sampled candidate

Only after the baseline body job has succeeded:

```powershell
.\update-windows.ps1 `
  -Branch "agent/recovery-throughput-v2-20260903"
```

Record the exact `Revision:` printed by the updater. That exact SHA is the candidate software authority for this physical run. Do not make commits, edit files, or otherwise dirty/move the checkout between the candidate body build and the machine A/B audit.

Use the candidate runner:

```powershell
.\run-recovery-throughput-candidate.ps1 `
  -PersonId "person-<32 hex>"
```

The candidate runner verifies the current clean Git HEAD, verifies the running service state points to that exact HEAD, requires `RECOVERY_TEMPORAL_SAMPLING_REVISION == 15fps-v1`, rechecks BodyRig/Stash/person/active-job gates, starts only the body build, and requires the persisted job `bodyrig_revision` to equal the exact candidate HEAD. It follows the canonical body monitor and exits 0 only for `succeeded`.

### 3. Audit before restoring the rig

Run the machine A/B gate **while the rig checkout is still on the exact candidate revision that produced the candidate job**. The comparator refuses a candidate job whose persisted `bodyrig_revision` differs from current clean checkout HEAD.

### 4. Build the hash-bound human review bundle

Only after the machine A/B gate passes, build a create-only side-by-side review bundle from the exact succeeded baseline and candidate jobs:

```powershell
.\build-recovery-throughput-review-bundle.ps1 `
  -BaselineJobId "job-<baseline>" `
  -CandidateJobId "job-<candidate>"
```

The wrapper requires the same clean candidate checkout used by the machine audit. It re-runs the canonical machine gate before copying any review bytes. If the machine gate is blocked, no bundle is created.

The default output is under `%LOCALAPPDATA%\BodyRig\recovery-throughput-reviews\<baseline>--<candidate>` (or the equivalent `BODYRIG_DATA_DIR`). The bundle contains:

- `index.html` with baseline/candidate side-by-side for all four canonical views;
- `baseline/*.png` and `candidate/*.png` copied only after their persisted SHA-256 values are revalidated;
- `machine-audit.json` containing the exact machine comparison;
- `review-bundle.json` containing a hash manifest for every copied/generated file.

`review-bundle.json` is deliberately non-authoritative. It always states:

```text
human_visual_review_required = true
promotion_authority = false
production_activation = false
```

The bundle is only an immutable review aid. It does not record an approval, cannot activate a body/person, and cannot promote PR #58.

### 5. Record the explicit human visual review

After inspecting `index.html`, record the human result as a separate create-only receipt outside the immutable bundle:

```powershell
.\record-recovery-throughput-human-review.ps1 `
  -BundleDir "<review-bundle-directory>" `
  -IdentityShape pass `
  -FaceIdentity pass `
  -SkinTextureAlignment pass `
  -GrossAnatomy pass `
  -Note "No material visual regression across all four canonical views."
```

Each criterion must be explicitly `pass` or `fail`; the note is mandatory. The recorder verifies the immutable bundle and its machine A/B PASS again before writing anything. The default receipt is a sibling named `<review-bundle-directory>.human-review.json`, so recording the human decision cannot mutate the hash-manifested bundle.

The receipt binds the exact `review-bundle.json` and `machine-audit.json` SHA-256 values plus every reviewed baseline/candidate view hash. One failed criterion produces:

```text
decision = material-regression
next_gate = blocked-material-regression
```

All four passing criteria produce only:

```text
decision = no-material-regression
next_gate = eligible-for-explicit-promotion-review
```

Even then the receipt always keeps:

```text
promotion_authority = false
production_activation = false
```

It is structured human evidence, not an authority mutation.

### 6. Always restore canonical Person Studio authority

After machine/human evidence has been captured — whether the experiment passes or fails — restore the rig:

```powershell
.\update-windows.ps1 `
  -Branch "agent/person-studio-photoreal-20260902"
```

The restored revision must again be `76c64a9546238663dedf750a1da4a230cc1e7fa4`. Do not leave normal BodyRig runtime on the performance-candidate branch.

## Baseline invariants

Before recording the baseline job id:

- `job.bodyrig_revision` must equal exact uncapped authority `76c64a9546238663dedf750a1da4a230cc1e7fa4`.
- Stash performer/source authority must be healthy.
- The body build must finish `succeeded`.
- Recovery proof, source binding, Gate A, fidelity output and persisted four-view review must all exist.
- Do not manually edit job/evidence files.

The recovery-resume cache may reduce the cost of repeating an interrupted baseline, but only checkpoints valid for the exact uncapped recovery revision are reusable.

## Candidate invariants

The candidate changes only PHALP temporal input density. It must not rewrite or spatially downscale the selected native observation MP4 segments used by identity capture/high-fidelity fitting.

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

Candidate recovery checkpoints/cache are versioned independently from uncapped baseline evidence. An uncapped raw PHALP result must never be accepted as sampled-candidate evidence.

## Machine A/B gate

### Preferred: fail-closed auto-discovery

After both jobs succeed, and before restoring Person Studio authority, run from the exact candidate checkout with the Person Studio person id:

```powershell
.\compare-recovery-throughput-auto.ps1 `
  -PersonId "person-<32 hex>"
```

The auto-discovery wrapper is read-only unless `-Out` is explicitly supplied to the underlying comparator. It:

- considers only `succeeded` `body-build` jobs for the requested person;
- reads the persisted recovery proof for classification;
- selects the **newest** sampled candidate for that person;
- derives that candidate's exact uncapped parent recovery revision;
- selects the **newest** succeeded baseline with that exact parent revision;
- does not search backwards for an older candidate merely because the newest candidate would fail the evidence gate;
- delegates to the canonical comparator, which binds baseline software to `76c64a9546238663dedf750a1da4a230cc1e7fa4`, binds candidate software to current clean checkout HEAD, and then revalidates source authority, observation selection, native segment bytes, recovery identity, Gate A and persisted review evidence.

If no exact parent baseline exists, if software authority differs, or if the newest candidate and selected baseline do not share the required evidence, the A/B gate is blocked. Do not manually substitute an older passing pair to hide newer regression evidence.

### Explicit job ids

For forensic/reproducibility work, or when an exact pair has already been recorded, call the canonical wrapper directly from the same exact clean candidate checkout:

```powershell
.\compare-recovery-throughput.ps1 `
  -BaselineJobId "job-<baseline>" `
  -CandidateJobId "job-<candidate>"
```

The wrappers resolve the same BodyRig data authority as the application (`BODYRIG_DATA_DIR`, otherwise `%LOCALAPPDATA%\BodyRig`). `-Out` is create-only and refuses overwrite.

The audit must block unless all of these are true:

- baseline `job.bodyrig_revision` is exact uncapped Person Studio authority `76c64a9546238663dedf750a1da4a230cc1e7fa4`
- candidate `job.bodyrig_revision` equals exact current clean comparator checkout HEAD
- same `person_id`
- same Stash performer authority
- same exact source-file SHA evidence
- same observation analyzer adapter/revision
- same exact selected observation windows and quality evidence
- same native observation segment identities and SHA-256 bytes
- candidate recovery revision is exactly baseline revision plus `;s:15fps-v1`
- same recovery adapter
- same selected recovery track
- candidate has fewer `observed_frames`
- each run independently revalidates source binding, recovery proof, visual identity binding, Gate A, fidelity output and persisted review

A machine PASS means only:

```text
decision = eligible-for-human-ab-review
promotion_authority = false
production_activation = false
human_visual_review_required = true
```

## Human visual A/B gate

Open the generated review bundle `index.html` and compare the baseline/candidate canonical review views:

- `front-full`
- `three-quarter-full`
- `side-full`
- `face-front`

Review identity-bearing shape, face, skin/texture alignment and gross anatomy. A speed improvement is not acceptable if there is a material visual regression or track/identity instability.

The machine audit reports identity/bodyprint numeric deltas as comparison evidence; those metrics do not replace human visual review. The hash-bound bundle proves which rendered bytes were compared, and the separate human-review receipt records the explicit result without granting authority.

## Promotion rule

The candidate may be proposed for physical authority only when:

1. baseline succeeded on exact uncapped software authority;
2. candidate succeeded on the exact clean candidate software authority audited by the comparator;
3. machine A/B gate passed;
4. the hash-bound human review bundle was generated from that exact passing pair;
5. candidate materially reduced recovery work/wall-clock time;
6. a create-only human review receipt is bound to that exact bundle and records `no-material-regression` across all four explicit criteria;
7. the rig was restored to canonical Person Studio authority after evidence capture;
8. the resulting authority change is explicitly reviewed and landed separately.

Never merge PR #58 or move PR #1/physical authority solely because CI is green or because the candidate is faster.
