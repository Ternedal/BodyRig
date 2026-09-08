# PBR v2 physical A/B review

This runbook prepares a revision-bound visual comparison for the current source-derived skin PBR v2 candidate without granting physical, renderer, release, or production authority.

## What the runner proves

`run-pbr-ab-physical-review.ps1` compares current `main` (LEFT / baseline) with the remote PBR candidate branch (RIGHT / candidate).

Before it builds anything, it requires:

- Windows and PowerShell 7+;
- a clean local `main` checkout;
- local `main` to equal current `origin/main`;
- the candidate branch to resolve to exactly one commit ahead of `main`;
- the candidate diff to contain only the three reviewed PBR-v2 files;
- a verified convergence checkpoint **or** explicit baseline-clone + retained-identity-workspace paths;
- current rig/SiTH setup authority;
- a current `sith-input-v1/reconstruction.json` and `reconstruction-authority.json`.

The runner then:

1. creates a detached worktree for the exact candidate commit;
2. validates the same retained reconstruction under both baseline and candidate code;
3. hashes the entire retained `sith-input-v1` tree;
4. rebuilds a fresh baseline `.mrbody` from the retained reconstruction;
5. proves the retained tree is byte-identical;
6. rebuilds a fresh candidate `.mrbody` from the **same** retained reconstruction;
7. proves the retained tree is byte-identical again;
8. verifies each package's `manifest.builder.revision` against the exact baseline/candidate Git SHA;
9. runs the clean appearance-only machine A/B gate with both expected revisions;
10. renders the same four canonical Windows views for both packages using one common baseline renderer build;
11. rechecks the retained reconstruction bytes and both remote refs;
12. writes a comparison-only `run-authority.json`, `review.html`, and `REVIEW-NEXT.txt`.

A successful runner result still requires human visual review. It does not merge the PBR candidate and it writes no acceptance or production activation.

## Preferred invocation from a retained convergence run

Use the existing fidelity-convergence work root whose latest checkpoint points at the retained reconstruction you want to compare:

```powershell
cd C:\Users\admin\Desktop\BodyRig-git

git fetch origin
git switch main
git pull --ff-only origin main
git status --short

.\run-pbr-ab-physical-review.ps1 `
  -ConvergenceWorkRoot "<path-to-fidelity-convergence-work-root>"
```

The runner verifies the latest checkpoint before using its `current_baseline_clone_output`, `current_identity_workspace`, body alias, and display name.

## Explicit retained-workspace invocation

If the retained reconstruction did not come from a convergence work root:

```powershell
.\run-pbr-ab-physical-review.ps1 `
  -BaselineCloneOutput "<path-to-baseline-clone-output>" `
  -IdentityWorkspace "<path-to-retained-identity-workspace>"
```

`BaselineCloneOutput` is the directory containing `bodyrig-sith-fitter-config.json` and a `clone` subdirectory. `IdentityWorkspace` must contain the completed `sith-input-v1` reconstruction and its current reconstruction authority.

## Candidate branch

The default candidate ref is:

```text
candidate/skin-pbr-v2-current-main-20260908
```

The runner fetches and freezes the exact remote SHA at start, then fetches again before publishing terminal run authority. If either `origin/main` or the candidate ref moves during the run, the run fails closed and no terminal `run-authority.json` is published.

## Output

The default output is under `%LOCALAPPDATA%\BodyRig\pbr-ab\...` and contains:

```text
baseline/<body>.mrbody
candidate/<body>.mrbody
machine-ab.json
baseline-render/
candidate-render/
run-authority.json
review.html
REVIEW-NEXT.txt
```

Open `review.html` to compare LEFT (baseline) and RIGHT (candidate) for:

- front-full;
- three-quarter-full;
- side-full;
- face-front.

## Human decision

After reviewing all four views, use the exact command template written to `REVIEW-NEXT.txt`.

Decisions are:

- `right` — candidate is visibly preferable;
- `left` — baseline is visibly preferable;
- `tie` — no reliable preference;
- `reject-both` — neither is acceptable.

Example only:

```powershell
.\record-fidelity-ab-review.ps1 `
  -AbEvidence "<run>\machine-ab.json" `
  -LeftRenderDir "<run>\baseline-render" `
  -RightRenderDir "<run>\candidate-render" `
  -Decision right `
  -QualityNote "Candidate has more natural skin response without changing geometry; face-front and three-quarter views are clearly better." `
  -ConfirmVisualReview `
  -Output "<run>\human-review.json"
```

The human-review receipt binds:

- exact left/right package SHA-256 values;
- exact left/right builder Git revisions;
- the machine A/B evidence SHA-256;
- one common renderer revision;
- both render-authority hashes;
- both render-set hashes;
- all eight individual canonical snapshot SHA-256 values;
- the operator decision and quality note.

It remains comparison-only and non-activating.

## Interpretation

A `right` decision is evidence that the candidate is preferable for this exact revision-bound appearance A/B. It is **not** automatically a full BodyRig physical PASS. Any subsequent merge/promotion must still respect the canonical physical/render/release gates and must not reinterpret older failed or unrelated human evidence.
