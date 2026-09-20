# BodyRig Photoreal V2

## Decision

The SiTH -> reconstructed shell -> SMPL-X/VRM path is no longer the visual-authority path for BodyRig.

It remains useful for skeletons, pose priors, body correspondence, measurements and compatibility, but it must not define final visual identity.

Photoreal V2 reverses the architecture:

```text
Stash source universe
  -> byte-bound exhaustive observations
  -> leakage-safe train/evaluation split
  -> deterministic scout/deprojection plan
  -> measurement-only vision adapter
  -> train-only identity bank + source-authoritative calibration
  -> core identity authority + frame leakage/coverage gate
  -> photoreal teacher reconstruction
  -> held-out photoreal validation
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
- projection and stereo layout preserved independently;
- all directly performer-bound still images;
- all performer-bound galleries and their images;
- every media file resolved through the verified Stash path map and SHA-256 bound;
- exact source paths remain build-private and never enter `.mrbody`.

The implemented P0 chain is:

```text
photoreal Stash inventory
  -> source-group-disjoint dataset plan
  -> exact byte/source receipt
  -> deterministic scout scan plan
  -> train-only identity bootstrap
  -> exact analyzer model-set digest
  -> same-model target identity extraction
  -> train-only identity bank
  -> source-authoritative negative discovery + byte receipt
  -> same-model negative extraction
  -> data-derived identity calibration
  -> measurement-only multi-candidate frame analysis
  -> core identity authority
  -> perceptual leakage + held-out coverage gate
```

The external analyzer is measurement-only. It cannot decide target identity, choose train/evaluation assignment, grant teacher-training authority, grant photoreal acceptance or activate production.

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

## Source analysis and identity authority

Photoreal V2 separates measurement from authority.

The external frame analyzer may measure, per detected person candidate:

- an identity embedding in the pinned model space, or `unavailable`;
- head/body view bin;
- face and full-body visibility;
- sharpness;
- motion;
- occlusion;
- person screen fraction;
- frame/perceptual hashes.

The analyzer must not emit `target_identity_verified`, identity authority or a hard-coded identity confidence threshold.

BodyRig core owns:

- exact source-byte binding;
- source-group-disjoint train/evaluation assignment;
- train-only target identity bootstrap;
- the identity bank and its exact model-set provenance;
- negative calibration evidence from other Stash performer IDs;
- the data-derived cosine threshold;
- multi-candidate target selection;
- cross-split perceptual near-duplicate rejection;
- held-out view coverage requirements;
- the decision whether teacher training may start.

A source marked as single-performer is direct identity authority only when the measured sample itself contains exactly one person candidate. In multi-person samples, exactly one candidate may cross the calibrated target threshold. Zero matches remain unresolved; two or more matches make the sample identity-ambiguous and no candidate receives target authority.

The current core frame-index gate rejects train/evaluation frames with a 64-bit perceptual-hash Hamming distance of four or less. It also requires front, three-quarter and profile face evidence plus front and three-quarter full-body evidence in the held-out evaluation split. Rear full-body evidence becomes mandatory when rear evidence is observable in the source universe.

Even a clean frame index grants **teacher-training authority only**. It never grants photoreal, human or production acceptance.

### Canonical post-P0 operator handoff

After one P0 root has persisted canonical `teacher-training-authorized` status, use the checkout-bound continuation operator from exact clean current `main`:

```powershell
.\continue-photoreal-v2-teacher.ps1 -P0Root <P0_ROOT>
```

The operator discovers the bound overnight summary when unambiguous, creates/reuses per-run P0 physical/readiness receipts in the exact P0 root, revalidates the current tracked readiness verifier, builds the canonical appearance-epoch plan + review handoff, and then **stops with exit code 2 at human review**. It prints the available train/evaluation source groups but never selects or approves them.

After visual review, rerun the same operator with an explicit epoch decision, at least one train group and one held-out evaluation group:

```powershell
.\continue-photoreal-v2-teacher.ps1 `
  -P0Root <P0_ROOT> `
  -SelectedEpochId <HUMAN_ASSIGNED_EPOCH_LABEL> `
  -SourceGroup <TRAIN_GROUP> `
  -SourceGroup <EVAL_GROUP> `
  -ReviewedBy <OPERATOR> `
  -ReviewNotes <NOTES> `
  -ApproveHumanReview
```

`SelectedEpochId` is a reviewer-assigned audit label for the coherent appearance state being approved; it is not selected from a machine-ranked candidate list and does not itself grant authority. The actual evidence boundary is the explicit set of reviewed train and held-out evaluation source groups.

Existing continuation artifacts are not trusted merely because they exist: the operator recomputes and requires exact canonical equality before reuse. The P0 root itself remains immutable; continuation artifacts are written to a sibling `<P0_ROOT>-teacher` workspace by default.

The underlying create-only CLI stages remain available for audit/manual recovery:

```powershell
bodyrig-photoreal-appearance-epoch --frame-index <P0_ROOT>/frame-index.json --out <EPOCH_PLAN>
bodyrig-photoreal-appearance-epoch-handoff --plan <EPOCH_PLAN> --handoff-out <HANDOFF> --review-template-out <REVIEW_TEMPLATE>
bodyrig-photoreal-appearance-epoch-review-record --plan <EPOCH_PLAN> --handoff <HANDOFF> --selected-epoch-id <EPOCH_ID> --source-group <TRAIN_GROUP> --source-group <EVAL_GROUP> --reviewed-by <OPERATOR> --review-notes <NOTES> --approve-human-review --out <HUMAN_REVIEW>
bodyrig-photoreal-appearance-epoch-review --plan <EPOCH_PLAN> --human-review <HUMAN_REVIEW> --out <EPOCH_SELECTION>
bodyrig-photoreal-teacher-input-from-p0 --p0-root <P0_ROOT> --epoch-selection <EPOCH_SELECTION> --out <TEACHER_INPUT>
```

The handoff and editable review template are deliberately non-authoritative. The final selection may authorize teacher input/training only; it must keep `photoreal_acceptance_authority=false`, `human_visual_acceptance_required=true` and `production_activation=false`.

Only after strict teacher input exists may a pinned teacher adapter run. For the first static-teacher benchmark, ExAvatar is the canonical current operator path:

```powershell
.\run-photoreal-v2-exavatar-teacher.ps1 `
  -TeacherWorkRoot <P0_ROOT>-teacher `
  -AssetRoot <EXAVATAR_MODEL_ASSETS> `
  -ReferenceModelRoot <REFERENCE_MODEL_ROOT> `
  -SmplxGender <female|male|neutral> `
  -CameraMode <colmap|virtual>
```

The four values above are explicit operator authority and are never guessed. Public pinned repositories and the pinned WSL runtime are also not mutated/downloaded implicitly: if missing, the operator exits with code 2. Add `-SetupPublicCode` and/or `-SetupRuntime` only when those public setup actions are intended. Restricted SMPL-X/FLAME/MANO/model assets are never auto-downloaded.

The ExAvatar operator recomputes or revalidates the strict benchmark plan, strict WSL preflight, exact authorized-frame materialization, isolated WSL workspace, Hand4Whole asset stage, preprocessing state, CUDA runtime preflight and hash-bound teacher config. Existing artifacts do not gain authority merely by existing.

Preparation stops at **LAUNCH READY** unless `-RunTeacher` is supplied. With `-RunTeacher`, the pinned ExAvatar adapter trains the static teacher and exports the exact teacher manifest plus 50 neutral-pose review renders. Training completion still grants no likeness PASS: the operator exits with the held-out/human review explicitly pending and keeps `photoreal_acceptance_authority=false` and `production_activation=false`.

## Stereo and spatial source handling

Spatial material is evidence, not noise.

Photoreal inventory records projection and stereo layout independently. A source may therefore be, for example:

```text
projection = vr180
stereo_layout = side-by-side
```

The scout planner:

- samples all planned source groups deterministically;
- splits side-by-side and over-under material into left/right observations;
- preserves train/evaluation assignment;
- requires deprojection for VR180/VR360/equirectangular material;
- fails closed on unknown stereo layout or unresolved ~2:1 projection ambiguity.

Spatial sources remain part of the byte-bound teacher source universe, but they cannot bootstrap identity before a projection-authoritative deprojection path exists. No aspect-ratio or center-crop guess is allowed to become identity/source authority.

## Reference P0 vision stack

The first reproducible P0 measurement benchmark is deliberately external to BodyRig core:

- InsightFace `buffalo_l` for face detection/recognition embeddings;
- DWPose/RTMPose-L whole-body 384x288 for body/face/hand keypoint evidence;
- RTMDet-M person detector;
- pinned MMPose and MMDetection revisions;
- exact adapter SHA-256;
- exact model-set SHA-256, including the local runtime-environment receipt.

The same identity model space is used for target bootstrap, non-target calibration and frame analysis. A threshold learned in one embedding space is never applied to another.

Negative video calibration uses a deterministic aggregate timestamp budget distributed across all verified negative video sources. The sampling budget is intentionally much denser than the original six-timestamp scout because calibration still requires at least eight accepted identity observations from at least two distinct negative performers; sampling density never lowers those authority gates.

The reference adapter returns multiple person candidates rather than silently selecting the largest face. BodyRig core owns the target decision.

The model weights remain external research dependencies. The `buffalo_l` model package has research/non-commercial licensing; BodyRig setup requires an explicit operator acceptance switch and never records acceptance automatically.

The first-time/full reference operator is:

```powershell
.\start-photoreal-v2-reference.ps1 `
  -PerformerId 42 `
  -OutputRoot C:\BR\photoreal-p0-42 `
  -AcceptInsightFaceResearchLicense
```

On first use this may build the external model root and pinned WSL environment. On later runs the already-provenanced stack is reused. Before any Stash scan, the reference wrapper performs a synthetic GPU/model preflight that initializes and executes both the face and whole-body inference stacks without accessing source media.

The P0 runner itself executes in an isolated child PowerShell process so its fail-closed exit codes cannot terminate the operator's working shell.

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

ExAvatar is the first benchmark teacher adapter, not a permanent architectural dependency. The adapter boundary must allow it to be replaced if held-out human review shows waxiness, identity drift, weak hair or other visible failure.

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

### Quest 2 - first physical standalone proof target

Quest 2 is the first BodyRig standalone proof target because it is the headset currently available for physical validation.

That does **not** mean Quest 2 defines the teacher quality ceiling. The PC teacher remains uncompromised; Quest 2 receives a deliberately distilled student and its fidelity loss must be reported against the accepted teacher.

The likely Quest 2 direction is:

- aggressively optimized skinned mesh where geometry is sufficient;
- neural/high-frequency appearance textures or residuals where conventional PBR loses likeness;
- specialized eye rendering;
- teacher-derived hair representation;
- device-specific LOD and foveated/VR-safe rendering;
- no assumption of native Meta Gaussian-splat support.

The first Quest 2 milestone is proof that a distilled student can preserve identity under real-time head/body motion. If that requires a materially lower visual ceiling than the teacher, the delta must be explicit rather than hidden behind a generic "photoreal" label.

### Quest 3 / 3S - higher-fidelity standalone target

Quest 3/3S is the higher-headroom standalone target and may use rendering paths unavailable on Quest 2, including native Gaussian-splat support where it proves useful.

It is not allowed to redefine the source/teacher pipeline. Both headset generations descend from the same accepted teacher and are measured independently against it.

The product target remains VR-safe frame pacing. A research result at low frame rate may prove feasibility but is not final BodyRig runtime acceptance.

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
- projection and stereo layout;
- information-priority scores without discarding low-ranked data.

Ranking is used to schedule expensive analysis. Ranking does **not** erase the rest of the source universe.

## Data epochs

A performer can change over time: hair style/colour, body mass, cosmetic changes, tattoos, ageing, clothing and capture conditions.

Photoreal V2 therefore has an explicit `appearance_epoch` layer before teacher training. Automatic clustering may propose epochs, but human review owns the final epoch boundary. Teacher input is allowed only from the selected coherent epoch and held-out evaluation remains physically separate from the external teacher request.

## Implementation status

1. `P0`: exhaustive Stash video/image/gallery inventory. **Implemented.**
2. Media hashing, local-path verification and source-universe receipt. **Implemented.**
3. Independent projection/stereo classification and deterministic scout plan. **Implemented.**
4. Train-only identity bootstrap and exact model-set provenance. **Implemented.**
5. Source-authoritative negative calibration and data-derived identity threshold. **Implemented.**
6. Multi-candidate measurement-only frame analyzer contract and core identity authority. **Implemented.**
7. Core frame index with perceptual leakage and held-out view gates. **Implemented.**
8. Pinned reference vision adapter, WSL transport, environment/model setup and synthetic preflight. **Implemented in code; physical rig validation pending.**
9. One-command reference P0 operator. **Implemented in code; physical rig validation pending.**
10. Appearance-epoch proposal + explicit human review receipt. **Implemented in core.**
11. Representation-agnostic teacher request/runner boundary. **Implemented in core.**
12. ExAvatar benchmark adapter/preflight. **Prepared; real performer benchmark pending P0 data.**
13. Run P0 against performer 42 and inspect actual source coverage/calibration. **Pending physical rig.**
14. Reconstruct performer 42 as the first teacher benchmark. **Blocked on P0 + human epoch selection.**
15. Render fixed canonical views plus held-out-reference comparisons.
16. Stop until human visual review says the static teacher is genuinely photographic.
17. Add body/face animation correspondence.
18. Distill the accepted animated teacher to Quest 2, then Quest 3/3S.

## What is deliberately frozen

The current source-hair-shell/cards path remains useful research evidence but is not the route to Photoreal V2 acceptance.

Do not spend additional physical-rig time improving hair cards, eye proxies or SiTH-shell appearance unless the work is directly reused by the teacher/distillation architecture.

## External references

- Meta Spatial SDK Gaussian splats: https://developers.meta.com/horizon/documentation/spatial-sdk/spatial-sdk-splats/
- MUA: Mobile Ultra-detailed Animatable Avatars: https://arxiv.org/abs/2604.18583
- PrismAvatar: Real-time animated 3D neural head avatars on edge devices: https://arxiv.org/abs/2502.07030
