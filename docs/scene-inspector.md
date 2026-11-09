# Blender scene inspector (experimental, #1393)

A headless Blender worker that reads one locally staged 3D asset (BLEND, FBX, OBJ,
GLB, glTF) and writes a versioned scene contract, plus optional pose, depth and
normal conditioning images. This is the "isolated Blender inspection" step after
the file inventory (#1394), and before structural passes go to ModelRig image
and video generation (#2296).

- **State:** draft. Software-tested in CI on Linux and Windows. It has **not** been
  validated on the physical rig.
- **`production_activation`:** stays `false`.
- **`likeness_authority`:** always `false`. A scene inspection is never identity
  evidence for BodyPrint, `.mrbody` or Photoreal (#817).

## On the rig: WSL2 with bubblewrap (Anders' decision, 2026-11-09)

On the rig the inspector runs inside WSL2, isolated with bubblewrap. The source
folder and the output folder stay on Windows. The steps:

**1. One-time setup.** From the BodyRig checkout in PowerShell (re-runnable):

```powershell
.\setup-scene-inspector-wsl.ps1
```

This setup:
- installs `bubblewrap` and Python 3.11 in the default WSL distro (`-Distro` picks
  another one), using the deadsnakes PPA only when Ubuntu has no final 3.11;
- creates the hash-locked bpy venv in `~/.local/share/bodyrig/bpy-venv`;
- inspects a Blender-generated corpus under bubblewrap.

It ends with `SCENE-INSPECTOR-WSL: PASS` or `FAIL (<reason>)`.

If Ubuntu's AppArmor blocks user namespaces, the setup stops and explains why.
`-AllowUsernsSysctl` lets it set `kernel.apparmor_restrict_unprivileged_userns=0`
in that distro.

**2. Inspect assets.** Isolation is always bubblewrap and never falls back:

```powershell
.\run-scene-inspector-wsl.ps1 -Root C:\assets\staging -All -Out C:\assets\scene-out
.\run-scene-inspector-wsl.ps1 -Root C:\assets\staging -All -Out C:\assets\scene-bench -Bench -Runs 3
```

The cache (`~/.cache/bodyrig/scene-cache`) and the private staging copies
(`~/.cache/bodyrig/scene-work`) stay on the WSL ext4 disk.

**What the sandbox hides.** Inside it, Blender sees only:
- read-only system directories;
- the bpy venv;
- its own job directory.

It does not see:
- `/mnt/c` or any other Windows drive;
- the WSL home directory;
- the network;
- WSL interop with Windows programs;
- the GPU (`/dev/dxg`), because bubblewrap mounts a minimal `/dev`.

## Native Windows (without WSL)

Use **one** of the two runtimes below. Each is pinned to one version.

**Option 1: the Blender 4.5 LTS installer.**

```powershell
$blender = "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
bodyrig-scene-inspect inspect --root C:\assets\staging --all --out C:\assets\scene-out `
  --cache C:\assets\scene-cache --blender $blender --conditioning pose,depth,normal
```

**Option 2: the hash-locked `bpy` module, in its own Python 3.11 venv.** CI uses
this runtime.

```powershell
py -3.11 -m venv C:\BodyRig\bpy-venv
C:\BodyRig\bpy-venv\Scripts\python.exe -m pip install --require-hashes --no-deps -r requirements\blender-bpy.lock.txt
bodyrig-scene-inspect inspect --root C:\assets\staging --all --out C:\assets\scene-out `
  --cache C:\assets\scene-cache --bpy-python C:\BodyRig\bpy-venv\Scripts\python.exe --conditioning pose,depth,normal
```

**Measure cold and warm runs on the rig:**

```powershell
bodyrig-scene-inspect bench --root C:\assets\staging --all --out C:\assets\scene-bench `
  --bpy-python C:\BodyRig\bpy-venv\Scripts\python.exe --conditioning pose,depth,normal --runs 3
```

**Header metadata only (no Blender), for a first look within seconds:**

```powershell
bodyrig-scene-inspect inspect --root C:\assets\staging --all --out C:\assets\scene-out --cache C:\assets\scene-cache --minimum-only
```

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | Every asset was analyzed. |
| 1 | At least one asset `FAILED`; the others were still processed. |
| 2 | Setup error. |
| 3 | The time budget ran out before every asset was done. Run the same command again to continue. |

Keep `--root` and `--work-root` on local SSD, not on a network share.

## Time budget and speed verdicts

A run can never go on for days. Every `inspect` run has a total time budget,
`--budget` (`-Budget` in the WSL script), default `60m`. It takes values such as
`90s`, `15m`, `1h`, or `0` for no budget.

- No asset starts after the budget is used up. Those assets are `FAILED` with
  `budget_exhausted` and the message "not started".
- No Blender worker runs past the budget. The per-asset `--timeout` still applies
  inside it. An asset stopped by the budget keeps its metadata (`MINIMUM_READY`
  was written) and is `FAILED` with `budget_exhausted`, never reported as analyzed.
- A frame sequence (`--frames`) whose worker is stopped by `--timeout` or the
  budget keeps the frames it finished. They are copied to the asset's folder
  under their normal `f%06d_` names and listed in `scene.json` → `partial`, together
  with the sequence camera. A half-written frame is never kept, and neither is
  anything after a gap. The asset stays `FAILED` and the partial result is not
  cached. Re-running starts the sequence again: resuming at the first missing
  frame is not built yet.
- Everything that finished is kept and cached. Running the same command again
  serves those assets from the cache in milliseconds and spends the new budget on
  the rest. The exit code is 3 when the budget ran out.

Every run ends with one line per #1393 target, and `summary.json` (`slo`) holds
the same data:

```text
speed metadata      PASS      4 ms (target 5.0 s, n=9)
speed analysis      PASS     1.9 s (target 90.0 s, n=7)
speed first_usable  PASS     1.1 s (target 120.0 s, n=1)
speed cached        NOT MEASURED  (target 2.0 s)
```

| Line | What is measured | Target |
|---|---|---|
| `metadata` | p95 of `minimum_ready_at`, uncached assets | 5 s |
| `analysis` | p95 of `fully_analyzed_at`, uncached assets. An asset stopped by `--timeout` or the budget counts with its elapsed time, so a slow asset cannot drop out of the figure. | 30 s, or 90 s with conditioning (30 s inspection + 60 s pose/depth/normal) |
| `first_usable` | time from the start of the run until the first asset is usable: conditioning written, or analyzed when no conditioning was asked for. If nothing became usable, this is `FAIL` with the whole run time. | 120 s |
| `cached` | p95 total of cache hits | 2 s |

`summary.json` also has `first_result_ms` (the first `minimum_ready_at`,
`conditioning_ready_at` and `fully_analyzed_at` after the run started) and
`budget` (`seconds`, `not_reached`). `bench` prints the same verdicts from its
cold and warm runs.

A `PASS` is a measurement on the machine that ran it, and that machine is
recorded in `slo.machine`. Only a run on the physical rig validates the #1393
targets.

## States and files

Each asset gets `<out>/<asset>/scene.json`; its schema is in
`contracts/bodyrig-scene-inspection-v1.schema.json`.

| State | Meaning | Typical time |
|---|---|---|
| `DISCOVERED` | path contained in `--root`, no symlink/reparse point, supported format, hashed | ms |
| `SAFE_TO_INSPECT` | dependency closure resolved with strict relative references | ms |
| `MINIMUM_READY` | header metadata without Blender; `scene.json` written now. Metadata only: enough to list the asset, **not** proof that it can be used for image or video | ms |
| `FULLY_ANALYZED` | Blender scene: meshes, armatures/bones, shape keys, materials, images, animations, risk flags | seconds |
| `FAILED` | this asset only; `error.code` + `error.message`; the batch continues | |

**Milestones** in `timings_ms`:

| Key | When it is set |
|---|---|
| `minimum_ready_at` | metadata only |
| `conditioning_ready_at` | the pose, depth and normal files are written; the asset is usable for image or video conditioning |
| `fully_analyzed_at` | the scene contract is complete |

**Dependency closure.** Only what Blender needs is staged:

- glTF/GLB external `buffers` and `images`;
- the OBJ `mtllib` files.

A reference is rejected (`unsafe_reference`) if it has:

- a scheme or host;
- a query or fragment;
- a backslash or drive letter;
- an absolute path;
- `..`, including the percent-encoded `%2e%2e`;
- a symlink or reparse point anywhere on the path.

Such a reference **fails the asset before Blender starts** (fail closed), because
Blender would open whatever the reference names. This covers glTF/GLB `uri`s
and OBJ `mtllib`.

**Missing files** are a different case. They degrade the asset instead of
failing it:
- a missing glTF image or OBJ material library gives a warning;
- a missing glTF buffer fails the asset, because the geometry is incomplete.

**OBJ `mtllib` names.** One `mtllib` line can name several libraries, or one
name containing spaces. The whole text is tried first, then each name. The
inspector never stages texture files. A material library is staged only when
every texture statement in it names a plain in-folder file. A library with an
absolute, drive, UNC, `..` or scheme texture path is left out with a warning,
and Blender then uses default materials. So no texture outside the folder is
ever opened.

**FBX textures.** FBX files carry the artist's (often absolute) texture paths.
Inside the worker, every FBX image load is redirected to
`<staging>/<basename>` with no search, and becomes a placeholder when that file
is not staged. A test proves that the unguarded importer does read an outside
file, and that the guarded one does not.

**BLEND linked libraries** are reported in `scene.risk.linked_libraries`, not
staged. Blender opens them when it opens the file, which is one more reason the
rig uses WSL2 with bubblewrap: there, nothing outside the job directory exists.

**Cache and output folders are not path sources.** A cache entry is used only if
all of these hold:
- its key is a 64-character hex string;
- no path component from the cache root down to the entry is a link;
- it resolves inside the cache root;
- its file names are exactly the allowlisted outputs (`pose.json`, `pose.png`,
  `depth.png`, `normal.png`);
- each file matches its stored hash.

An output file that is a link is never written through (`unsafe_path`).

**Inventory hand-off (#1394).**
`bodyrig-scene-inspect inspect --root <inventory root> --inventory manifest.json ...`
runs exactly the assets a schema-2 inventory lists. Statuses map as follows:

| Inventory status | Inspector result |
|---|---|
| `ok` | proceeds |
| `degraded` | proceeds, and the inventory reasons become warnings |
| `rejected` | `FAILED` with `inventory_rejected`; Blender never starts |
| asset changed since the inventory, or not listed in it | `FAILED` with `inventory_mismatch` |

The inspector still computes and checks its own dependency closure; it does not
trust the inventory's. It records the dependencies the inventory listed but did
not stage (`inventory.dependencies_not_staged`), and it warns about staged
dependencies the inventory did not list.

**Conditioning outputs** (`--conditioning pose,openpose,depth,normal`) use one fixed
orthographic front camera, looking along +Y with Z up. It is framed on the
visible meshes at the first frame of the scene:

- `pose.json` and `pose.png`: every armature joint in world coordinates and
  pixel coordinates, with bones drawn as lines. This is a generic skeleton.
- `openpose.json` and `openpose.png`: the rig mapped to the 18-point OpenPose
  (COCO) body layout, as OpenPose JSON (`people[].pose_keypoints_2d`) and drawn
  in the usual ControlNet colours. The mapping goes by bone name and covers:
  - Mixamo (`mixamorig:LeftArm`);
  - Unreal (`upperarm_l`, `calf_r`);
  - Rigify (`DEF-upper_arm.L`);
  - VRM (`J_Bip_L_UpperArm`);
  - XPS (`arm left elbow`);
  - Biped (`Bip01 L UpperArm`).

  Toes, twist/roll/IK helpers and `_end` leaf bones are never used.
  The nose is approximated mid-head, at confidence 0.5. Ears are not mapped,
  and eyes are mapped only when the rig has eye bones. `bodyrig.armatures[].bones`
  shows which bone fed each joint, and `facing` says whether the figure faces the
  camera.

  **Generic chain names.** Some rigs number their limb joints instead of naming
  them, for example `arm_joint_L_1/2/3`, `leg_joint_R_1/2/3` and `b_LeftLeg01/02`.
  For these, a limb whose roles are not named specifically is filled in hierarchy
  order (upper arm, forearm, hand; thigh, shin, foot). With several neck bones
  and no head bone, the deepest neck bone stands in for the head. Each such
  choice is listed in `bones._approximated`.

  **Checked on real assets.** I ran the inspector locally on Khronos
  glTF-Sample-Assets models, which are not part of the repo:
  - **CesiumMan and RiggedFigure:** 14 body keypoints each, facing the camera.
  - **Fox:** a quadruped. It maps only partially, as expected, because OpenPose
    is a human layout.
  - **BrainStem:** its bones are only named `Node_N`, so nothing maps. A
    structural mapping that does not depend on bone names is a possible later
    step.

  **Hands.** When the rig has numbered finger bones, each hand also gets the
  21-point OpenPose hand layout: the wrist, then base to tip for the thumb,
  index, middle, ring and pinky. They are written as
  `hand_left_keypoints_2d` / `hand_right_keypoints_2d` and drawn ControlNet-style,
  with rainbow edges and blue points. Recognised finger names include
  `mixamorig:LeftHandIndex2`, `index_02_l`, `DEF-f_index.02.L`, `J_Bip_L_Little2`
  and `thumb_01_r`. Metacarpal and end bones are skipped.
  `bodyrig.armatures[].fingers` lists the bones used.
- `depth.png`: 16-bit grayscale, brighter means nearer, background 0.
- `normal.png`: 8-bit RGB camera-space normals (R = x right, G = y up, B = towards
  the camera). They are smooth normals interpolated from corner normals. The
  background is 0.

**Views** (`--view-yaw DEG`, or `-ViewYaw` on the rig): the camera orbits the
vertical axis. 0 is the front view, 90 the side and 180 the back.

- Depth, normals, pose and OpenPose all use that view. Normals stay in camera
  space for every view.
- OpenPose `facing` reports `camera`, `side` or `away`.
- The yaw is part of the cache key.
- At yaw 0 the output is byte-identical to before this option existed.

**Frame sequences for video conditioning** (`--frames START:END[:STEP]`, end
inclusive, at most 600 frames):

- Every chosen output is written once per frame as `f<index>_<name>` (index
  `000000` upwards). `conditioning.sequence` maps each index to its scene frame.
- One camera, framed on the union of all frames, is used for the whole sequence,
  so the image does not jump.
- The frame range is part of the cache key.
- On the rig: `run-scene-inspector-wsl.ps1 ... -Conditioning openpose,depth -Frames 1:120:2`.

The outputs come from ray casts against the evaluated meshes. No render engine
is used and no GPU is touched, so CPU inspection never needs the GPU lease.

## Speed

The #1393 targets are first usable output in ≤ 120 s and a cached repeat in
< 2 s. They are targets, not measured results on the rig. What this branch
measured (the `bench` command, Linux container with 2 vCPU, bpy 4.5.15, all
three conditioning outputs at 512²):

| Asset | Metadata ready | Conditioning ready, cold | Conditioning ready, cached |
|---|---|---|---|
| Generated sample (1.8 k triangles, 3 bones, 2 shape keys), five formats | 1–2 ms | p50 1.1 s, p95 1.3 s | p50 1 ms, p95 6 ms |
| Inventory hand-off: 9 assets (7 inspected, 2 rejected by the inventory), `--jobs 2`, bubblewrap | p95 4 ms | p50 1.1 s, p95 1.9 s | p95 5 ms |
| 510 k triangle GLB | — | about 5.2 s (import 1.6 s, conditioning 3.1 s) | — |

Real assets with large textures, FBX with many takes, or BLEND files with heavy
modifier stacks will be slower. Run `bench` on the rig against a representative
corpus before quoting any figure.

**How the cache works.** The key covers:

- the asset hash and the hashes of its staged dependencies;
- the worker script hash;
- the Blender version;
- the conditioning options and resolution.

File hashes are memoised by size and mtime; `--rehash` turns the memo off.
Only `FULLY_ANALYZED` results are cached. A cache entry whose files no longer
match their hashes is ignored. To clear the cache, delete the cache folder.

## Isolation: what is enforced and what is not

`--disable-autoexec` is **not** a sandbox. Each `scene.json` records the
isolation that was actually applied (`isolation`, `process.limits`).

**Always enforced, on every platform:**

- **Private staging copy.** It is re-hashed after copying (`source_changed` if
  the source moved under us) and deleted afterwards (`cleanup.staging_removed`).
- **Scrubbed environment.** Only `PATH` and a few OS variables pass through.
  `HOME`, `APPDATA`, `TEMP` and every `BLENDER_USER_*` directory point to empty
  folders inside the job directory. The proxy variables point to a dead local
  port. `CUDA_VISIBLE_DEVICES`, `HIP_VISIBLE_DEVICES` and `ROCR_VISIBLE_DEVICES`
  are empty.
- **Blender started without user content.** CLI runtime:
  `--background --factory-startup --disable-autoexec`, plus `--offline-mode`
  when this Blender build supports it, plus `-noaudio`. Module runtime:
  `python -I -B`. In both cases the worker resets to factory settings with an
  empty scene, forces auto-run off, and opens `.blend` files with
  `use_scripts=False`. Registered text blocks and scripted drivers therefore do
  not run. CI proves this with a generated `.blend` whose text block and driver
  would write a marker file. With auto-run enabled the marker appears; under the
  inspector it does not.
- **Bundled importers only.** No add-on is installed or enabled from the asset
  or from user folders.
- **Resource limits.** A wall-clock limit (`--timeout`), a memory limit
  (`--memory-gb`), and a kill of the whole process tree on either.

**Windows (Job Object).** The worker is created suspended, assigned to the job
and only then resumed. The job enforces:

- kill on close;
- a committed-memory limit;
- an active-process limit;
- below-normal priority;
- UI restrictions: no clipboard, and no desktop or display changes.

**Linux and WSL2 with bubblewrap** (`--isolation auto` or `--isolation bwrap`):

- The system directories and the Blender/Python install are mounted read-only.
- Only the job directory is writable.
- `/home`, `/root`, `/mnt` (including the Windows drives under WSL2) and the
  rest of `/tmp` are not visible.
- All namespaces are unshared, including the network.

**What cannot be sandboxed here, explicitly:**

- **File reads on Windows.** A Job Object does not restrict file-system reads.
  Blender runs as the user, so an FBX texture path or a `.blend` library link
  pointing at `C:\Users\...` can be opened. The inspector only reports such
  references (`images_outside_staging`, `linked_libraries`). The worker's output
  contains names and counts, never file contents. What reaches the file system
  is the staging copy and the output folder.
- **Network on Windows.** A Job Object does not restrict the network. The dead
  proxy and `--offline-mode` stop Blender's own online features. They do not
  stop a raw socket from code running inside the process.
- **Parser exploits.** A memory-corruption bug in a Blender importer would run
  with the user's rights on Windows, or inside the bubblewrap jail on Linux.
  Auto-run being off does not change that.
- **The kernel.** bubblewrap shares the kernel. There is no seccomp filter yet,
  and `/etc` is readable.
- **WSL2.** bubblewrap needs unprivileged user namespaces. Ubuntu 24.04 restricts
  these through AppArmor (`kernel.apparmor_restrict_unprivileged_userns`). If
  bubblewrap is unusable, `--isolation auto` falls back to `process-only` and
  says so; use `--isolation bwrap` to fail instead.
- **Disk use.** Disk use in the job directory is not capped.

**Options for V2:**

1. Add a seccomp filter to the bubblewrap profile.
2. On native Windows (the WSL2 path above is the rig default), use a dedicated
   low-privilege local account, plus an outbound Windows Firewall rule for that
   `blender.exe`. Setting this up needs admin rights once.
3. On native Windows, use an AppContainer launcher.

## What this does not do

- It does not parse licences or provenance. That is the #1394 inventory, and
  provenance is optional there.
- It does not edit, export or re-topologise assets.
- It does not map rigs to OpenPose and does not fit a body model.
- It does not render textured images.
- It does not activate anything in ModelRig. The #2296 hand-off stays
  default-off and is a separate change.
- It does not decide what a human figure may be used for. The adult and consent
  rules for the hand-off are decided in #1393 and #2296.
