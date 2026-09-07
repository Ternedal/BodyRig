# Recovery throughput physical A/B — revision-bound candidate

This runbook is for the recovery-only PHALP temporal-sampling candidate. It is a performance experiment, not production or physical authority. CI, lower frame count, or faster runtime can never promote it by themselves.

## Required evidence

Use two **succeeded** `body-build` jobs for the same Person and exact source authority:

1. **Baseline** — an uncapped run from one exact clean BodyRig revision.
2. **Candidate** — a sampled run from the exact clean candidate revision being reviewed.

The selected native observation MP4 bytes, Stash performer/source-file SHA evidence, observation windows, and recovery track must match. The candidate is allowed to reduce only PHALP/HMR2 temporal work; identity capture and high-fidelity fitting continue to consume the native observation bytes.

Do not start a candidate run merely to hide or bypass a failing baseline. The baseline must succeed first.

## 1. Record the exact baseline authority

On the baseline checkout, before starting the baseline body build:

```powershell
git status --short
git rev-parse HEAD
```

`git status --short` must be empty. Record the exact 40-character revision as `<baseline-bodyrig-revision>`.

Drive the normal source-bound physical path with `bodyrig-status.ps1` until the baseline `body-build` job succeeds and has its normal Gate A, fidelity, and persisted body-review evidence. Record its `job-...` id as `<baseline-job>`.

## 2. Run the exact candidate

Switch/update to the exact candidate revision under review and verify again:

```powershell
git status --short
git rev-parse HEAD
```

Do not edit tracked files after the candidate job starts. Run the same Person/source path and record the succeeded candidate job id as `<candidate-job>`.

## 3. Run the machine A/B gate

From the exact clean candidate checkout:

```powershell
.\compare-recovery-throughput.ps1 `
  -BaselineJobId '<baseline-job>' `
  -CandidateJobId '<candidate-job>' `
  -BaselineBodyRigRevision '<baseline-bodyrig-revision>' `
  -Out '<create-only-audit.json>'
```

The gate fails closed unless the explicit baseline revision matches the baseline job and the candidate job matches the exact current clean checkout HEAD. It also requires matching Person/source authority, native observation bytes, observation selection, recovery adapter/track, package/Gate-A/fidelity/review evidence, the exact versioned sampling derivative, and an actual recovery frame reduction.

A machine PASS means only `eligible-for-human-ab-review`. It never grants promotion or production authority.

## 4. Build the immutable visual review bundle

After machine PASS:

```powershell
.\build-recovery-throughput-review-bundle.ps1 `
  -BaselineJobId '<baseline-job>' `
  -CandidateJobId '<candidate-job>' `
  -BaselineBodyRigRevision '<baseline-bodyrig-revision>'
```

The wrapper re-runs the machine gate before copying any review bytes. The bundle contains the canonical baseline/candidate views, `machine-audit.json`, `index.html`, and a SHA-256 manifest. Existing output is never overwritten.

Inspect `index.html` as a human comparison. Machine metrics do not substitute for this judgement.

## 5. Record explicit human PASS/FAIL

Record all four review axes explicitly:

```powershell
.\record-recovery-throughput-human-review.ps1 `
  -BundleDir '<review-bundle-dir>' `
  -IdentityShape pass `
  -FaceIdentity pass `
  -SkinTextureAlignment pass `
  -GrossAnatomy pass `
  -Note 'No material visual regression across the reviewed canonical views.'
```

Use `fail` for any criterion that regressed. The human receipt is stored outside the immutable bundle and is create-only. A failed criterion produces `blocked-material-regression`.

Even when all four criteria pass, the receipt only yields `eligible-for-explicit-promotion-review` and always keeps:

```text
promotion_authority = false
production_activation = false
```

## 6. Promotion remains a separate decision

Do not merge or activate the candidate merely because:

- CI is green;
- recovery used fewer frames;
- wall-clock time improved;
- machine A/B passed; or
- the human receipt says `no-material-regression`.

Those results create evidence for an explicit later promotion decision. Existing historical physical evidence remains bound to the exact revisions and bytes that created it.
