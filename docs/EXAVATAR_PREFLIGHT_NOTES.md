# ExAvatar read-only preflight — operator handoff

This document is on an isolated branch; V1 `main` remains frozen.

## What can be tested now

The existing `bodyrig.photoreal_exavatar_fit_diagnostic` module supports a bounded, read-only sample and an all-frame audit. It records per-frame projection metrics, anatomical evidence, review categories, and a diverse validation panel. These are diagnostic heuristics **only**. They never authorize teacher training, photoreal acceptance, or production.

### Step 1 — verify the code without a rig

From the repository root in a Python environment with pytest:

```powershell
python -m pytest tests/test_photoreal_exavatar_projection_audit.py -q
```

Do not interpret a passing synthetic test as physical camera validation.

### Step 2 — bounded physical diagnostic (no training)

From WSL Ubuntu-22.04, with the checkout available under the Windows mount, run from the repository root (adjust path to the actual checkout):

```bash
python3 -m bodyrig.photoreal_exavatar_fit_diagnostic \
  --dataset /opt/bodyrig-exavatar/workspaces/bodyrig-42-camera-v2-20261008/dataset/bodyrig-42 \
  --optimized-only \
  --output /tmp/bodyrig-exavatar-fit-audit.json
```

The default checks representative frames. The diagnostic exits nonzero if there are frame errors. The output is a JSON file containing private dataset paths; inspect before sharing.

### Step 3 — only after bounded diagnostic works

Add `--all-frames` to the same command to audit all indexed frames. This is read-only but can be CPU-intensive on a large dataset. Review the `validation_panel` and `priority_review_frames` sections of the JSON with matching source frames.

## Stop/go

**NO-GO** for spatial VR teacher training while camera coordinate conventions or held-out human visual fit are unvalidated. A high 2D projected bounding-box overlap is not proof of accurate 3D geometry. Any unreadable frame, suspicious transform, or anatomical gap requires manual review. No automatic promotion, dataset rewrite, checkpoint change, or GPU training belongs in this procedure.
