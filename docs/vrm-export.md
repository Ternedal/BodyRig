# VRM export (experimental, #1393)

Turns a third-party 3D asset into a VRM 1.0 avatar that UniVRM (Kaliv renderer,
`reference-renderer`) can load: a model file, a folder, or a whole `.zip` pack
(for example an Open3DLab download). The goal is #1393's fast path: a usable
avatar in seconds to minutes, and a cached repeat in under two seconds.

- **State:** draft. Software-tested in CI on Linux (bubblewrap) and Windows (Job
  Object) with Blender-generated capsule figures. **Not validated on the rig, and
  not with real third-party packs.**
- **`likeness_authority`:** always `false`. A converted third-party model is never
  identity evidence for BodyPrint, `.mrbody` or Photoreal (#817), and it is not a
  substitute for the owner's own twin (#1397).
- **Personal use only.** Every `.vrm` is written with the VRM meta "only author,
  no redistribution, no modification, personal non-profit". There is no publishing
  path. Licence/provenance stays informative (#1393 §7): nothing here gates on it.

## On the rig: WSL2 with bubblewrap

It reuses the scene inspector's WSL setup (same bpy venv, same bubblewrap, same
state file), plus two pinned add-ons.

```powershell
.\setup-scene-inspector-wsl.ps1          # once, if not done already
.\setup-vrm-export-wsl.ps1               # once: pinned add-ons into ~/.local/share/bodyrig/vrm-addons
```

Convert files, or keep an inbox running:

```powershell
.\run-vrm-export-wsl.ps1 -Asset C:\packs\model.zip, C:\packs\hero.fbx -Out C:\BodyRig\vrm-out
.\run-vrm-export-wsl.ps1 -Inbox C:\BodyRig\vrm-inbox -Out C:\BodyRig\vrm-out
```

Each asset gives `<Out>\<name>.vrm` and `<name>.vrm.json` (state, timings per
stage, humanoid mapping, materials, isolation, cache hit). In inbox mode the
source moves to `done\` or `failed\`. The `.vrm` is written to a temporary name
and renamed, so a renderer watching `<Out>` never reads half a file.

## Pipeline

| Stage | Where | What |
|---|---|---|
| fingerprint | host | SHA-256 of the asset (or every file of a folder); cache lookup |
| stage | host | private job dir; zip entries checked for absolute paths, `..`, links, count and size |
| reset + add-ons | Blender | factory reset, auto-run off, add-ons only from the read-only add-on folder |
| import | Blender | XPS (`.mesh`, `.mesh.ascii`, `.xps`) via XNALara-io-Tools; FBX with images confined to the job; glTF/GLB/VRM; `.blend` with `use_scripts=False` |
| humanoid | Blender | name table (`bodyrig/humanoid_names.py`: XPS, ValveBiped/SFM, Daz, Mixamo, generic) in milliseconds; the VRM add-on's structure search only if required bones are still missing |
| materials | Blender | relink textures from the job dir only, fail closed (`bodyrig/vrm_paths.py`: no linked file or folder on the way, containment re-checked right before `reload()`, nothing from outside the job is ever packed); XPS shader groups replaced by Principled + best diffuse texture (otherwise VRM drops them); pack; downscale above `--max-texture` (2048) |
| export | Blender | private meta; VRM add-on validator; `.partial` then rename |
| deliver + cache | host | atomic copy to `<Out>`; content-addressed cache entry |

If Blender itself fails to load before the worker ran (`DLL load failed while
importing bpy`, no output document), the job is retried once, the same rule as the
scene inspector (#1396); `process.attempts` records it. Any other failure is
reported as it is.

The cache key covers the asset hash, the three worker files, the Blender version,
the add-on pins (`bodyrig-addons.json`) and the options. A cache entry whose `.vrm`
no longer matches its recorded hash is ignored.

## Hip/groin weight transfer from a reference body (#1401)

Many third-party rigs bind the pelvis, groin and upper-thigh area badly (whole
patches on the hips bone), so the body tears or collapses when the legs move.
`--weight-reference <model>` (`-WeightReference` on the rig) takes those weights
from a body with a good rig, for example the owner's own twin or a Daz/MPFB base:

1. both skeletons are mapped with the name table; hips, head, spine and both upper
   legs must be found in both;
2. the reference is aligned by the hips position and scaled uniformly by the
   hips→head distance (no rotation: both are assumed upright after import);
3. region vertices are the target vertices whose weights on those bones sum to at
   least 0.5;
4. each region vertex takes barycentric-interpolated weights from the nearest
   reference surface point (BVH, rest pose);
5. the region's total weight per vertex is kept and only redistributed, so weights
   on other bones and every vertex's total are unchanged;
6. if the median surface distance is above 15 % of the hips→head distance, the
   reference does not fit and **nothing is changed** (`weight_transfer.applied:
   false` plus the reason, and a warning). The export itself still succeeds.

If the reference fails to import (even part-way) or the transfer fails, the reference
objects are always removed and the export continues with the source weights. Writing is
transactional: each vertex's region weights are recorded before the first write, and a
failure part-way restores them exactly and deletes any vertex group the transfer created
(`weight_transfer.rolled_back: true`). If the cleanup or the restore itself cannot be
completed, the export fails: it never ships a half-transferred body.

Works on meshes with shape keys (no modifier is applied). The reference is staged in
its own folder of the job with the same checks as the asset, is part of the cache
key, and is deleted from the scene before export, so it never reaches the VRM.

Tested with capsule figures: a target whose thigh tops are bound 100 % to the hips,
and references with other bone names and ×1.8 scale. The test reads the weights back
from the exported `.vrm`: exactly the 8 thigh-top vertices become 50/50 hips/thigh.
**Not tested on real bodies yet:** whether 0.5 and 15 % are the right thresholds for
real packs is for the rig to show.

## `.mrbody` for Kaliv (one runtime ingress)

Decision (Anders, 2026-11-09, on ChatGPT's #1402 recommendation): Kaliv keeps one
runtime body ingress, `.mrbody` via `BodyRigRemoteAvatarSource`. A converted model
goes through that door; there is no second Unity load path.

`--mrbody` (`-MrBody` on the rig) also writes `<name>.mrbody` (`bodyrig/vrm_mrbody.py`).
`.mrbody` v1 is used as it is, with no contract change:

| payload | content |
|---|---|
| `avatar.vrm` | the exported VRM, checked with `avatar.validate_vrm1` |
| `bodyprint.json` | **only `shape`, measured from the model** in BodyRig's definitions: height from world-space mesh bounds (relative to 1.70 m), shoulder width = upper-arm joint span, hip width = pelvis width (hip-joint span / 0.66), arm/leg = summed bone lengths. No motion, expression or runtime values are invented |
| `provenance.json` | `synthetic_avatar: true`, stages `third_party_conversion` (+ `weight_transfer` when applied) + `mrbody_packaging`; no file names, no reference hashes |
| `thumbnail.png` | BodyRig's neutral placeholder silhouette |

**Identity boundary (#817).** The id is `asset-<24 hex of the avatar.vrm SHA-256>`, never
`bodyid-*`. It follows the packaged VRM bytes, not the input asset: the same input exported
with and without a weight reference gives two ids, and a cache hit gives the same id. The
provenance `source.kind` stays `user-supplied-local-media`: it is a constant in both
validators and in `contracts/provenance-v1.schema.json`, so the third-party origin is carried
by the `third_party_conversion` stage and the `asset-` id instead. ModelRig's Person Profile binds only `bodyid-*` bodies, so a converted model
can be shown but never bound to a person or used as the owner's twin. If the package cannot
be built and validated, the asset is FAILED; the `.vrm` stays.

Checked against **ModelRig's own validator** (`bodyrig/mrbody.py` on ModelRig `main`
`3cbd00f1d0c0`): an exported package with a weight transfer is accepted with
`body_id=asset-…` and `identity_content_id=None`.

## Add-ons (pinned)

`scripts/vrm_export_setup.py` installs exactly the commits in
`bodyrig/vrm_export.py` (`ADDON_PINS`):

- [VRM Add-on for Blender](https://github.com/saturday06/VRM-Addon-for-Blender), `src/io_scene_vrm` (MIT/GPL-3.0);
- [XNALara-io-Tools](https://github.com/Valerie-Bosco/XNALara-io-Tools), the maintained fork of XPS Tools (the
  original XNALaraMesh no longer works on Blender 4+/5), with its pinned submodules.

**Local patch to XNALara-io-Tools.** The fork sets `edit_bones[parentId]` for every
bone. XPS marks the root with parent `-1`, which Python reads as the *last* bone, so
every real XPS skeleton is imported with its root hanging off a leaf, and the humanoid
cannot be assigned. The setup patches that one line and records the patch hash in the
stamp. `test_xps_root_parent_patch` fails without it. To report upstream.

**Add-on network access.** The XPS fork ships an updater (ALXAddonUpdater). At the
pinned commit, loading the add-on only registers its classes; the download code
(`urlopen`) runs from a UI operator the worker never calls. On top of that: under
bubblewrap there is no network and the add-on folder is mounted read-only; in
process-only mode the environment carries a dead proxy.

## Timings (CI capsule figures, not the rig)

Measured 2026-11-09 in a Linux dev container, bpy 4.5.15, process-only isolation,
19-bone capsule figures (`bodyrig-vrm-export export ...`, wall clock per asset):

| asset | cold | cached repeat |
|---|---|---|
| `xps_pack.zip` (native XPS, relink + material fix) | 3.5 s | 1 ms |
| `xps_names.fbx` (4096 px texture, downscaled) | 4.5 s | 1 ms |
| `valve.blend`, `daz.blend` (name table) | 3.4 s | 1 ms |
| `anon.blend` (VRM add-on structure search) | 4.5 s | 1 ms |
| `no_armature.glb` (fails cleanly, not cached) | 1.2 s | 1.2 s |

About 1.2 s of every cold run is Blender start-up in a fresh bounded process. Real
packs (100k+ triangles, several 4K textures) will be slower; measure on the rig
before quoting numbers (#1393).

## Known limits

- **SFM `.mdl`/`.vtx`** need decompiling (Crowbar) first; not automated.
- **PMX (MMD)** is not supported.
- **Skin weights** are used as the model ships them, unless a weight reference is given
  (next section).
- **One worker at a time.** Parallel workers are possible with the same bounds; not
  needed until the rig numbers say so.
- **A-pose models:** the VRM add-on exports the rest pose; check T-pose handling on real
  packs.
