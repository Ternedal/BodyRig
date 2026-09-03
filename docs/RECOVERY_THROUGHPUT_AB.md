# Recovery throughput physical A/B

This procedure validates the recovery-only PHALP temporal-sampling candidate before it may be considered for BodyRig physical authority.

The candidate is a performance change, not a quality or release authority. CI alone cannot promote it.

## Required runs

Two **succeeded** Person Studio `body-build` jobs for the same person are required:

1. **Baseline** — uncapped recovery from `agent/person-studio-photoreal-20260902`.
2. **Candidate** — recovery-only sampling from `agent/recovery-throughput-v2-20260903`.

The failed 2026-09-02 job `job-8a5bece5df0f4707a1186b53e01eb4db` is useful diagnostic evidence, but it is not an A/B baseline because it never reached succeeded body/Gate-A/fidelity-review state.

Do not start the candidate until the baseline has succeeded. If the baseline fails, diagnose/fix the baseline first; do not use the performance candidate to hide a functional failure.

## Baseline invariants

Before recording the baseline job id:

- BodyRig must report the exact intended Person Studio checkout revision.
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

After both jobs succeed, run from the candidate checkout with the Person Studio person id:

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
- passes the selected ids to the canonical fail-closed auditor, which then revalidates source authority, observation selection, native segment bytes, recovery identity, Gate A and persisted review evidence.

If no exact parent baseline exists, or if the newest candidate and selected baseline do not share the required evidence, the A/B gate is blocked. Do not manually substitute an older passing pair to hide newer regression evidence.

### Explicit job ids

For forensic/reproducibility work, or when an exact pair has already been recorded, call the canonical wrapper directly:

```powershell
.\compare-recovery-throughput.ps1 `
  -BaselineJobId "job-<baseline>" `
  -CandidateJobId "job-<candidate>"
```

The wrappers resolve the same BodyRig data authority as the application (`BODYRIG_DATA_DIR`, otherwise `%LOCALAPPDATA%\BodyRig`). `-Out` is create-only and refuses overwrite.

The audit must block unless all of these are true:

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

Compare the persisted canonical review views from baseline and candidate:

- `front-full`
- `three-quarter-full`
- `side-full`
- `face-front`

Review identity-bearing shape, face, skin/texture alignment and gross anatomy. A speed improvement is not acceptable if there is a material visual regression or track/identity instability.

The machine audit reports identity/bodyprint numeric deltas as comparison evidence; those metrics do not replace human visual review.

## Promotion rule

The candidate may be proposed for physical authority only when:

1. baseline succeeded;
2. candidate succeeded;
3. machine A/B gate passed;
4. candidate materially reduced recovery work/wall-clock time;
5. human visual A/B review found no material regression;
6. the resulting authority change is explicitly reviewed and landed separately.

Never merge PR #58 or move PR #1/physical authority solely because CI is green or because the candidate is faster.
