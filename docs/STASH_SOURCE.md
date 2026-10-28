# Stash as a BodyRig source

BodyRig can use a local Stash library as a first-class clone source.

The intended normal flow is:

```text
Stash performer
    -> matching scenes
    -> ranked Stash files
    -> SHA-256-verified private local source snapshot
    -> sparse observation analysis
    -> 1..10 private high-value segments
    -> BodyRig recovery / BodyPrint
    -> built-in visual identity capture
    -> pinned SiTH reconstruction
    -> SMPL-X skin transfer / canonical unpose
    -> skinned textured VRM 1.0
    -> .mrbody
```

## Trust boundary

Stash is a **source/catalogue layer**, not a BodyRig runtime dependency.

- BodyRig talks to the local Stash GraphQL API.
- `STASH_API_KEY` is used only for the HTTP request header.
- the API key is never written to the source manifest, provenance or `.mrbody`;
- Stash performer metadata is treated as an approved source grouping;
- BodyRig still verifies that returned scenes actually contain the requested performer id;
- recovery/identity track binding remains authoritative for the visual subject;
- source/segment manifests are build-only and may contain local file paths;
- local file paths, adapter configuration, private video segments, extracted identity frames, SiTH intermediate meshes and research-model paths are not `.mrbody` payloads.

BodyRig does not depend on the SkyPlayer Companion process. The adapter deliberately follows the same local GraphQL pattern so SkyPlayer and BodyRig can evolve independently while using the same Stash installation.

## Search performers

Configuration defaults to environment variables:

```powershell
$env:STASH_URL = "http://localhost:9999"
$env:STASH_API_KEY = "<local key if configured>"
```

Search:

```powershell
bodyrig-stash-sources search "Alice"
```

The result includes Stash performer ids. The id is the stable input to source selection.

## Stage 1: rank source files

```powershell
bodyrig-stash-sources select `
  --performer-id 123 `
  --max-sources 10 `
  --out .\bodyrig-stash-source-manifest.json
```

V1 metadata ranking prefers single-performer scenes, higher resolution, useful duration, 24/50+ fps and ordinary flat footage over VR/SBS/OU material. Missing files, wrong-performer results and duplicate local paths are discarded.

The build-only `bodyrig-stash-source-manifest` v1 is defined by `contracts/stash-source-manifest-v1.schema.json`.

## Local source snapshot (before observation/recovery)

A clone run has two phases.

**Phase 1** needs Stash and the media share. It covers the Stash query, ranking, the source manifest, and staging.

Staging copies **all selected originals** into `<OutputDir>/local-source-snapshot/`. For each file:

- The original is read **once** over the share, and it is hashed while it is copied.
- The local copy is hashed again from local disk, and the two SHA-256 values must match.
- A size and mtime check before and after the copy detects an original that changes mid-copy.

Staging then writes a new source manifest that contains only snapshot paths. These cases fail the run before any processing starts, and remove the partial snapshot:

- a missing, duplicate or changed source;
- a size or hash mismatch;
- too little disk space. The run needs the sources plus 5 % or 256 MiB, whichever is larger.

**Phase 2** is offline. Once the wrapper prints `Stash source snapshot complete`, it sets `BODYRIG_STASH_OFFLINE=1` and removes the Stash API key from its own process. From then on, any Stash GraphQL request or Stash image download from BodyRig fails closed, so a step cannot quietly depend on Stash still being up. The wrapper restores both environment variables when it exits.

### Cleanup and recovery

The snapshot is disposable working data. The wrapper deletes it when the clone pipeline exits, on success and on failure, and it never deletes the original files in Stash or on the network share. `-KeepPrivateWorkspace` does not keep the snapshot. The copy of the source manifest kept under `clone/` is an audit artifact, and its snapshot paths stop working once cleanup has run.

A run that is killed outright (power loss, `kill -9`) can leave its snapshot behind. Every run gets a new `OutputDir`, so the leftover sits in a **sibling** run directory. Each run holds `bodyrig-run.lock` in its `OutputDir` open with exclusive sharing for its whole duration. The OS releases the lock if the process dies.

Before staging, the launcher looks through the sibling run directories next to its own `OutputDir`. It removes a `local-source-snapshot/` or `.bodyrig-staging-*` there only if both of these hold:

1. it can take that run's lock, which means the run is no longer alive;
2. the directory carries BodyRig's ownership marker, `.bodyrig-local-source-snapshot`.

A live run's snapshot, an unmarked directory and any other run output are never touched. To clean up a single run directory by hand:

```powershell
python -m bodyrig.stage_stash_sources --cleanup-stale --destination .\bodyrig-stash-<id>-<stamp>\local-source-snapshot
```

To stage an existing manifest independently:

```powershell
python -m bodyrig.stage_stash_sources --manifest .\bodyrig-stash-source-manifest.json --destination .\local-source-snapshot --timing-out .\bodyrig-staging-timing.json
```

### Rig check in minutes: `-StageOnly`

A full clone takes days, so staging is checked on its own:

```powershell
.\clone-body-from-stash.ps1 -PerformerId 123 -ExternalPython "C:\...\recovery\python.exe" -FourDHumansRepo "C:\...\4D-Humans" -BodyId "check" -StageOnly
```

The run does phase 1 for real: the Stash query, ranking, and staging from the real share with SHA-256 verification. It switches to offline mode, writes the timing file, deletes the snapshot and stops. Observation, recovery and fitting are skipped. That is everything this change touches. The processing steps are unchanged apart from where they read their input.

`<OutputDir>/bodyrig-staging-timing.json` holds counts and seconds, never paths:

| Field | Meaning |
| --- | --- |
| `staged` | `true` for a normal run, `false` for a `-DirectSourceBenchmark` run |
| `files`, `bytes` | what was staged |
| `copy_seconds` | the time to read the originals over the share once and write the local copies |
| `verify_seconds` | the time to hash the local copies |
| `processing_seconds` | everything after staging; close to 0 for `-StageOnly` |
| `processing_succeeded`, `stage_only` | how the run ended |

`copy_seconds + verify_seconds` is the whole cost of staging. Compare it with the processing time of a normal clone, from its logs. There is no need for a second full run just to benchmark.

`-DirectSourceBenchmark` runs the old path, processing straight from the share. It is there for a deliberate comparison, but such a comparison needs two full clones, so it is not part of the acceptance check.

### Rollback

The change only adds a phase boundary in front of unchanged processing steps. To go back to the earlier behaviour for a single run, use `-DirectSourceBenchmark`. To roll it back entirely, revert the PR. Existing `.mrbody` outputs are unaffected either way, because the snapshot never ends up in them.

## Stage 2: select actual observations

The normal Stash clone path performs a second, visual selection stage before HMR2/4D-Humans.

The built-in analyzer is `opencv-hog-haar` v1 and runs out-of-process in the existing recovery Python environment. It samples each ranked file sparsely rather than processing every frame with the heavy recovery model.

It scores candidate windows from:

- person detector confidence;
- target/person screen fraction;
- frontal/profile face visibility;
- full-body framing/clipping;
- Laplacian sharpness;
- person-box occlusion;
- inter-sample motion.

The lightweight built-in analyzer is deliberately conservative: it only performs automatic target selection for Stash scenes tagged with exactly one performer. Multi-performer footage remains available to future identity-aware analyzers but the simple analyzer will not silently guess which person is the named performer.

BodyRig core — not the external analyzer — chooses the final observations. It rejects bad ranges/unknown sources/non-finite metrics, applies a minimum quality threshold, avoids strongly overlapping windows and limits domination by one scene. The final set is fail-closed for high-fidelity coverage: it must contain at least one face-strong observation (`face_visibility >= 0.72`) and at least one full-body-strong observation (`full_body_visibility >= 0.72`); missing mandatory coverage outranks ordinary source/view diversity during greedy selection.

Selected windows are re-encoded by FFmpeg as 1..10 private H.264 MP4 segments. The segment manifest records a SHA-256 for every clip. `clone-body.ps1` re-hashes every segment before recovery, so a clip cannot be replaced between selection and cloning.

Artifacts:

```text
bodyrig-observation-selection.json   # redacted metrics/evidence; no source paths
bodyrig-observation-segments.json    # build-only paths + segment SHA-256
<private workspace>/selected-segments/segment-01.mp4 ...
```

The private observation workspace is deleted after success or failure by default.

## Stage 3: built-in visual identity capture

The normal Stash path does not require a hand-written identity-capture config.

If `-IdentityCaptureConfig` is omitted, the wrapper uses `opencv-identity-rgba` v1. Before Stash discovery it fail-closes unless the external recovery Python can provide:

- OpenCV/cv2;
- NumPy;
- HOG people detection;
- frontal/profile Haar cascades;
- GrabCut.

The adapter operates on the exact source set used by recovery — normally the already selected, hash-verified private segments. It sparsely samples them and only accepts candidate frames where one person is detected, the body framing is useful and a face is visible.

The best candidate is written only inside the private identity workspace as:

```text
identity-capture/
  primary-rgb.png
  primary-rgba.png
  capture.json
```

`primary-rgba.png` uses a source-derived GrabCut alpha mask and is build-time input to the default high-fidelity SiTH path. `capture.json` binds the private image hashes, source index and source timestamp.

The only capture artifact accepted back into BodyRig core is the strict metadata-only `bodyrig-visual-identity` profile. It contains observation counts/coverage/quality and the recovery subject track id, but no source path, image, embedding or biometric template.

A custom capture adapter remains available through `-IdentityCaptureConfig <config.json>`. Direct use of `clone-body.ps1` remains generic and still requires an explicit identity-capture config; the automatic default is a Stash operator policy, not a weakened core contract.

## Stage 4: built-in high-fidelity SiTH fitter

If `-FitterConfig` is omitted, the Stash wrapper now uses the built-in `sith-smplx-vrm` v1 adapter.

The adapter keeps the research stack outside BodyRig core. It performs, in the private identity workspace:

1. hash-bound staging of the captured RGBA frame;
2. the pinned SiTH `centralize_rgba.py` step;
3. OpenPose BODY_25 + hands + face with exactly one person;
4. pinned SiTH SMPL-X fitting;
5. offline, fixed-seed SiTH back-view generation;
6. UV textured mesh reconstruction;
7. numerical re-creation of the fitted SMPL-X body from the saved fit parameters;
8. SMPL-X skin-weight transfer to the reconstructed mesh;
9. inverse skinning from the source pose to the shape/rest pose;
10. VRM 1.0 humanoid mapping and skinned textured avatar export.

Before BodyRig even queries Stash, the wrapper runs the pinned SiTH preflight and computes a deterministic byte-bound digest of the local diffusion-model tree. A revision, dependency, asset or model-digest mismatch therefore fails early rather than after a long clone job.

The built-in fitter derives the SMPL-X model directory from the pinned SiTH checkout itself (`<SiTH repo>/data/body_models/smplx`). There is deliberately no separate operator-selectable SMPL-X path, because SiTH fitting and BodyRig rig transfer must use the same licensed assets.

The heavy adapter may return only:

```text
avatar.vrm
thumbnail.png
result.json
```

BodyRig core independently checks the returned hashes and validates VRM 1.0 before building `.mrbody`. SiTH checkpoints, SMPL-X files, source frames and intermediate meshes are never copied into the portable package.

A custom high-fidelity adapter remains available through `-FitterConfig <config.json>`. Direct use of `clone-body.ps1` also remains generic and still requires an explicit fitter config.

### One-time SiTH settings

The built-in fitter needs the local WSL research environment to be configured once. Values can be passed as wrapper parameters, but the normal machine-level setup is environment variables:

```powershell
$env:BODYRIG_SITH_DISTRIBUTION = "Ubuntu-22.04"
$env:BODYRIG_SITH_REPO = "/opt/sith"
$env:BODYRIG_SITH_PYTHON = "/opt/sith/.venv/bin/python"
$env:BODYRIG_SITH_OPENPOSE = "/opt/openpose/build/examples/openpose/openpose.bin"
$env:BODYRIG_SITH_DIFFUSION_MODEL = "/opt/models/sith-diffusion"
$env:BODYRIG_SITH_DIFFUSION_SHA256 = "<64-char model-tree sha256>"
```

`BODYRIG_SITH_DISTRIBUTION` defaults to `Ubuntu-22.04` if omitted. The other values are required when the built-in fitter is selected. The diffusion SHA is the output of `bodyrig-sith-model-digest` for the exact local model directory.

The equivalent wrapper parameters are:

- `-SithDistribution`
- `-SithRepo`
- `-SithPython`
- `-SithOpenPose`
- `-SithDiffusionModel`
- `-SithDiffusionModelSha256`
- optional `-SithSeed` (default `1337`)
- optional `-WslExe` (default `wsl.exe`)

## One-command wrapper

After the one-time Stash and SiTH environment settings are in place, the normal operator path is:

```powershell
.\clone-body-from-stash.ps1 `
  -PerformerId 123 `
  -ExternalPython "C:\...\recovery\python.exe" `
  -FourDHumansRepo "C:\...\4D-Humans" `
  -BodyId "alice"
```

`-Name` is optional. If omitted, the Stash performer name becomes the BodyRig display name.

By default the wrapper:

1. preflights the built-in identity-capture environment;
2. preflights the pinned SiTH/WSL/OpenPose environment;
3. re-digests and verifies the local SiTH diffusion model;
4. queries Stash;
5. ranks local source files;
6. creates the Stash source manifest;
7. copies all selected originals to a private local snapshot (one read each, SHA-256 verified), switches to the local manifest and goes offline (`BODYRIG_STASH_OFFLINE=1`, API key removed);
8. runs the built-in lightweight observation analyzer;
9. selects/diversifies the best visual windows;
10. materializes hash-bound private segments with FFmpeg;
11. feeds those segments into the existing recovery pipeline;
12. captures a private RGB/RGBA identity frame and strict visual-identity profile;
13. runs the pinned offline SiTH reconstruction and SMPL-X rig transfer;
14. validates the returned VRM 1.0 and builds `.mrbody`;
15. deletes the temporary local Stash source snapshot when the clone pipeline exits (success or failure);
16. deletes private observation/identity workspaces unless `-KeepPrivateWorkspace` was explicitly supplied.

Use `-SkipObservationSelection` only when you explicitly want the previous whole-file behavior.

A custom observation analyzer can be supplied with `-ObservationAnalyzerConfig`, a custom identity capture adapter with `-IdentityCaptureConfig`, and a custom high-fidelity fitter with `-FitterConfig`. All stay behind strict out-of-process contracts.

## Manual observation selection CLI

The visual stage can also be run independently:

```powershell
bodyrig-select-observations .\bodyrig-stash-source-manifest.json `
  --config .\observation-analyzer.json `
  --workspace "$env:LOCALAPPDATA\BodyRig\observation-workspaces\test" `
  --selection-out .\bodyrig-observation-selection.json `
  --segments-out .\bodyrig-observation-segments.json `
  --max-segments 10
```

Relevant contracts:

- `contracts/observation-analyzer-config-v1.schema.json`
- `contracts/observation-selection-v1.schema.json`
- `contracts/observation-segments-v1.schema.json`
- `contracts/identity-capture-config-v1.schema.json`
- `contracts/visual-identity-v1.schema.json`
- `contracts/external-fitter-config-v1.schema.json`

## Schema compatibility

Current Stash uses `SceneFilterType.performers` with a `MultiCriterionInput`. BodyRig tries that query first.

For older Stash installations, the adapter has an explicit fallback to the older `scene_filter.performer_id` form. Both paths still verify the requested performer id in every returned scene before accepting a file.

## Remaining physical proof

The built-in high-fidelity path is now wired end-to-end in code, but it is not considered production-proven until the real rig passes the existing physical gates:

- real local Stash/video input through recovery and the SiTH fitter;
- source-derived visual-quality inspection;
- the same `.mrbody` in a built WindowsPlayer;
- the same `.mrbody` in a Quest-class Android build;
- final `complete-acceptance.ps1` over the exact package and machine evidence.

The adapter remains fail-closed while those physical gates are outstanding. The `-StageOnly` rig check above has not been run yet.
