# Digital twin fast path v1 — Stash → BodyRig → ModelRig / Kaliv / VR

Parent: #1397; vertical slice: #1398. This is a proposed interface, not a claim that video reconstruction exists.

## Purpose

Use the owner's authorized Stash video to recover a reusable **person-specific** 3D representation (rig, mesh/appearance, motion) and generate images, video and VR assets. The existing #1394 inventory and #1396 scene inspector are supporting stages, **not** the final product. Preserve general-purpose generation.

## Progressive stages and latency gates

1. `SOURCE_STAGED`: obtain an explicitly selected Stash source once, copy to local SSD, hash and disconnect from Stash. Do not persist the source URL or credentials in output.
2. `FRAMES_READY`: `ffprobe` metadata; `ffmpeg` sample timestamps and shot changes, capped by configurable `max_frames`, deduplicated by perceptual fingerprint. Do not decode the entire video for the initial preview. Record frame selection and wall time.
3. `TRACK_READY`: select the owner's track, reject or require confirmation on multi-person ambiguity. No automatic assumption that the most visible subject is the owner.
4. `POSE_READY`: time-indexed 2D/3D joints and camera estimates; output a skeleton/motion clip, even if geometry reconstruction is not ready.
5. `MESH_READY`: fuse multi-frame body shape into a stable rigged mesh, with confidence and explicit unknown/occluded regions. A single-image mesh is an estimate, not a proven likeness.
6. `TWIN_READY`: identity/appearance validated against authorized reference views; canonical meters, right-handed coordinates, named skeleton mapping, UV/textures and stable ID; versioned GLB + motion export.
7. `CONDITIONING_READY`: ModelRig has actually consumed the mesh/pose/depth/normal inputs and produced a preview.
8. `VR_READY`: a real Kaliv or VR client loads the asset and validates scale, animation, camera and stereo/depth output; a GLB file alone is insufficient.

Each stage writes a durable atomic status with `started_at`, `completed_at`, `elapsed_ms`, backend/version, confidence and error code. Publish a usable preview as early as possible. **Goal: first usable output in minutes**, measured on the owner's Windows 11 / WSL2 / 2× RTX 3060 12GB rig; no invented SLA or GPU throughput.

## Manifest shape (draft)

```json
{
  "schema": "bodyrig-digital-twin-v1",
  "subject": {"subject_id": "owner-local", "track_id": "track-0", "identity_confirmed": false},
  "source": {"sha256": "<hex>", "duration_ms": 0, "staged_source_retained": false},
  "sampling": {"timestamps_ms": [], "selection_algorithm": "scene-change+diversity-v1"},
  "stages": {"POSE_READY": {"elapsed_ms": 0, "confidence": null}},
  "artifacts": {"pose_json": null, "motion_bvh": null, "rigged_glb": null, "preview": null},
  "geometry": {"units": "meters", "handedness": "right", "uncertainty": "unknown"},
  "privacy": {"local_only": true, "source_cleanup": "pending"}
}
```

All artifact paths must be **relative**, allowlisted and checked for traversal/symlink escape. Source footage and extracted raw frames are ephemeral; cleanup must run on success, cancellation and failure. SSD deletion is not guaranteed secure erasure.

## Candidate inference backends (not yet validated)

- Meta SAM 3D Body: single-image MHR body mesh and pose, optionally guided by keypoints/masks. Requires checkpoint access and a local GPU compatibility/latency test; by itself does not solve multi-frame identity, texture or motion fusion. https://github.com/facebookresearch/sam-3d-body
- SAM3DBody-cpp: ONNX/C++ video-oriented pose/BVH path; validate actual CUDA runtime, output skeleton semantics and speed on RTX 3060. https://github.com/AmmarkoV/SAM3DBody-cpp
- Benchmark any accelerated TensorRT path independently; vendor L4 results are not evidence for RTX 3060 performance.

## Vertical-slice acceptance

- Offline deterministic test: video metadata, frame timestamps, multiple-person rejection, cache invalidation, failure cleanup, hostile paths, no network after initial staging.
- Physical sample: first pose, first mesh, first preview and first downstream conditioning latency; cold/warm cache, peak VRAM, output size, quality/confidence and any manual corrections.
- One actual consumer: Kaliv animated preview or ModelRig generated output, with artifact hashes and version pinning.
- No merge or release without owner's explicit go.
