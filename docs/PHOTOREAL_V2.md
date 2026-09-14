# BodyRig Photoreal V2

## Decision

The SiTH -> reconstructed shell -> SMPL-X/VRM path is no longer the visual-authority path for BodyRig.

It remains useful for skeletons, pose priors, body correspondence, measurements and compatibility, but it must not define final visual identity.

Photoreal V2 reverses the architecture:

```text
Stash source universe
  -> exhaustive calibrated observations
  -> photoreal teacher reconstruction
  -> photoreal validation
  -> animation/deformation model
  -> animated photoreal validation
  -> device distillation
  -> Quest runtime representation
```

The central rule is simple:

> Do not optimize an avatar until the teacher already looks like the real person.

A machine-valid mannequin is a failure.

## Why the previous path hit a ceiling

The previous high-fidelity path intentionally reduced Stash input to a small number of observations and excluded VR/SBS/OU material before reconstructing one SiTH surface and transferring that surface onto SMPL-X/VRM.

That is appropriate for a generic rigged avatar. It is the wrong information bottleneck for a photoreal digital twin when the source library already contains hours of high-resolution video, still photography and stereo/VR observations.

Photoreal V2 therefore treats the entire source library as a reconstruction dataset rather than merely a way to choose one identity frame.

## Non-negotiable quality gates

### Gate P0 - source universe

Before reconstruction, BodyRig must account for the complete performer-bound source universe available through Stash:

- all matching scenes, not the top ten;
- every local video file and its native resolution/frame rate;
- VR180/VR360/SBS/OU/stereo material retained and classified rather than rejected;
- all directly performer-bound still images;
- all performer-bound galleries and their images;
- exact source paths remain build-private and never enter `.mrbody`.

`photoreal-stash-inventory.ps1` is the first implementation of this gate.

### Gate P1 - static photoreal teacher

The first reconstruction milestone has deliberately **no VRM requirement and no Quest requirement**.

Produce a canonical high-quality teacher that can render at least:

- front face;
- three-quarter face;
- profile face;
- front full body;
- three-quarter full body;
- rear full body where source evidence exists.

Each rendered view must be compared against held-out real source frames that were not used as direct texture/projective references for that view.

Failure conditions include obvious mannequin appearance, identity drift, wax/plastic skin, generic eyes, synthetic hair silhouette, collapsed hands or geometry that is visibly inconsistent with the held-out reference.

No downstream animation or Quest work starts while P1 fails human visual review.

### Gate P2 - animated photoreal teacher

Only after P1 passes:

- drive body pose through a canonical skeleton/SMPL-X correspondence;
- drive face through an explicit facial-expression representation;
- preserve identity and source appearance through motion;
- validate head turns, eye motion, mouth motion, hands and full-body pose against source motion.

The rig drives the teacher. The rig does not replace the teacher surface/appearance.

### Gate P3 - Quest distillation

Only after P2 passes:

- distill high-frequency appearance and pose-conditioned residuals to a compact runtime representation;
- use ordinary mesh skinning where it is visually sufficient;
- use neural textures/residuals where ordinary PBR loses identity;
- treat eyes and hair as specialized components;
- optionally use Gaussian/splat representation where the target headset and renderer support it efficiently;
- preserve an explicit fidelity delta against the teacher.

A runtime build cannot claim fidelity greater than its measured teacher delta.

## Teacher representation

BodyRig should not commit to one reconstruction family prematurely. The teacher boundary is intentionally representation-agnostic.

Candidate teacher stack:

1. **camera/source calibration**
   - recover intrinsics where possible;
   - estimate distortion;
   - decode stereo layouts independently;
   - establish source timestamps and frame hashes;
   - identify repeated shots and near duplicates.

2. **identity-aware frame selection**
   - use far more observations than the old sparse 1..10 segment flow;
   - cover azimuth, elevation, expression, hair state, hands, feet and clothing/body regions;
   - separate incompatible appearance epochs instead of averaging them together.

3. **geometry/appearance teacher**
   - multi-view neural reconstruction / Gaussian or neural-field teacher for source fidelity;
   - explicit high-detail surface where animation correspondence requires it;
   - view-dependent appearance where source evidence supports it;
   - source-bound appearance, not generic generated anatomy.

4. **semantic correspondence**
   - SMPL-X remains useful here as a body correspondence and skeleton prior;
   - face correspondence gets its own high-resolution model/landmark domain;
   - correspondence may deform the teacher but must not collapse teacher geometry into SMPL-X topology.

## Hair

Hair is no longer extracted from a reconstructed body shell and treated as final runtime geometry.

Teacher hair may use a neural/volumetric representation or explicit geometry reconstructed from multi-view evidence.

Runtime hair is derived *from the accepted teacher* using whichever representation preserves the measured silhouette and appearance best:

- groom/strands on sufficiently capable targets;
- teacher-baked cards for raster targets;
- compact splats/neural residuals where appropriate.

A hair representation is accepted because it matches the teacher and held-out photographs, not because it satisfies a geometry heuristic.

## Face and skin

The face is the primary identity gate.

The teacher must preserve:

- face geometry at identity-critical scales;
- eye shape and placement;
- eyelids and wetline;
- iris appearance;
- teeth/mouth interior where observed;
- pores/freckles/moles/scars where resolved by source material;
- specular response distinct from baked illumination;
- hairline and brows.

Lighting baked into source images must be separated from material appearance as far as the data supports. A diffuse texture copied from one photograph is not photoreal material reconstruction.

## Quest targets

### Quest 3 / 3S

This is the primary photoreal standalone target.

Meta's Spatial SDK supports native Gaussian splats on Quest 3/3S and currently recommends optimized splats below roughly 150k primitives. That is useful as a rendering option, not a complete animated-avatar solution.

The product target remains VR-safe frame pacing. A research result at 24 FPS proves feasibility of compact high-detail avatars but is not an acceptable final BodyRig VR target.

### Quest 2

Quest 2 remains a compatibility target, but its practical photoreal representation will likely need to be more aggressively distilled toward conventional rasterization, neural textures and LOD. Native Spatial SDK splat support must not be assumed for Quest 2.

Photoreal V2 must report target-device fidelity separately. It must not call Quest 2 and Quest 3 output equivalent if their teacher deltas differ materially.

## Distillation direction

The architectural precedent is teacher -> efficient student, not direct low-budget reconstruction.

Relevant research directions include:

- MUA (2026): ultra-detailed animatable teacher distilled into a compact representation with native Quest 3 proof-of-concept performance;
- PrismAvatar (2025): neural volumetric head reconstruction distilled to a rigged mesh plus neural textures for real-time edge rendering;
- mobile Gaussian-splat compression/pruning for view synthesis where splats are useful.

These are design signals, not dependencies. BodyRig will pin concrete implementations only after reproducing their value against our own held-out performer data.

## Stash is an advantage, not merely a catalogue

For Photoreal V2 the Stash library is effectively a private multi-view capture dataset.

The new inventory stage explicitly records:

- total flat video hours;
- total spatial/VR/projection video hours;
- high-resolution still count;
- still megapixel budget;
- performer binding;
- scene/gallery provenance;
- information-priority scores without discarding low-ranked data.

Ranking is used to schedule expensive analysis. Ranking does **not** erase the rest of the source universe.

## Data epochs

A performer can change over time: hair style/colour, body mass, cosmetic changes, tattoos, ageing, clothing and capture conditions.

Photoreal V2 therefore needs an explicit `appearance_epoch` layer before teacher training. The first teacher should represent one internally coherent appearance state rather than averaging years of incompatible observations.

Automatic clustering may propose epochs, but human review owns the final epoch boundary.

## Planned implementation sequence

1. `P0`: exhaustive Stash video/image/gallery inventory.
2. Add media hashing, local-path verification and source-universe receipt.
3. Decode/classify stereo and VR layouts instead of rejecting them.
4. Build frame-index inventory with perceptual deduplication and quality metrics.
5. Add camera/intrinsics estimation and shot grouping.
6. Add appearance-epoch proposal/report.
7. Build a teacher adapter contract independent of VRM/SMPL-X.
8. Reconstruct performer 42 as the first teacher benchmark.
9. Render fixed canonical views plus held-out-reference comparisons.
10. Stop until human visual review says the static teacher is genuinely photographic.
11. Add body/face animation correspondence.
12. Distill the accepted animated teacher to Quest targets.

## What is deliberately frozen

The current source-hair-shell/cards path remains useful research evidence but is not the route to Photoreal V2 acceptance.

Do not spend additional physical-rig time improving hair cards, eye proxies or SiTH-shell appearance unless the work is directly reused by the teacher/distillation architecture.

## External references

- Meta Spatial SDK Gaussian splats: https://developers.meta.com/horizon/documentation/spatial-sdk/spatial-sdk-splats/
- MUA: Mobile Ultra-detailed Animatable Avatars: https://arxiv.org/abs/2604.18583
- PrismAvatar: Real-time animated 3D neural head avatars on edge devices: https://arxiv.org/abs/2502.07030
