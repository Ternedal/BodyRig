# Photoidentity anatomy source review

This flow exists to close the remaining source-observability blockers for `body_rear`, `torso_chest`, and `waist_hips` without rendering an avatar and without allowing a model to infer hidden anatomy.

## Authority boundary

OpenPose is used only as a source-space locator for BODY_25 landmarks and crop placement. Machine discovery never decides that:

- a candidate really shows the subject from behind;
- torso/chest anatomy itself is visible rather than covered by clothing;
- waist/hips anatomy itself is visible rather than inferred through clothing.

Those three semantic claims require explicit human review of exact source-derived crops. Public discovery evidence is path-free. Private source paths and review images remain under the retained photoidentity sweep workspace.

A 1024x1024 review image is presentation only. BodyRig records the native crop dimensions and never upscales the source crop before placing it on the 1024 canvas. Review eligibility requires the native source extent and the existing photoidentity detail threshold (`>= 0.80`).

All outputs remain `production_activation=false` and `generic_guessing_permitted=false`.

## Prerequisites

Use the same exact clean BodyRig revision that produced the retained photoidentity sweep. The sweep must already contain the canonical `human-parsing-evidence` stage. The baseline clone output is used only to recover and preflight the already pinned SiTH/OpenPose runtime.

## 1. Discover source candidates

```powershell
.\discover-photoidentity-anatomy-sources.ps1 `
  -SweepRoot '<photoidentity-sweep-root>' `
  -BaselineCloneOutput '<baseline-clone-output>'
```

This creates `anatomy-source-candidates.json` plus a private candidate workspace. Discovery grants no rear/anatomy authority.

## 2. Prepare the flat source review set

```powershell
.\prepare-photoidentity-anatomy-source-review.ps1 `
  -SweepRoot '<photoidentity-sweep-root>'
```

Review the real source crops in `private-anatomy-source-review`. `review-refs.txt` contains the exact refs accepted by the recorder.

For `rear_body`, select at least one crop that clearly shows the subject from behind. For `torso_chest` and `waist_hips`, select crops from at least two distinct scenes where the identity-specific anatomy itself is actually observable. Do not approve shape inferred only from clothing or pose priors.

## 3. Record the atomic human source attestation

```powershell
.\record-photoidentity-anatomy-source-attestation.ps1 `
  -SweepRoot '<photoidentity-sweep-root>' `
  -RearRef '<anatomycand-...:rear_body>' `
  -TorsoRef '<anatomycand-...:torso_chest>','<anatomycand-...:torso_chest>' `
  -WaistRef '<anatomycand-...:waist_hips>','<anatomycand-...:waist_hips>' `
  -ConfirmRearView `
  -ConfirmTorsoChestAnatomyVisible `
  -ConfirmWaistHipsAnatomyVisible `
  -QualityNote '<real source-review note>'
```

The recorder is intentionally atomic: all three confirmations are required. It re-hashes every selected review crop and original source-media file before creating authority. `body_rear` requires at least one distinct source scene; `torso_chest` and `waist_hips` each require at least two.

If an authoritative nail-attested evidence stage already exists, the anatomy recorder validates and preserves it when producing `anatomy-attested-evidence`. Otherwise nail blockers remain unchanged.

## What this does not do

This flow does not reconstruct anatomy, render an avatar, approve a digital twin, or activate production. It proves only that identity-critical source observations exist strongly enough that later reconstruction can proceed without silently substituting a generic body prior.
