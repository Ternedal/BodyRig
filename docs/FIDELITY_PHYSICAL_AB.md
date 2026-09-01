# BodyRig fidelity physical A/B runbook

This runbook is for the frozen donor-topology / appearance comparison only. It does not authorize merges or production activation.

## Frozen authorities

| Role | Exact authority |
| --- | --- |
| Historical integration renderer | `64aa10bf5b1ad45a1e5ffdd63328b751b33359b9` |
| Historical physically-bad package | SHA-256 `8a8915658201eb8a391a3a2771b2e36bc4fe0e20d293259e015938d5aa6f1897` |
| PR #40 donor topology | `c9dc066ef40f95a6004499a895b22a9cb3ff26c7` |
| PR #41 seam-aware appearance | `b75fe3097702875e81378389d8b93138240ae4fd` |
| Performer | Stash performer `42` / Lauren Phillips |
| #40 body alias/work root | `lauren-phillips-pr40-physical01` |

Do not move #40 or #41 heads during the physical session. Helper tooling is used from a separate detached worktree.

## 1. Create the helper worktree

Replace `HELPER_SHA` with the exact-green PR #49 head recorded in the PR conversation.

```powershell
$main = 'C:\Users\admin\Desktop\BodyRig-git'
$helper = 'C:\Users\admin\Desktop\BodyRig-fidelity-helper'
$helperSha = 'HELPER_SHA'
$python = Join-Path $main '.venv\Scripts\python.exe'

git -C $main fetch origin
if (Test-Path -LiteralPath $helper) { throw "Helper worktree already exists: $helper" }
git -C $main worktree add --detach $helper $helperSha
if ((git -C $helper rev-parse HEAD).Trim() -ne $helperSha) { throw 'Wrong helper head' }
if ((git -C $helper status --porcelain).Count -ne 0) { throw 'Helper checkout is not clean' }
```

## Read-only session status

After the helper worktree exists, this is the preferred entrypoint whenever the physical session is resumed or its state is uncertain:

```powershell
& "$helper\fidelity-physical-session-status.ps1" `
  -MainCheckout $main `
  -BodyRigPython $python
```

The status tool is read-only. It verifies existing checkpoint/handoff authority before advancing and emits only the next allowed action. In particular, an existing #40 work root can never cause it to recommend a second full reconstruction. Invalid, partial or tampered authority is `BLOCKED` rather than guessed around.

## 2. Render the historical bad baseline

The integration checkout passed to this script must be exact-clean `64aa10bf...`. The script locates the old package by exact SHA-256; it refuses substitution.

```powershell
& "$helper\render-known-bad-fidelity-baseline.ps1" `
  -IntegrationCheckout $main `
  -BodyRigPython $python
```

This creates the canonical historical snapshots under:

```text
%LOCALAPPDATA%\BodyRig\fidelity-baselines\integration-64aa-8a891565\snapshots
```

## 3. Run exactly one PR #40 reconstruction

After the historical render, use the frozen #40 command. The key policy is one full rebuild, zero refinements, retained private workspaces:

```powershell
git -C $main fetch origin
git -C $main switch --detach c9dc066ef40f95a6004499a895b22a9cb3ff26c7
if ((git -C $main status --porcelain).Count -ne 0) { throw 'BodyRig checkout is not clean' }
if ((git -C $main rev-parse HEAD).Trim() -ne 'c9dc066ef40f95a6004499a895b22a9cb3ff26c7') { throw 'Wrong #40 head' }

$env:BODYRIG_STASH_PATH_MAP = @{ 'E:\VR' = '\\192.168.1.42\VR_E' } | ConvertTo-Json -Compress
$work = "$env:LOCALAPPDATA\BodyRig\fidelity-convergence\lauren-phillips-pr40-physical01"
if (Test-Path -LiteralPath $work) { throw "WorkRoot already exists: $work (use physical02; do not overwrite evidence)" }

.\run-profiled-fidelity-convergence.ps1 `
  -PerformerId '42' `
  -BodyId 'lauren-phillips-pr40-physical01' `
  -Name 'Lauren Phillips' `
  -WorkRoot $work `
  -MaxFullRebuilds 1 `
  -MaxRefinementsPerRebuild 0 `
  -MaxWallClockHours 8 `
  -KeepPrivateWorkspaces
```

Optional read-only watcher from another PowerShell window:

```powershell
.\watch-fidelity-progress.ps1 -WorkRoot $work -RefreshSeconds 5
```

Do not interact with or terminate the long-running reconstruction console merely because progress appears quiet. If a verified `post-reconstruction` checkpoint exists but the original process has stopped, resume that checkpoint path rather than starting another full reconstruction.

## 4. Human geometry gate before PR #41

Inspect #40 front, 3/4, side and face snapshots. The geometry decision is specifically about:

- closed armholes;
- no membrane/bridge fans;
- stable body surface and silhouette;
- no obvious topology collapse.

Face/skin/hair/appearance quality is **not** approved by this geometry-only decision.

If geometry is bad, stop. Do not spend a PR #41 fit.

If geometry is acceptable, seal the handoff explicitly:

```powershell
& "$helper\invoke-pr40-physical-handoff.ps1" `
  -WorkRoot $work `
  -Mode Seal `
  -ApproveGeometry `
  -BodyRigPython $python
```

The create-only handoff receipt binds the verified #40 checkpoint/artifacts, Gate A acceptance, skin QA, topology QA, current rig setup, retained SiTH reconstruction and reconstruction-authority bytes. It keeps production activation false.

## 5. Verify the handoff immediately before PR #41

```powershell
& "$helper\invoke-pr40-physical-handoff.ps1" `
  -WorkRoot $work `
  -Mode Verify `
  -BodyRigPython $python
```

Any failure means stop. Do not run the #41 fit.

## 6. Run the frozen PR #41 fit-only comparison

Switch the main checkout to exact #41 only after the #40 handoff is verified:

```powershell
git -C $main fetch origin
git -C $main switch --detach b75fe3097702875e81378389d8b93138240ae4fd
if ((git -C $main status --porcelain).Count -ne 0) { throw 'BodyRig checkout is not clean' }
if ((git -C $main rev-parse HEAD).Trim() -ne 'b75fe3097702875e81378389d8b93138240ae4fd') { throw 'Wrong #41 head' }
```

Use the exact clean fit-only command recorded on PR #41. It must reuse #40 proof, visual identity, portable identity and retained `sith-input-v1/reconstruction.json`; it must not add a BodyPrint adjustment or run a second SiTH reconstruction.

Expected #41 output root:

```text
%LOCALAPPDATA%\BodyRig\fidelity-convergence\lauren-phillips-pr40-physical01\pr41-clean-ab
```

## 7. Finalize machine evidence and human review surface

After the #41 package and comparison render exist:

```powershell
& "$helper\finalize-pr40-pr41-review.ps1" `
  -WorkRoot $work `
  -BodyRigPython $python
```

The finalizer:

1. re-verifies the sealed #40 handoff;
2. loads #40 package/render paths from the sealed checkpoint;
3. loads the fixed clean #41 fit-only output;
4. requires identical Body ID, BodyPrint, geometry, skin binding and humanoid rig;
5. requires appearance to actually differ;
6. creates one HTML page with historical bad → #40 → #41 for front, 3/4, side and face.

A clean machine A/B proves only that #41 remained appearance-only. Human review decides whether #41 actually improves face/skin/hair/appearance. No merge or production activation is automatic.
