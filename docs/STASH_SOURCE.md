# Stash as a BodyRig source

BodyRig can use a local Stash library as a first-class clone source.

The intended normal flow is:

```text
Stash performer
    -> matching scenes
    -> ranked local files
    -> sparse observation analysis
    -> 1..10 private high-value segments
    -> BodyRig recovery / BodyPrint
    -> visual identity capture
    -> high-fidelity fitter
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
- local file paths, analyzer configuration and private video segments are not copied into `.mrbody`.

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

## Stage 2: select actual observations

The normal Stash clone path now performs a second, visual selection stage before HMR2/4D-Humans.

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

BodyRig core — not the external analyzer — chooses the final observations. It rejects bad ranges/unknown sources/non-finite metrics, applies a minimum quality threshold, avoids strongly overlapping windows, limits domination by one scene and rewards different sources/views plus face-strong and body-strong observations.

Selected windows are re-encoded by FFmpeg as 1..10 private H.264 MP4 segments. The segment manifest records a SHA-256 for every clip. `clone-body.ps1` re-hashes every segment before recovery, so a clip cannot be replaced between selection and cloning.

Artifacts:

```text
bodyrig-observation-selection.json   # redacted metrics/evidence; no source paths
bodyrig-observation-segments.json    # build-only paths + segment SHA-256
<private workspace>/selected-segments/segment-01.mp4 ...
```

The private observation workspace is deleted after success or failure by default.

## One-command wrapper

The normal operator path remains one command:

```powershell
.\clone-body-from-stash.ps1 `
  -PerformerId 123 `
  -ExternalPython "C:\...\recovery\python.exe" `
  -FourDHumansRepo "C:\...\4D-Humans" `
  -IdentityCaptureConfig .\identity-capture.json `
  -FitterConfig .\fitter.json `
  -BodyId "alice"
```

`-Name` is optional. If omitted, the Stash performer name becomes the BodyRig display name.

By default the wrapper:

1. queries Stash;
2. ranks local source files;
3. creates the Stash source manifest;
4. runs the built-in lightweight observation analyzer;
5. selects/diversifies the best visual windows;
6. materializes hash-bound private segments with FFmpeg;
7. feeds those segments into the existing `clone-body.ps1` recovery/capture/fitter pipeline;
8. deletes private observation segments unless `-KeepPrivateWorkspace` was explicitly supplied.

Use `-SkipObservationSelection` only when you explicitly want the previous whole-file behavior.

A custom analyzer can be supplied with `-ObservationAnalyzerConfig`. Its strict config format is `bodyrig-observation-analyzer-config` v1. External analyzers receive source paths only as process arguments; paths are absent from the JSON analyzer request and selection evidence.

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

Contracts:

- `contracts/observation-analyzer-config-v1.schema.json`
- `contracts/observation-selection-v1.schema.json`
- `contracts/observation-segments-v1.schema.json`

## Schema compatibility

Current Stash uses `SceneFilterType.performers` with a `MultiCriterionInput`. BodyRig tries that query first.

For older Stash installations, the adapter has an explicit fallback to the older `scene_filter.performer_id` form. Both paths still verify the requested performer id in every returned scene before accepting a file.

## Next quality improvements

The generic observation boundary is intentionally engine-neutral. Later analyzers can add stronger identity-aware multi-person selection, better front/rear orientation estimation and learned face/body quality while preserving the same source, segment and clone contracts.
