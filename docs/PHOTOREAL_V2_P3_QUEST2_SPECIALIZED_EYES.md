# Photoreal V2 P3 Quest 2 specialized eyes

This stage is stacked on the real ExAvatar-derived Quest 2 student candidate and implements the previously open specialized-eye-component blocker.

## Geometry authority

The base candidate is a skinned SMPL-X VRM. BodyRig reads its exact JOINTS_0 and WEIGHTS_0 accessors and selects only triangles where all three vertices carry strong authority from joint 23 (left eye) or joint 24 (right eye). Mixed eyelid/skin boundary triangles are rejected.

The base body mesh is preserved. Four separate skinned primitives are appended: left surface, left cornea, right surface and right cornea. The surface scale is 1.0015 and the corneal shell scale is 1.012.

## Appearance authority

The eye surface uses the exact teacher-derived basecolor produced by the ExAvatar Gaussian-to-canonical-UV candidate stage. Its SHA-256 must match the core candidate receipt. The cornea is a separate transparent PBR layer. Eyelashes remain part of the pending teacher-derived hair component.

## Authority after success

A successful run records implemented_student_components with specialized-eye-component, keeps physical face close-up review required, and keeps P3 distillation, runtime acceptance, photoreal acceptance and production activation false.

The remaining blockers are teacher-derived-hair-component, teacher-student-fidelity-delta-measurement and p3-distillation-manifest.

## Core runner

Run bodyrig.photoreal_p3_quest2_eye_student_runner with candidate-receipt, candidate-output-root and a new output-root.

Before mutation BodyRig strict-reads the candidate receipt, verifies its digest, re-hashes the candidate VRM and basecolor and requires the exact candidate artifact universe. After grafting it writes student/avatar.vrm, student/basecolor.png and p3-quest2-eye-student-receipt.json. The basecolor is copied byte-for-byte.

## Next boundary

The next implementation target is teacher-derived-hair-component. Quest 2 may not depend on native Gaussian splats, so hair must become a bounded mesh/shell/card representation derived from the accepted ExAvatar teacher while preserving silhouette and appearance evidence. Scalp color alone is not completed hair.
