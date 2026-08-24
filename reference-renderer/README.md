# BodyRig Unity reference renderer

This is the thin physical-acceptance client for proving that a completed BodyRig `.mrbody` can be materialized and loaded by a normal Unity/UniVRM runtime without HMR2, PHALP, SMPL-X or Python dependencies in the renderer.

It is intentionally **not** the final Kaliv or immersive Quest UI. Its narrow job is to prove the same accepted Gate A runtime bytes in a built WindowsPlayer and on Quest-class Android hardware, with deterministic deformation evidence and a separate human quality attestation.

## Reproducible project authority

`reference-renderer/` is a directly openable Unity project, but production physical evidence is created through the root reference wrappers rather than by manually opening the project or hand-running player binaries.

Pinned contract:

- Unity **6000.3.13f1**;
- UniVRM semantic version **0.131.2**;
- UniVRM exact Git revision **`a4711bbf8c4d10659d3e5568c2e3d7d595005e51`**;
- `com.vrmc.gltf` from `/Packages/UniGLTF` at that exact revision;
- `com.vrmc.vrm` from `/Packages/VRM10` at that exact revision;
- `com.unity.mathematics` **1.2.6**;
- `com.unity.test-framework` **1.4.6**;
- `com.unity.timeline` **1.7.6**;
- VRM 1.0 only: `canLoadVrm0X: false`;
- application id `dk.ternedal.bodyrig.reference`;
- deformation sequence `humanoid-muscle-sweep-v1`.

`renderer-contract.json` is the single renderer identity/version authority. `Packages/manifest.json` and `Packages/bodyrig-univrm-manifest.snippet.json` are exact dependency declarations and are contract-tested to remain identical.

The Git URLs use the concrete UniVRM commit, not the movable `v0.131.2` tag. The semantic version remains useful for humans; the 40-character revision is the build authority.

## Read-only toolchain readiness

Before the first physical BodyRig session, the root doctor invokes:

```powershell
.\check-reference-renderer-ready.ps1
```

It does **not** open Unity and creates no physical evidence. It fails closed unless the target Windows rig has:

- PowerShell 7+;
- the exact Unity `6000.3.13f1` editor;
- Android Build Support for that editor;
- the bundled Android SDK, NDK and OpenJDK;
- the bundled `adb.exe`;
- Git for Unity Package Manager Git dependencies;
- the exact renderer contract/project version and pinned package manifest.

`prepare-first-physical-run.ps1` runs this check before the recovery/SiTH/Stash readiness gate, so missing Unity/Quest build tooling is found before a real clone session is created.

## Gate A runtime is the only renderer input

The renderer must **not** be pointed at an arbitrary loose `.vrm`. Gate A leaves a validated materialized runtime similar to:

```text
C:\acceptance\
  bodyrig-acceptance.json
  bodyid-....mrbody
  bodyrig-physical-clone-session.json
  bodyrig-rig-readiness.json
  bodyrig-skin-qa.json
  runtime\
    runtime-manifest.json
    avatar.vrm
    bodyprint.json
    provenance.json
    ...
```

The player starts from `runtime-manifest.json`. `BodyRigAvatarLoader` verifies the fixed payload names and package identity, loads only the manifest-selected `avatar.vrm`, disables VRM 0.x migration, and requires a valid Unity Humanoid plus all BodyRig-required bones before the active runtime identity changes.

## Ephemeral Unity build boundary

`build-reference-renderer.ps1` never opens the tracked `reference-renderer/` source project for a production build. It copies only `Assets/`, `Packages/` and `ProjectSettings/` into a temporary project and invokes Unity there.

That separation is intentional. Unity may generate `Packages/packages-lock.json`, default ProjectSettings, `.meta` files, Library state and other editor-owned files on first import. None of those are allowed to mutate the exact accepted BodyRig checkout.

After Unity resolves packages, the build wrapper validates the generated `Packages/packages-lock.json` in the temporary project. Both UniVRM packages must resolve to exact Git hash `a4711bbf8c4d10659d3e5568c2e3d7d595005e51`, and the contracted Unity registry dependencies must resolve to their pinned versions. A missing or mismatched lock makes the build fail.

The temporary project is removed after the attempt. The real BodyRig Git HEAD and checkout cleanliness are revalidated after the build.

Default diagnostic build outputs remain:

```text
reference-renderer\Builds\Windows\BodyRigReferenceProbe.exe
reference-renderer\Builds\Quest\BodyRigReferenceProbe.apk
```

The canonical probe wrappers remove the previous platform build directory before invoking a fresh build, so production evidence cannot silently reuse an older player/APK.

## Canonical Windows physical gate

From the BodyRig repository root, after Gate A:

```powershell
.\run-reference-windows-renderer-probe.ps1 `
  -AcceptanceDir "C:\path\to\acceptance"
```

This is the production entrypoint. It does **not** expose `-SkipBuild` or renderer identity overrides.

The wrapper:

1. reads the exact renderer contract;
2. creates a fresh Windows build from the exact clean Gate A BodyRig revision;
3. runs the built `WindowsPlayer`, never the Unity Editor;
4. rejects a non-zero player exit even if JSON was written first;
5. validates machine + deformation evidence against Gate A, build revision/GUID, Unity version, renderer identity and `humanoid-muscle-sweep-v1`;
6. commits the pair transactionally into `windows-evidence/` only after all checks pass.

A failed or crashed attempt does not become canonical evidence.

After visually reviewing the complete deformation loop:

```powershell
.\record-reference-renderer-acceptance.ps1 `
  -AcceptanceDir "C:\path\to\acceptance" `
  -Platform "windows-unity-univrm" `
  -ConfirmQualityChecklist `
  -QualityNote "<concrete physical quality review>"
```

## Canonical Quest physical gate

After Windows evidence + human review:

```powershell
.\run-reference-quest-renderer-probe.ps1 `
  -AcceptanceDir "C:\path\to\acceptance"
```

Optionally pass `-Serial` when multiple ADB devices are attached.

The canonical wrapper always builds a fresh ARM64 Development APK, installs it with ADB, clears the app's staged runtime/evidence area, pushes the exact Gate A runtime, starts `dk.ternedal.bodyrig.reference`, waits for both evidence files, pulls them into a temporary local staging directory and validates them before atomically committing `quest-evidence/`.

Both the connected device and the machine/deformation evidence must identify Quest/Oculus hardware. A generic Android phone cannot satisfy this gate.

After reviewing the deformation loop in the headset:

```powershell
.\record-reference-renderer-acceptance.ps1 `
  -AcceptanceDir "C:\path\to\acceptance" `
  -Platform "android-quest-class" `
  -ConfirmQualityChecklist `
  -QualityNote "<concrete physical quality review>"
```

## Diagnostic wrappers are not production authority

The lower-level wrappers remain useful for troubleshooting:

- `run-windows-renderer-probe.ps1`
- `run-quest-renderer-probe.ps1`
- `build-reference-renderer.ps1`

The low-level probe wrappers retain `-SkipBuild` for diagnostics. That switch is intentionally **not** exposed by `run-reference-windows-renderer-probe.ps1` or `run-reference-quest-renderer-probe.ps1`, and evidence from a hand-assembled diagnostic flow must not be relabelled as canonical reference evidence.

## What the physical probes prove

The machine/deformation evidence records and revalidates:

- exact BodyRig build revision;
- platform and Unity runtime (`WindowsPlayer` or Android);
- exact pinned Unity version;
- non-empty Unity build GUID;
- Quest/Oculus device identity for the Quest gate;
- graphics/device information;
- BodyRig body id;
- accepted `.mrbody` package hash;
- runtime-manifest hash;
- avatar and bodyprint hashes;
- VRM 1.0 load success;
- valid Humanoid and required bones;
- canonical renderer identity;
- fixed six-pose `humanoid-muscle-sweep-v1` completion;
- restored neutral pose and mandatory human review state.

The human attestation then requires explicit PASS for source identity/texture, geometry/proportions, upper- and lower-body deformation, cross-limb leakage absence and consideration of anatomical skin-QA.

## Final reference release gate

Only after Windows + Quest canonical evidence and both structured human attestations exist:

```powershell
.\complete-reference-acceptance.ps1 `
  -AcceptanceDir "C:\path\to\acceptance"
```

The wrapper revalidates the exact renderer contract, including Unity and UniVRM revision authority, rejects legacy root evidence layouts, verifies both structured human quality reviews and delegates the full byte/provenance binding to `complete-acceptance.ps1`.

Only the resulting final `bodyrig-release-acceptance.json` may set:

```text
release_gate_pass=true
production_activation=true
```

## Still not proven by repository CI

Repository CI proves source contracts, exact dependency declarations, ephemeral-build policy, package-lock validation logic, PowerShell parsing and the complete non-physical/tamper evidence state machine. It does **not** prove that Unity `6000.3.13f1` actually compiles the project on the target Windows rig, that UPM resolves successfully there, that the APK deploys to a real Quest, or that the source-derived avatar looks and deforms correctly.

Those are deliberately physical gates. They must be produced from the same real Stash/source-derived profile and exact BodyRig revision that reached Gate A.
