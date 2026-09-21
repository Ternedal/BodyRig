# Photoreal V2 P3 Quest 2 review-only runtime

This stage bridges the final modular P3 student to a **real physical Quest renderability check** without weakening BodyRig's canonical Gate-A/production renderer boundary.

It is intentionally not an XR or photoreal PASS gate yet.

## Why a separate review runtime exists

The canonical BodyRig reference loader starts from Gate A:

```text
runtime-manifest.json
avatar.vrm
bodyprint.json
package / BodyPrint authority
```

That loader deliberately exposes no loose-VRM acceptance path.

The modular P3 student instead ends with:

```text
avatar.vrm
basecolor.png
quest2-modular-provenance.json
```

Creating a fake BodyPrint or pretending those files are Gate A would cross an authority boundary.

The P3 review runtime therefore has a separate manifest, loader, APK application id and machine-probe format.

## Materialize the review runtime

From the exact clean BodyRig checkout used by the final P3 software chain:

```powershell
.\prepare-photoreal-v2-p3-quest2-review-runtime.ps1 \
  -FinalWorkspace <FINAL_P3_WORKSPACE> \
  -RuntimeReviewWorkspace <P3_RUNTIME_REVIEW_WORKSPACE>
```

The command strict-reads the canonical P3 runtime-review plan, re-hashes the final three-artifact universe and copies the exact bytes into a new create-only review workspace:

```text
quest2-review-runtime/
  p3-quest2-review-manifest.json
  p3-quest2-review-runtime-receipt.json
  avatar.vrm
  basecolor.png
  quest2-modular-provenance.json
```

The review manifest records:

- exact BodyRig revision;
- exact P3 plan/execution/runtime-review lineage;
- performer and epoch;
- exact avatar/basecolor/provenance SHA-256 values;
- Quest 2 + `skinned-mesh-pbr`;
- specialized-eye + teacher-derived-hair components;
- `physical_review_only=true`;
- `comparison_only=true`;
- all physical/runtime/photoreal/production authority false.

No BodyPrint, `.mrbody` package or Gate-A receipt is created.

## Isolated Unity application

The review APK uses:

```text
dk.ternedal.bodyrig.p3review
```

The canonical production/reference probe retains:

```text
dk.ternedal.bodyrig.reference
```

The P3 review bootstrap installs only in the review application.

The normal physical-probe bootstrap and automatic deformation-quality grader explicitly do not install in the review application. A stale review payload therefore cannot silently turn the canonical Gate-A application into review mode.

Build target:

```text
P3QuestReview
BodyRig.ReferenceRenderer.Editor.BodyRigReferenceBuild.BuildP3QuestReviewBatch
Builds/Quest/BodyRigP3QuestReview.apk
```

Unity and UniVRM remain pinned by the existing reference-renderer contract.

## Physical renderability probe

With Quest connected over the pinned Unity Android ADB:

```powershell
.\run-photoreal-v2-p3-quest2-review-probe.ps1 \
  -ReviewRuntimeWorkspace <QUEST2_REVIEW_RUNTIME_WORKSPACE>
```

The operator:

1. requires exact clean current checkout;
2. revalidates review manifest/receipt and all local payload hashes;
3. requires the renderer-contract-pinned ADB;
4. requires a real Quest/Oculus-class device;
5. builds the isolated review APK unless `-SkipBuild` is explicitly used;
6. force-stops the review app and replaces only its review workspace;
7. pushes the exact manifest, VRM, basecolor and provenance;
8. launches the review APK;
9. waits for create-only device evidence;
10. pulls evidence into a new local evidence directory;
11. revalidates revision, device and all artifact hashes before committing local evidence.

The app remains open for human visual inspection after the machine probe succeeds.

## What the current machine probe proves

A successful:

```text
p3-quest2-review-render-probe.json
```

proves:

- the built player comes from the exact BodyRig revision in the review manifest;
- it executed on Android Quest/Oculus hardware;
- exact review-manifest SHA is observed;
- exact avatar/basecolor/provenance hashes are observed;
- UniVRM loads the exact VRM as VRM 1.0;
- Unity sees a valid Humanoid with required bones;
- `BodyRigP3QuestEyeComponent` is instantiated and drawable;
- `BodyRigP3QuestTeacherHair` is instantiated and drawable.

This is materially stronger than a software-only schema check: it proves the final modular student actually renders on the physical target device.

## Deliberate XR limitation

The current reference-renderer package manifest contains no OpenXR or Oculus/Meta XR package.

Therefore a flat Android render on a Quest must **not** be relabeled as stereo XR evidence.

The P3 review probe hardcodes:

```text
xr_runtime_present = false
stereo_rendering_observed = false
vr_safe_frame_pacing_observed = false
physical_runtime_review_complete = false
runtime_acceptance_authority = false
photoreal_acceptance_authority = false
production_activation = false
```

It may record the Android display refresh rate as diagnostic context only. That number is not the P3 XR performance acceptance measurement.

## Next implementation boundary

The next software step is an isolated XR-enabled P3 review application or review build variant.

That stage must add and pin a real Quest-supported XR stack, then measure:

- actual stereoscopic rendering;
- headset refresh rate;
- p95 frame time under the real XR render loop;
- VR-safe frame pacing.

Only after those physical XR measurements and the explicit eight-dimension human visual review exist may the existing P3 physical PASS/FAIL recorder grant runtime/photoreal acceptance.

Production activation remains a separate BodyRig release boundary even after a physical P3 PASS.
