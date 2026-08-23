# Stash as a BodyRig source

BodyRig can use a local Stash library as a first-class clone source.

The intended normal flow is:

```text
Stash performer
    -> matching scenes
    -> ranked local files
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
- later recovery/identity track binding remains authoritative for the visual subject;
- the Stash source manifest is build-only and may contain local file paths;
- local file paths are not copied into `.mrbody`.

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

## Select clone sources

```powershell
bodyrig-stash-sources select `
  --performer-id 123 `
  --max-sources 10 `
  --out .\bodyrig-stash-source-manifest.json
```

BodyRig queries Stash scenes for that performer and evaluates local `files.path` entries.

V1 ranking prefers:

1. a scene where the requested performer is the only tagged performer;
2. higher spatial resolution;
3. useful video duration;
4. normal 24+ fps footage, with a smaller preference for 50/60 fps;
5. ordinary flat footage over explicitly tagged VR/SBS/OU material.

Multi-performer and VR material is not forbidden. It is deliberately ranked lower because it creates more ambiguity/distortion for automatic identity and body recovery.

Missing local files and duplicate paths are discarded. A source path returned by Stash is never trusted without a local file existence check.

## Source manifest

The build-only manifest is `bodyrig-stash-source-manifest` v1 and has a JSON Schema in `contracts/stash-source-manifest-v1.schema.json`.

It includes:

- Stash performer id/name;
- Stash version;
- number of scene candidates inspected;
- the selected 1..10 local paths;
- scene id/title and ranking metadata.

It does **not** include:

- Stash URL;
- Stash API key;
- request headers;
- raw GraphQL responses.

## Feed the normal clone pipeline

`clone-body.ps1` accepts either ordinary `-Source` clips or one `-SourceManifest`:

```powershell
.\clone-body.ps1 `
  -SourceManifest .\bodyrig-stash-source-manifest.json `
  -ExternalPython "C:\...\python.exe" `
  -FourDHumansRepo "C:\...\4D-Humans" `
  -IdentityCaptureConfig .\identity-capture.json `
  -FitterConfig .\fitter.json `
  -BodyId "alice" `
  -Name "Alice"
```

This is the same recovery/capture/fitting pipeline used for manually supplied files.

## One-command wrapper

The normal Stash operator path is:

```powershell
.\clone-body-from-stash.ps1 `
  -PerformerId 123 `
  -ExternalPython "C:\...\python.exe" `
  -FourDHumansRepo "C:\...\4D-Humans" `
  -IdentityCaptureConfig .\identity-capture.json `
  -FitterConfig .\fitter.json `
  -BodyId "alice"
```

`-Name` is optional. If omitted, the Stash performer name becomes the BodyRig display name.

The wrapper:

1. queries Stash;
2. ranks the local source files;
3. writes the source manifest;
4. displays the selected scene scores;
5. starts the existing `clone-body.ps1` in a separate PowerShell process;
6. preserves the source manifest as non-portable build evidence beside the clone output.

## Schema compatibility

Current Stash uses `SceneFilterType.performers` with a `MultiCriterionInput`. BodyRig tries that query first.

For older Stash installations, the adapter has an explicit fallback to the older `scene_filter.performer_id` form. Both paths still verify the requested performer id in every returned scene before accepting a file.

## Next quality slice

Metadata ranking is intentionally only the first filter. The next Stash-specific improvement should sample the ranked files before recovery and score actual visual coverage:

- face visibility/sharpness;
- full-body visibility;
- front/side/rear coverage;
- target-person screen size;
- occlusion;
- motion blur;
- duplicate/near-duplicate shots.

That stage should reduce large Stash libraries to the smallest set of clips/segments that maximizes BodyRig identity/body coverage instead of simply feeding ten long videos into every research model.
