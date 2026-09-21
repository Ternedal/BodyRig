# BodyRig Photoreal V2 appearance-epoch visual review

## Purpose

This operator turns an already teacher-training-authorized P0 root into a private human review pack for appearance-epoch selection.

It deliberately does **not** rescan Stash, rehash source media, rerun identity inference, grant teacher-input authority, grant photoreal acceptance, or activate production.

## Operator path

From an exact clean current `main` checkout:

```powershell
.\prepare-photoreal-v2-appearance-epoch-review.ps1 -P0Root <P0_ROOT>
```

The operator:

1. reads the existing `dataset-plan.json`, `source-receipt.json`, `scan-plan.json`, `frame-index.json`, and authorized `p0-status.json`;
2. converts only the paths of sources that already contain P0-authorized teacher-eligible observations into private WSL runtime paths;
3. does **not** recompute source-media SHA-256;
4. reuses the exact P0 scan-plan decoder authority (`projection`, `stereo_layout`, `decode_mode`, and projection authority) and replays only the exact authorized timestamps/eyes from the frame index;
5. SHA-binds the scan plan into the private path map, review request, and review manifest, then requires every replayed image to reproduce the existing P0 `frame_sha256` exactly;
6. supports flat/mono plus the existing equirectangular, mesh-projection and cubemap deprojection paths through the pinned reference adapter;
7. writes lossless PNG review frames, a public-path-free manifest, a private source-path index, and `review-index.html`.

The default output is a deterministic sibling under `<P0_ROOT>-teacher`, keyed by the frame-index SHA prefix and current BodyRig revision. A valid existing review pack is revalidated instead of regenerated.

## Human boundary

The HTML separates `TRAIN` and `HELD-OUT EVALUATION` groups. The reviewer may inspect both splits to decide which source groups belong to one coherent appearance state.

Held-out evaluation images are review evidence only. They must remain excluded from the external teacher training request. The review pack therefore keeps:

```text
teacher_input_authorized=false
photoreal_acceptance_authority=false
production_activation=false
```

After review, use `continue-photoreal-v2-teacher.ps1` with a human-assigned `SelectedEpochId` label and explicit selected train/evaluation group IDs. The selected groups, not the label itself, define the reviewed evidence boundary.

## Expected outputs

```text
appearance-epoch-visual-review-<frame-index-prefix>-<revision-prefix>/
  appearance-epoch-visual-review-manifest.json
  private-review-index.json
  review-index.html
  frames/
    review-frame-*.png
```

`private-review-index.json` contains local source paths and stays build-private. The public manifest contains source references and exact frame/staged-PNG hashes but no resolved media paths.
