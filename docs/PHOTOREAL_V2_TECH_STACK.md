# BodyRig Photoreal V2 - technical direction

Status: architecture decision record, not production authority.

## Owned-hardware target

The first standalone acceptance target is the currently owned Quest 2 class device. Quest 3/3S is a higher-budget follow-on target, not an excuse to make the first runtime depend on hardware the operator does not own.

Meta's native Spatial SDK Gaussian-splat path is currently Quest 3/3S-only, so BodyRig must not make that API a dependency of the Quest 2 runtime.

## Core representation decision

Photoreal V2 uses different representations for truth and deployment.

### Teacher

The PC teacher is allowed to be expensive. Its only job is to preserve source identity and appearance under held-out views.

Preferred investigation order:

1. multi-view / dynamic Gaussian or neural avatar reconstruction for source fidelity;
2. explicit high-detail geometry where semantic correspondence, collision or rigging requires it;
3. separate high-fidelity face/head model if the whole-body representation loses identity-critical face detail;
4. view-dependent appearance and relighting where the source data supports it.

SMPL-X is correspondence and pose infrastructure. It is not visual authority.

### Quest 2 student

The first Quest student should assume a conventional triangle renderer plus compact learned appearance, not native Gaussian splats.

Preferred direction:

- skinned coarse/high-quality mesh proxy;
- neural texture / learned feature texture;
- compact screen-space decoder or residual network;
- explicit eyes and mouth interior;
- teacher-derived hair representation;
- pose-conditioned residuals for clothing, face and other deformation that LBS cannot preserve;
- aggressive LOD/foveation;
- App SpaceWarp may be evaluated as a performance tool, but cannot be used to hide unstable animation or unacceptable latency.

Research precedent:

- MoRF demonstrates realistic full-body neural-texture avatars at 30 FPS on Snapdragon 888-class mobile hardware.
- RAM-Avatar demonstrates real-time photoreal full-body control using neural-texture-style rendering.
- PrismAvatar distills neural volumetric head appearance into rigged mesh + neural textures and reports 60 FPS on mobile/edge devices.
- MobilePortrait reports over 50 FPS for a lightweight neural head-avatar pipeline on mobile devices.

These results are feasibility evidence, not drop-in dependencies.

### Quest 3/3S student

Quest 3/3S can additionally evaluate:

- compact Gaussian/2D Gaussian students;
- native Spatial SDK splats for static or partially static components where the API fits;
- a custom deformable splat renderer only if it beats the raster/neural-texture student at equal fidelity and VR frame pacing.

Meta currently documents native splat support only on Quest 3/3S and recommends staying below roughly 150k splats for performance. That API is therefore an optimization option, not the architecture foundation.

MUA demonstrates a teacher-to-compact-student direction with native on-device Quest 3 performance at 24 FPS. This is strong feasibility evidence but below BodyRig's final VR frame-pacing requirement.

## Teacher candidates to reproduce, not merely cite

BodyRig should benchmark candidate ideas against performer 42 rather than selecting a paper by reputation.

Initial shortlist:

- TaoAvatar: multi-view full-body Gaussian avatar, real-time AR-device deployment direction;
- DNF-Avatar: neural-field teacher distilled to explicit 2D Gaussian student with reported 67 FPS;
- AniGS: animatable Gaussian avatar direction;
- HRAvatar / PSAvatar: high-fidelity head-specific Gaussian models;
- MUA: mobile distillation of an ultra-detailed animatable teacher;
- MoRF / RAM-Avatar: raster + neural-texture full-body runtime direction;
- PrismAvatar / MobilePortrait: mobile head-runtime direction.

No method is accepted until BodyRig reproduces useful quality on held-out performer 42 observations.

## Frame-rate policy

"Real-time" in a paper is not automatically VR-ready.

BodyRig reports separately:

- teacher render FPS;
- native application FPS on target headset;
- compositor/display rate;
- whether App SpaceWarp or equivalent reconstruction is active;
- per-eye render resolution;
- motion-to-photon behaviour where measurable;
- fidelity delta against the accepted teacher.

For Quest 2, an early engineering milestone may use 36 native application FPS reconstructed to 72 Hz while the student is being optimized. Final acceptance must be based on perceptual stability and latency as well as throughput; 24-30 FPS alone is not a finished VR target.

## Quality ordering

The work order is fixed:

1. exhaustive source universe;
2. source-byte verification;
3. leakage-safe train/evaluation split;
4. view/quality/epoch analysis;
5. static photoreal teacher;
6. held-out human visual acceptance;
7. animated teacher;
8. held-out motion acceptance;
9. Quest 2 student distillation;
10. Quest 2 physical acceptance;
11. optional Quest 3/3S higher-fidelity student.

No runtime optimization is allowed to redefine the teacher or lower the teacher acceptance gate.

## References

- Meta Spatial SDK Gaussian splats: https://developers.meta.com/horizon/documentation/spatial-sdk/spatial-sdk-splats/
- Meta Application SpaceWarp: https://developers.meta.com/horizon/documentation/spatial-sdk/os-app-spacewarp/
- MUA: https://arxiv.org/abs/2604.18583
- DNF-Avatar: https://openaccess.thecvf.com/content/ICCV2025W/Findings/html/Jiang_DNF-Avatar_Distilling_Neural_Fields_for_Real-time_Animatable_Avatar_Relighting_ICCVW_2025_paper.html
- MoRF: https://openaccess.thecvf.com/content/WACV2024/html/Bashirov_MoRF_Mobile_Realistic_Fullbody_Avatars_From_a_Monocular_Video_WACV_2024_paper.html
- RAM-Avatar: https://openaccess.thecvf.com/content/CVPR2024/html/Deng_RAM-Avatar_Real-time_Photo-Realistic_Avatar_from_Monocular_Videos_with_Full-body_Control_CVPR_2024_paper.html
- PrismAvatar: https://arxiv.org/abs/2502.07030
- MobilePortrait: https://openaccess.thecvf.com/content/CVPR2025/html/Jiang_MobilePortrait_Real-Time_One-Shot_Neural_Head_Avatars_on_Mobile_Devices_CVPR_2025_paper.html
- AniGS: https://openaccess.thecvf.com/content/CVPR2025/html/Qiu_AniGS_Animatable_Gaussian_Avatar_from_a_Single_Image_with_Inconsistent_CVPR_2025_paper.html
- HRAvatar: https://openaccess.thecvf.com/content/CVPR2025/html/Zhang_HRAvatar_High-Quality_and_Relightable_Gaussian_Head_Avatar_CVPR_2025_paper.html
