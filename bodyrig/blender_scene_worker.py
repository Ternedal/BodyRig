"""Scene inspection that runs INSIDE Blender (``blender --python`` or the ``bpy`` module).

Standalone on purpose: ``bodyrig`` is not importable inside Blender's Python, so
this file imports nothing from it. The host side is ``bodyrig.scene_inspector``;
it stages the asset, scrubs the environment, bounds the process and validates
what this script writes. Nothing here is a sandbox. It only avoids the paths
that would execute content from the asset:

- the scene is reset to factory settings with an empty scene before import;
- ``.blend`` files are opened with ``use_scripts=False`` and the auto-run
  preference is forced off, so registered text blocks and Python drivers do
  not run; whether Blender blocked anything is reported, not hidden;
- only Blender's bundled importers are used (FBX, glTF, OBJ); no add-on is
  installed or enabled from the asset or from user directories.

Output: one JSON document (``--output``) under the ``bodyrig-scene-worker-v1``
contract, plus optional conditioning files next to it:

- ``pose.json`` and ``pose.png``: armature joints at the first frame, projected
  with the conditioning camera;
- ``depth.png``: 16-bit grayscale, brighter is nearer, background 0;
- ``normal.png``: 8-bit RGB camera-space normals (R=x right, G=y up,
  B=z towards the camera), background 0;
- ``openpose.json`` and ``openpose.png``: the rig mapped to the 18-point
  OpenPose (COCO) body layout by bone name (Mixamo, VRM, Rigify, Unreal, XPS
  and similar), in the OpenPose JSON format and drawn in the usual
  ControlNet colours.

With ``--frames START:END:STEP`` every output is written once per frame as
``f<index>_<name>`` (index 000000 upwards), with one camera framed on the
union of all frames, so a sequence can condition video without the camera
moving.

The conditioning camera is a fixed orthographic front view (looking along +Y,
Z up) framed on the union of the mesh bounds. Depth and normals come from
ray casts against the evaluated meshes, so no render engine and no GPU are
involved.
"""

from __future__ import annotations

import argparse
import hashlib
import re as _re
import json
import math
import os
import re
import struct
import sys
import time
import traceback
import zlib

import bpy  # noqa: F401  (provided by Blender)

CONTRACT = "bodyrig-scene-worker-v1"
MAX_LISTED_BONES = 2000
MAX_LISTED_ITEMS = 5000
_BONE_PATH = re.compile(r'^pose\.bones\["((?:[^"\\]|\\.)*)"\]')


def hard_exit(code: int) -> None:
    """Exit without Blender's C-level teardown, on every platform.

    The bpy module can hang in its teardown after some importers ran (seen
    with bpy 4.5.15 on Linux), and ``os._exit`` crashes it on Windows (exit
    139 on the CI runner, during DLL detach). TerminateProcess on our own
    process skips DLL detach; ``os._exit`` is the POSIX equivalent.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        import ctypes

        # (HANDLE)-1 is the current-process pseudo-handle. It must be passed as a full
        # pointer: an int argument is truncated to 32 bits and the call fails silently.
        ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), ctypes.c_uint(int(code)))
    os._exit(int(code))


def _progress(out_dir: str, stage: str, done: int = 0, total: int = 0, camera: dict | None = None) -> None:
    """Atomically publish where the worker is, for the host to relay (best effort).

    ``frames_done = k`` is published before frame ``k`` starts, so frames below ``k`` are
    complete: a stopped run keeps them (with the sequence camera).
    """
    try:
        partial = os.path.join(out_dir, ".progress.json.partial")
        state = {"stage": stage, "frames_done": done, "frames_total": total}
        if camera is not None:
            state["camera"] = camera
        with open(partial, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(partial, os.path.join(out_dir, "progress.json"))
    except OSError:
        pass


def _ms(start: float) -> int:
    return int(round((time.perf_counter() - start) * 1000))


def _r(value: float, digits: int = 6) -> float:
    value = float(value)
    if not math.isfinite(value):
        return 0.0
    return round(value, digits)


def _vec(values) -> list[float]:
    return [_r(v) for v in values]


def _args(argv: list[str]) -> argparse.Namespace:
    rest = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser(prog="blender_scene_worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--format", required=True, choices=("blend", "fbx", "obj", "glb", "gltf"))
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--conditioning", default="")
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument("--frames", default="")
    parser.add_argument("--yaw", type=float, default=0.0)
    parser.add_argument("--resume-from", type=int, default=0)
    parser.add_argument("--resume-camera-sha256", default="")
    return parser.parse_args(rest)


def camera_sha256(camera: dict) -> str:
    """The camera's identity for resuming a sequence: the host has frames rendered with exactly it."""
    return hashlib.sha256(json.dumps(camera, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _inside(path: str, root: str) -> bool:
    try:
        path = os.path.normcase(os.path.realpath(path))
        root = os.path.normcase(os.path.realpath(root))
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives on Windows
        return False


def _harden_preferences() -> dict:
    prefs = bpy.context.preferences
    prefs.filepaths.use_scripts_auto_execute = False
    return {
        "autoexec_enabled": bool(prefs.filepaths.use_scripts_auto_execute),
        "online_access": bool(getattr(bpy.app, "online_access", False)),
    }


def _bundled_importer(module: str) -> dict:
    import addon_utils

    loaded_default, loaded_state = addon_utils.check(module)
    if not loaded_state:
        addon_utils.enable(module, default_set=False, persistent=False)
    for mod in addon_utils.modules(refresh=False):
        if mod.__name__ == module:
            return {"module": module, "version": ".".join(str(v) for v in mod.bl_info.get("version", ())),
                    "path_is_bundled": not _inside(mod.__file__, bpy.utils.user_resource("SCRIPTS"))}
    raise RuntimeError(f"bundled importer {module} not found")


def _confine_fbx_images(staging_root: str) -> dict:
    """Make the FBX importer's image loads stay inside the staging root.

    FBX files carry texture paths that are often absolute (the artist's disk)
    and the importer tries them as given, then searches. Every load is
    redirected to ``<staging root>/<basename>`` with no search; a texture that
    is not staged becomes a placeholder, so nothing outside is ever opened.
    Embedded textures are unaffected (they are packed from the FBX itself).
    """
    from bpy_extras import image_utils

    original = image_utils.load_image
    report = {"redirected": 0, "placeholders": 0}

    def confined(imagepath, dirname="", place_holder=False, recursive=False, *args, **kwargs):
        name = os.path.basename(str(imagepath).replace("\\", "/")) or "missing"
        local = os.path.join(staging_root, name)
        if os.path.normpath(os.path.join(dirname or "", str(imagepath))) != os.path.normpath(local):
            report["redirected"] += 1
        if not os.path.isfile(local):
            report["placeholders"] += 1
        return original(local, dirname="", place_holder=True, recursive=False, *args, **kwargs)

    image_utils.load_image = confined
    return report


def _import(path: str, fmt: str, staging_root: str) -> dict:
    if fmt == "blend":
        bpy.ops.wm.open_mainfile(filepath=path, load_ui=False, use_scripts=False)
        return {"module": "wm.open_mainfile", "use_scripts": False}
    if fmt == "fbx":
        info = _bundled_importer("io_scene_fbx")
        info["images"] = _confine_fbx_images(staging_root)
        bpy.ops.import_scene.fbx(filepath=path, use_image_search=False)
        return info
    if fmt in ("glb", "gltf"):
        info = _bundled_importer("io_scene_gltf2")
        bpy.ops.import_scene.gltf(filepath=path)
        return info
    bpy.ops.wm.obj_import(filepath=path)
    return {"module": "wm.obj_import"}


def _fcurves(action) -> list:
    curves = getattr(action, "fcurves", None)
    if curves is not None:
        try:
            return list(curves)
        except (RuntimeError, TypeError):
            pass
    out = []
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for bag in getattr(strip, "channelbags", ()):
                out.extend(bag.fcurves)
    return out


def _world_bounds(obj, depsgraph):
    from mathutils import Vector

    evaluated = obj.evaluated_get(depsgraph)
    corners = [evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box]
    return ([min(c[i] for c in corners) for i in range(3)], [max(c[i] for c in corners) for i in range(3)])


def _bone_shapes(objects) -> set[str]:
    shapes = set()
    for obj in objects:
        if obj.type == "ARMATURE" and obj.pose is not None:
            shapes.update(bone.custom_shape.name for bone in obj.pose.bones if bone.custom_shape is not None)
    return shapes


def _renderable(obj, bone_shapes: set[str]) -> bool:
    """Visible in the view layer and not a bone display shape (glTF/FBX importers add those)."""
    try:
        visible = obj.visible_get()
    except RuntimeError:
        visible = not obj.hide_get()
    return bool(visible) and not obj.hide_render and obj.name not in bone_shapes


def _armature_of(obj):
    for modifier in obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object is not None:
            return modifier.object.name
    if obj.parent is not None and obj.parent.type == "ARMATURE":
        return obj.parent.name
    return None


def _collect(staging_root: str) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects = sorted(scene.objects, key=lambda o: o.name)

    by_type: dict[str, int] = {}
    for obj in objects:
        by_type[obj.type] = by_type.get(obj.type, 0) + 1

    bone_shapes = _bone_shapes(objects)
    meshes = []
    bounds_min = [math.inf] * 3
    bounds_max = [-math.inf] * 3
    for obj in objects:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        mesh.calc_loop_triangles()
        low, high = _world_bounds(obj, depsgraph)
        renderable = _renderable(obj, bone_shapes)
        if renderable:
            for i in range(3):
                bounds_min[i] = min(bounds_min[i], low[i])
                bounds_max[i] = max(bounds_max[i], high[i])
        keys = [block.name for block in mesh.shape_keys.key_blocks] if mesh.shape_keys else []
        meshes.append({
            "object": obj.name,
            "mesh": mesh.name,
            "renderable": renderable,
            "bone_shape": obj.name in bone_shapes,
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "faces": len(mesh.polygons),
            "triangles": len(mesh.loop_triangles),
            "uv_layers": [layer.name for layer in mesh.uv_layers],
            "vertex_groups": len(obj.vertex_groups),
            "shape_keys": keys,
            "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
            "armature": _armature_of(obj),
            "modifiers": [modifier.type for modifier in obj.modifiers],
            "bounds_world": {"min": _vec(low), "max": _vec(high)},
        })

    armatures = []
    for obj in objects:
        if obj.type != "ARMATURE":
            continue
        bones = list(obj.data.bones)
        listed = [{
            "name": bone.name,
            "parent": bone.parent.name if bone.parent else None,
            "head": _vec(obj.matrix_world @ bone.head_local),
            "tail": _vec(obj.matrix_world @ bone.tail_local),
            "deform": bool(bone.use_deform),
        } for bone in bones[:MAX_LISTED_BONES]]
        armatures.append({
            "object": obj.name,
            "armature": obj.data.name,
            "bone_count": len(bones),
            "deform_bones": sum(1 for bone in bones if bone.use_deform),
            "root_bones": sorted(bone.name for bone in bones if bone.parent is None),
            "bones": listed,
            "bones_truncated": len(bones) > MAX_LISTED_BONES,
        })

    used_actions: dict[str, list[str]] = {}
    for obj in objects:
        holders = [obj]
        if obj.type == "MESH" and obj.data.shape_keys is not None:
            holders.append(obj.data.shape_keys)
        for holder in holders:
            data = holder.animation_data
            if data is not None and data.action is not None:
                used_actions.setdefault(data.action.name, []).append(obj.name)
            if data is not None:
                for track in data.nla_tracks:
                    for strip in track.strips:
                        if strip.action is not None:
                            used_actions.setdefault(strip.action.name, []).append(obj.name)

    animations = []
    for action in sorted(bpy.data.actions, key=lambda a: a.name):
        curves = _fcurves(action)
        bones = set()
        shape_key_curves = 0
        for curve in curves:
            match = _BONE_PATH.match(curve.data_path)
            if match:
                bones.add(match.group(1))
            elif curve.data_path.startswith("key_blocks["):
                shape_key_curves += 1
        start, end = action.frame_range
        animations.append({
            "name": action.name,
            "frame_range": [_r(start, 3), _r(end, 3)],
            "fcurves": len(curves),
            "bones_animated": len(bones),
            "shape_key_fcurves": shape_key_curves,
            "used_by": sorted(set(used_actions.get(action.name, []))),
        })

    materials = []
    for material in sorted(bpy.data.materials, key=lambda m: m.name):
        if material.users == 0:
            continue
        images = []
        if material.use_nodes and material.node_tree is not None:
            images = sorted({node.image.name for node in material.node_tree.nodes
                             if node.type == "TEX_IMAGE" and node.image is not None})
        materials.append({"name": material.name, "uses_nodes": bool(material.use_nodes), "images": images})

    images = []
    outside = 0
    for image in sorted(bpy.data.images, key=lambda i: i.name):
        if image.type != "IMAGE":
            continue
        packed = image.packed_file is not None
        entry = {"name": image.name, "source": image.source, "packed": packed}
        if not packed and image.filepath:
            absolute = bpy.path.abspath(image.filepath, library=image.library)
            inside = _inside(absolute, staging_root)
            entry["file_in_staging"] = inside
            entry["file_present"] = inside and os.path.isfile(absolute)
            if not inside:
                outside += 1
        images.append(entry)
    if outside:
        warnings.append(f"{outside} image reference(s) point outside the staging root; they were not staged")

    libraries = []
    for library in bpy.data.libraries:
        absolute = bpy.path.abspath(library.filepath)
        libraries.append({"name": library.name, "in_staging": _inside(absolute, staging_root)})
    if libraries:
        warnings.append(f"{len(libraries)} linked .blend librar(y/ies); linked data was not staged")

    scripted_drivers = 0
    for obj in objects:
        holders = [obj, obj.data] if obj.data is not None else [obj]
        if obj.type == "MESH" and obj.data.shape_keys is not None:
            holders.append(obj.data.shape_keys)
        for holder in holders:
            data = getattr(holder, "animation_data", None)
            if data is None:
                continue
            scripted_drivers += sum(1 for fcurve in data.drivers if fcurve.driver.type == "SCRIPTED")

    finite = all(math.isfinite(v) for v in bounds_min + bounds_max)
    renderable = [m for m in meshes if m["renderable"]]
    totals = {
        "objects": len(objects),
        "meshes": len(renderable),
        "helper_meshes": len(meshes) - len(renderable),
        "vertices": sum(m["vertices"] for m in renderable),
        "triangles": sum(m["triangles"] for m in renderable),
        "armatures": len(armatures),
        "bones": sum(a["bone_count"] for a in armatures),
        "shape_keys": sum(max(0, len(m["shape_keys"]) - 1) for m in renderable),
        "materials": len(materials),
        "images": len(images),
        "actions": len(animations),
    }
    return {
        "scene_name": scene.name,
        "scenes_in_file": sorted(s.name for s in bpy.data.scenes),
        "units": {"system": scene.unit_settings.system, "scale_length": _r(scene.unit_settings.scale_length)},
        "frame_range": [scene.frame_start, scene.frame_end],
        "fps": _r(scene.render.fps / (scene.render.fps_base or 1.0), 4),
        "objects_by_type": dict(sorted(by_type.items())),
        "totals": totals,
        "bounds_world": {"min": _vec(bounds_min), "max": _vec(bounds_max)} if finite else None,
        "meshes": meshes[:MAX_LISTED_ITEMS],
        "armatures": armatures,
        "animations": animations[:MAX_LISTED_ITEMS],
        "materials": materials[:MAX_LISTED_ITEMS],
        "images": images[:MAX_LISTED_ITEMS],
        "risk": {
            "embedded_texts": len(bpy.data.texts),
            "scripted_drivers": scripted_drivers,
            "autoexec_blocked": bool(getattr(bpy.app, "autoexec_fail", False)),
            "autoexec_blocked_reason": str(getattr(bpy.app, "autoexec_fail_message", "") or "")[:500],
            "linked_libraries": libraries,
            "images_outside_staging": outside,
        },
    }, warnings


# --- conditioning -------------------------------------------------------------------

def _png(path: str, width: int, height: int, rows: bytes, *, color_type: int, bit_depth: int) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    with open(path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def _rows(array, np) -> bytes:
    """PNG scanlines (filter type 0) from a uint8 array shaped (height, ...)."""
    height = array.shape[0]
    flat = array.reshape(height, -1)
    filtered = np.zeros((height, flat.shape[1] + 1), dtype=np.uint8)
    filtered[:, 1:] = flat
    return filtered.tobytes()


def _camera(bounds: dict, resolution: int, yaw_deg: float = 0.0) -> dict:
    """Orthographic camera orbiting the subject around Z by ``yaw_deg`` (0 = front, looking along +Y)."""
    low, high = bounds["min"], bounds["max"]
    center = [(low[i] + high[i]) / 2.0 for i in range(3)]
    theta = math.radians(yaw_deg)
    right = [math.cos(theta), math.sin(theta), 0.0]
    forward = [-math.sin(theta), math.cos(theta), 0.0]
    up = [0.0, 0.0, 1.0]
    corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]

    def extent(axis):
        values = [sum((corner[i] - center[i]) * axis[i] for i in range(3)) for corner in corners]
        return min(values), max(values)

    r_low, r_high = extent(right)
    u_low, u_high = extent(up)
    f_low, f_high = extent(forward)
    scale = max(r_high - r_low, u_high - u_low) * 1.1 or 1.0
    start = f_low - 1.0  # rays start one unit in front of the subject, along -forward
    return {
        "type": "orthographic",
        "view": "front" if yaw_deg == 0 else f"yaw {yaw_deg:g}",
        "yaw_deg": _r(yaw_deg, 3),
        "right": _vec(right),
        "forward": _vec(forward),
        "up": up,
        "center": _vec(center),
        "ortho_scale": _r(scale),
        "origin_offset": _r(start),
        "origin_y": _r(center[1] + start * forward[1]),
        "max_distance": _r(max(f_high - f_low, 1e-6) + 2.0),
        "resolution": [resolution, resolution],
        "pixel_origin": "top-left",
    }


def _project(camera: dict, point) -> list[float]:
    scale = camera["ortho_scale"]
    width, height = camera["resolution"]
    center, right, up = camera["center"], camera["right"], camera["up"]
    delta = [point[i] - center[i] for i in range(3)]
    across = sum(delta[i] * right[i] for i in range(3))
    vertical = sum(delta[i] * up[i] for i in range(3))
    u = (across + scale / 2.0) / scale * width
    v = (scale / 2.0 - vertical) / scale * height
    return [_r(u, 3), _r(v, 3)]


def _line(canvas, a, b, value) -> None:
    (x0, y0), (x1, y1) = a, b
    steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    height, width = canvas.shape[:2]
    for i in range(steps + 1):
        t = i / steps
        x = int(round(x0 + (x1 - x0) * t))
        y = int(round(y0 + (y1 - y0) * t))
        if 0 <= x < width and 0 <= y < height:
            canvas[y, x] = value


def _pose(out_dir: str, camera: dict, np, prefix: str = "") -> dict:
    scene = bpy.context.scene
    width, height = camera["resolution"]
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    armatures = []
    for obj in sorted(scene.objects, key=lambda o: o.name):
        if obj.type != "ARMATURE":
            continue
        joints = []
        for pose_bone in obj.pose.bones:
            head = obj.matrix_world @ pose_bone.head
            tail = obj.matrix_world @ pose_bone.tail
            uv_head, uv_tail = _project(camera, head), _project(camera, tail)
            joints.append({
                "bone": pose_bone.name,
                "parent": pose_bone.parent.name if pose_bone.parent else None,
                "head_world": _vec(head),
                "tail_world": _vec(tail),
                "head_px": uv_head,
                "tail_px": uv_tail,
                "in_frame": 0 <= uv_head[0] < width and 0 <= uv_head[1] < height,
            })
            _line(canvas, uv_head, uv_tail, (255, 255, 255))
            x, y = int(uv_head[0]), int(uv_head[1])
            canvas[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = (255, 64, 64)
        armatures.append({"object": obj.name, "joints": joints[:MAX_LISTED_BONES]})
    document = {"frame": scene.frame_current, "camera": camera, "armatures": armatures}
    with open(os.path.join(out_dir, prefix + "pose.json"), "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
    _png(os.path.join(out_dir, prefix + "pose.png"), width, height, _rows(canvas, np), color_type=2, bit_depth=8)
    return {"armatures": len(armatures), "joints": sum(len(a["joints"]) for a in armatures)}


def _world_triangles(np):
    """All evaluated mesh triangles in world space, with per-corner normals when available."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    vertices, triangles, corner_normals = [], [], []
    offset = 0
    smooth = True
    objects = list(bpy.context.scene.objects)
    bone_shapes = _bone_shapes(objects)
    for obj in objects:
        if obj.type != "MESH" or not _renderable(obj, bone_shapes):
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            count_v, count_t = len(mesh.vertices), len(mesh.loop_triangles)
            if count_t == 0:
                continue
            matrix = np.array(evaluated.matrix_world, dtype=np.float64)
            co = np.empty(count_v * 3, dtype=np.float64)
            mesh.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
            tri = np.empty(count_t * 3, dtype=np.int64)
            mesh.loop_triangles.foreach_get("vertices", tri)
            vertices.append(co)
            triangles.append(tri.reshape(-1, 3) + offset)
            offset += count_v
            normals = None
            if smooth and hasattr(mesh, "corner_normals"):
                loops = np.empty(count_t * 3, dtype=np.int64)
                mesh.loop_triangles.foreach_get("loops", loops)
                corner = np.empty(len(mesh.loops) * 3, dtype=np.float64)
                mesh.corner_normals.foreach_get("vector", corner)
                normal_matrix = np.linalg.inv(matrix[:3, :3]).T
                normals = corner.reshape(-1, 3)[loops] @ normal_matrix.T
                normals = normals.reshape(-1, 3, 3)
            if normals is None:
                smooth = False
            else:
                corner_normals.append(normals)
        finally:
            evaluated.to_mesh_clear()
    if not vertices:
        return None
    return (np.concatenate(vertices), np.concatenate(triangles),
            np.concatenate(corner_normals) if smooth and corner_normals else None)


def coverage_mask(verts, tris, camera: dict, np):
    """Pixels whose ray can hit a triangle: a conservative superset, so casting only these is exact.

    An orthographic ray through a pixel centre hits a triangle only if that centre lies inside
    the triangle's projection on the image plane, so inside its projected bounding box. The boxes
    are widened by one pixel plus a float32 error bound (the BVH works in float32) and
    accumulated in a summed-area table. Pixels outside every box are misses without a ray cast;
    _depth_normal also casts the ring just outside the mask and falls back to every pixel if
    any of those rays hits.
    """
    width, height = camera["resolution"]
    scale = camera["ortho_scale"]
    step = scale / width
    left = -scale / 2.0 + step / 2.0
    top = scale / 2.0 - step / 2.0
    rel = verts - np.asarray(camera["center"], dtype=np.float64)
    px = (rel @ np.asarray(camera["right"], dtype=np.float64) - left) / step
    py = (top - rel @ np.asarray(camera["up"], dtype=np.float64)) / step
    magnitude = float(np.abs(verts).max()) + float(np.abs(np.asarray(camera["center"])).max()) if len(verts) else 0.0
    margin = 1 + int(math.ceil(4.0 * magnitude * 2.0 ** -23 / step))
    tx, ty = px[tris], py[tris]
    c0 = np.floor(tx.min(axis=1)).astype(np.int64) - margin
    c1 = np.ceil(tx.max(axis=1)).astype(np.int64) + margin
    r0 = np.floor(ty.min(axis=1)).astype(np.int64) - margin
    r1 = np.ceil(ty.max(axis=1)).astype(np.int64) + margin
    keep = (c1 >= 0) & (c0 <= width - 1) & (r1 >= 0) & (r0 <= height - 1) & np.isfinite(tx).all(axis=1) \
        & np.isfinite(ty).all(axis=1)
    size = (height + 1) * (width + 1)
    acc = np.zeros(size, dtype=np.int64)
    if keep.any():
        c0, c1 = np.clip(c0[keep], 0, width - 1), np.clip(c1[keep], 0, width - 1)
        r0, r1 = np.clip(r0[keep], 0, height - 1), np.clip(r1[keep], 0, height - 1)
        stride = width + 1
        corners = np.concatenate([r0 * stride + c0, r0 * stride + c1 + 1, (r1 + 1) * stride + c0,
                                  (r1 + 1) * stride + c1 + 1])
        signs = np.repeat(np.array([1, -1, -1, 1], dtype=np.int64), len(c0))
        acc = np.bincount(corners, weights=signs, minlength=size).astype(np.int64)
    return acc.reshape(height + 1, width + 1).cumsum(axis=0).cumsum(axis=1)[:height, :width] > 0


def _ring(mask, np):
    """Pixels next to the mask (8-neighbourhood) but not in it."""
    grown = mask.copy()
    grown[1:, :] |= mask[:-1, :]
    grown[:-1, :] |= mask[1:, :]
    grown[:, 1:] |= grown[:, :-1].copy()
    grown[:, :-1] |= grown[:, 1:].copy()
    return grown & ~mask


def _depth_normal(out_dir: str, camera: dict, kinds: set, np, prefix: str = "") -> dict:
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    data = _world_triangles(np)
    if data is None:
        return {"skipped": "no visible mesh"}
    verts, tris, corner_normals = data
    tree = BVHTree.FromPolygons(verts.tolist(), tris.tolist(), all_triangles=True)
    width, height = camera["resolution"]
    scale = camera["ortho_scale"]
    center, right, up, forward = camera["center"], camera["right"], camera["up"], camera["forward"]
    start = camera["origin_offset"]
    max_distance = camera["max_distance"]
    direction = Vector(forward)
    base = [center[i] + forward[i] * start for i in range(3)]
    step = scale / width
    left = -scale / 2.0 + step / 2.0
    top = scale / 2.0 - step / 2.0
    # One flat comprehension, results gathered once: per-pixel numpy writes inside the
    # loop cost more than the ray casts themselves (measured on a 510k-triangle mesh).
    # Rays are cast only where coverage_mask says a hit is possible; every other pixel is a
    # miss either way, so the images are identical to casting every pixel.
    ray_cast = tree.ray_cast
    def cast_pixels(pixels):
        # The same float64 operations, in the same order, as the per-pixel origin of a full cast.
        col_term = left + (pixels % width) * step
        row_term = top - (pixels // width) * step
        axes = [((base[i] + right[i] * col_term) + up[i] * row_term).tolist() for i in range(3)]
        return [ray_cast(origin, direction, max_distance) for origin in zip(*axes)]

    mask = coverage_mask(np.asarray(verts, dtype=np.float32).astype(np.float64), tris, camera, np)
    ring = np.flatnonzero(_ring(mask, np))
    if any(cast[0] is not None for cast in cast_pixels(ring)):
        mask[:] = True  # the bound was not enough here: cast every pixel
    pixels = np.flatnonzero(mask)
    covered = pixels.tolist()
    casts = cast_pixels(pixels)
    flat_hits = [covered[i] for i, cast in enumerate(casts) if cast[0] is not None]
    hit_casts = [cast for cast in casts if cast[0] is not None]
    distance = np.full(height * width, np.nan)
    hit_index = np.full(height * width, -1, dtype=np.int64)
    hit_point = np.zeros((height * width, 3))
    face_normal = np.zeros((height * width, 3))
    if flat_hits:
        chosen = np.array(flat_hits, dtype=np.int64)
        distance[chosen] = [cast[3] for cast in hit_casts]
        hit_index[chosen] = [cast[2] for cast in hit_casts]
        hit_point[chosen] = [tuple(cast[0]) for cast in hit_casts]
        face_normal[chosen] = [tuple(cast[1]) for cast in hit_casts]
    distance = distance.reshape(height, width)
    hit_index = hit_index.reshape(height, width)
    hit_point = hit_point.reshape(height, width, 3)
    face_normal = face_normal.reshape(height, width, 3)
    hits = ~np.isnan(distance)
    result = {"hit_pixels": int(hits.sum()), "pixels": width * height,
              "normals": "smooth" if corner_normals is not None else "flat"}
    if "depth" in kinds:
        depth = np.zeros((height, width), dtype=np.uint16)
        if hits.any():
            near, far = float(distance[hits].min()), float(distance[hits].max())
            span = max(far - near, 1e-9)
            depth[hits] = np.round((1.0 - 0.9 * (distance[hits] - near) / span) * 65535).astype(np.uint16)
            result["depth_range_world"] = [_r(near), _r(far)]
        _png(os.path.join(out_dir, prefix + "depth.png"), width, height, _rows(depth.astype(">u2").view(np.uint8), np),
             color_type=0, bit_depth=16)
    if "normal" in kinds:
        normals = face_normal.copy()
        if corner_normals is not None and hits.any():
            idx = hit_index[hits]
            a, b, c = (verts[tris[idx, k]] for k in range(3))
            p = hit_point[hits]
            v0, v1, v2 = b - a, c - a, p - a
            d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
            d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
            denom = np.where(np.abs(d00 * d11 - d01 * d01) < 1e-20, 1e-20, d00 * d11 - d01 * d01)
            w1 = (d11 * d20 - d01 * d21) / denom
            w2 = (d00 * d21 - d01 * d20) / denom
            w0 = 1.0 - w1 - w2
            corners = corner_normals[idx]
            n = corners[:, 0] * w0[:, None] + corners[:, 1] * w1[:, None] + corners[:, 2] * w2[:, None]
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
            normals[hits] = n
        # camera space: x = right, y = up, z = towards the camera (front view: world x, world z, -world y)
        basis = np.array([camera["right"], camera["up"], [-v for v in camera["forward"]]], dtype=np.float64)
        camera_space = normals @ basis.T  # x right, y up, z towards the camera
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        rgb[hits] = np.clip(np.round((camera_space[hits] + 1.0) * 0.5 * 255.0), 0, 255).astype(np.uint8)
        _png(os.path.join(out_dir, prefix + "normal.png"), width, height, _rows(rgb, np), color_type=2, bit_depth=8)
    return result


# --- OpenPose (COCO-18) from bone names ------------------------------------------------------

OPENPOSE_NAMES = ("nose", "neck", "r_shoulder", "r_elbow", "r_wrist", "l_shoulder", "l_elbow", "l_wrist",
                  "r_hip", "r_knee", "r_ankle", "l_hip", "l_knee", "l_ankle", "r_eye", "l_eye", "r_ear", "l_ear")
# The 17 limbs and 18 colours of the usual OpenPose/ControlNet body drawing (1-based keypoint pairs).
OPENPOSE_LIMBS = ((2, 3), (2, 6), (3, 4), (4, 5), (6, 7), (7, 8), (2, 9), (9, 10), (10, 11), (2, 12), (12, 13),
                  (13, 14), (2, 1), (1, 15), (15, 17), (1, 16), (16, 18))
OPENPOSE_COLOURS = ((255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0),
                    (0, 255, 0), (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255),
                    (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85))
_NOISE_TOKENS = {"mixamorig", "mixamorig1", "mixamorig2", "def", "org", "mch", "j", "bip", "bip01", "bip001",
                 "cc", "base", "valvebiped", "jnt", "bn", "b", "c", "center"}
_EXCLUDE_TOKENS = {"index", "middle", "ring", "pinky", "little", "thumb", "finger", "toe", "toes", "end", "nub",
                   "twist", "roll", "ik", "fk", "pole", "target", "ctrl", "control", "tip", "top", "share",
                   "bend", "helper", "jiggle", "breast", "hair", "skirt"}


def classify_bone(name: str) -> tuple:
    """(role, side) for a bone name, or (None, None). Pure; no Blender needed.

    Roles: clavicle, upperarm, forearm, hand, thigh, shin, foot, neck, head, eye,
    plus "armchain"/"legchain" for generic numbered limb chains such as
    ``arm_joint_L_2`` or ``b_LeftLeg01`` (assigned by hierarchy order later).
    Side: "L", "R" or None. Fingers, toes, twist/roll/IK helpers and leaf
    ("_end", "nub") bones are never mapped.
    """
    spaced = _re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[a-z])(?=[0-9])", " ", str(name))
    tokens = [t for t in _re.split(r"[^a-z0-9]+", spaced.lower()) if t]
    side = None
    core = []
    numbers = []
    for token in tokens:
        if token in ("left", "l"):
            side = side or "L"
        elif token in ("right", "r"):
            side = side or "R"
        elif token.isdigit():
            numbers.append(int(token))
        elif token not in _NOISE_TOKENS:
            core.append(token)
    if not core or _EXCLUDE_TOKENS & set(core):
        return None, None
    joined = "".join(core)
    words = set(core)
    if "wrist" in joined or joined == "hand":
        role = "hand"
    elif "forearm" in joined or "lowerarm" in joined or "elbow" in joined:
        role = "forearm"
    elif joined == "armshoulder" or joined == "shoulder" and numbers[:1] in ([1], [2]) and len(tokens) > 2:
        role = "upperarm" if numbers and numbers[0] == 2 else "clavicle"  # XPS "arm left shoulder 1/2"
    elif "upperarm" in joined or "uparm" in joined or joined == "arm":
        role = "upperarm"
    elif "clavicle" in joined or joined == "shoulder":
        role = "clavicle"
    elif "upleg" in joined or "thigh" in joined or "upperleg" in joined:
        role = "thigh"
    elif "calf" in joined or "shin" in joined or "lowerleg" in joined or "knee" in joined or (joined == "leg" and not numbers):
        role = "shin"
    elif joined == "foot" or "ankle" in joined or joined.startswith("foot"):
        role = "foot"
    elif joined.startswith("neck") or "neck" in words:
        role = "neck"
    elif joined.startswith("head") or "head" in words:
        role = "head"
    elif "eye" in joined:
        role = "eye"
    elif "arm" in words:
        role = "armchain"  # "arm_joint_L_2", "Skeleton_arm_joint_R__3_"
    elif "leg" in words:
        role = "legchain"  # "leg_joint_L_1", "b_LeftLeg01"
    else:
        return None, None
    if role in ("neck", "head"):
        return role, None
    return (role, side) if side else (None, None)


FINGERS = ("thumb", "index", "middle", "ring", "pinky")
# OpenPose hand: 0 wrist, then 4 points per finger (base joint .. tip) in this finger order.
HAND_EDGES = tuple((0 if j == 0 else 1 + 4 * f + j - 1, 1 + 4 * f + j) for f in range(5) for j in range(4))


def classify_finger(name: str) -> tuple:
    """(finger, segment, side) for a numbered finger bone, or (None, None, None). Pure; no Blender.

    Mixamo ``LeftHandIndex2``, Unreal ``index_02_l``, Rigify ``DEF-f_index.02.L``,
    VRM ``J_Bip_L_Index2``, ``thumb_01_r``. Metacarpals, end/nub bones and
    helpers are never mapped.
    """
    spaced = _re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Za-z])", " ", str(name))
    tokens = [t for t in _re.split(r"[^a-z0-9]+", spaced.lower()) if t]
    side = None
    finger = None
    segment = None
    for token in tokens:
        if token in ("left", "l"):
            side = side or "L"
        elif token in ("right", "r"):
            side = side or "R"
        elif token in FINGERS or token == "little":
            finger = finger or ("pinky" if token == "little" else token)
        elif token.isdigit():
            segment = int(token)  # the last number wins: "mixamorig1:LeftHandIndex2" is segment 2
        elif token in ("metacarpal", "meta", "end", "nub", "tip", "twist", "ik", "ctrl", "share", "toe", "toes"):
            return None, None, None
    if finger is None or side is None or segment is None or not 1 <= segment <= 4:
        return None, None, None
    return finger, segment, side


def _hand_points(obj, camera: dict, side: str, wrist_world) -> tuple:
    """21 OpenPose hand keypoints for one side, or ([], {}) when the rig has no finger bones."""
    segments: dict = {}
    for bone in obj.pose.bones:
        finger, segment, bone_side = classify_finger(bone.name)
        if finger is not None and bone_side == side:
            segments.setdefault(finger, {}).setdefault(segment, bone)
    if not segments:
        return [], {}
    points = [[0.0, 0.0, 0.0] for _ in range(21)]
    if wrist_world is not None:
        points[0] = [*_project(camera, wrist_world), 1.0]
    used = {}
    for f, finger in enumerate(FINGERS):
        bones = [segments.get(finger, {})[k] for k in sorted(segments.get(finger, {}))][:3]
        if not bones:
            continue
        joints = [obj.matrix_world @ bone.head for bone in bones] + [obj.matrix_world @ bones[-1].tail]
        for j, world in enumerate(joints[:4]):
            points[1 + 4 * f + j] = [*_project(camera, world), 1.0 if len(bones) == 3 or j < len(bones) else 0.5]
        used[finger] = [bone.name for bone in bones]
    return points, used


def _openpose_points(obj, camera: dict) -> tuple:
    """18 OpenPose keypoints [x, y, confidence] for one armature, plus the bone used per role."""
    def depth(bone) -> int:
        level = 0
        while bone.parent is not None:
            bone, level = bone.parent, level + 1
        return level

    chosen: dict = {}
    chains: dict = {}
    necks = []
    for bone in obj.pose.bones:  # hierarchy order; the first deform bone wins a role
        role, side = classify_bone(bone.name)
        if role is None:
            continue
        if role in ("armchain", "legchain"):
            chains.setdefault((role, side), []).append(bone)
            continue
        if role == "neck":
            necks.append(bone)
        key = (role, side)
        deform = bool(obj.data.bones[bone.name].use_deform)
        if key not in chosen or (deform and not chosen[key][1]):
            chosen[key] = (bone, deform)
    approximated = []
    # Generic numbered chains fill the limb roles that have no specific name, in hierarchy order.
    for (kind, side), bones in sorted(chains.items(), key=lambda item: (item[0][0], item[0][1])):
        roles = ("upperarm", "forearm", "hand") if kind == "armchain" else ("thigh", "shin", "foot")
        ordered = sorted(bones, key=depth)
        free = [role for role in roles if (role, side) not in chosen]
        if not free:
            continue
        if len(free) < len(roles):
            # Specific names cover the end of the limb (e.g. "b_LeftFoot01" after "b_LeftLeg01/02"):
            # fill only a missing leading run, and only when the chain has exactly that many bones.
            if free != list(roles[:len(free)]) or len(ordered) != len(free):
                continue
        for role, bone in zip(free, ordered):
            chosen[(role, side)] = (bone, True)
        approximated.append(f"{kind}.{side} by hierarchy order")
    if ("head", None) not in chosen and len(necks) > 1:  # e.g. neck_joint_1/2 with no head bone
        chosen[("head", None)] = (max(necks, key=depth), True)
        chosen[("neck", None)] = (min(necks, key=depth), True)
        approximated.append("head = deepest neck bone")

    def joint(role, side, end="head"):
        found = chosen.get((role, side))
        if not found:
            return None
        bone = found[0]
        return obj.matrix_world @ (bone.head if end == "head" else bone.tail)

    points = [[0.0, 0.0, 0.0] for _ in OPENPOSE_NAMES]

    def put(index, world, confidence=1.0):
        if world is not None:
            u, v = _project(camera, world)
            points[index] = [u, v, confidence]

    head = joint("head", None)
    head_tail = joint("head", None, "tail")
    neck = joint("neck", None)
    put(1, neck if neck is not None else head, 1.0 if neck is not None else 0.5)
    if head is not None and head_tail is not None:
        put(0, head + (head_tail - head) * 0.5, 0.5)  # no face bones: nose approximated mid-head
    for side, base in (("R", 2), ("L", 5)):
        put(base, joint("upperarm", side))
        elbow = joint("forearm", side)
        put(base + 1, elbow if elbow is not None else joint("upperarm", side, "tail"), 1.0 if elbow is not None else 0.5)
        wrist = joint("hand", side)
        put(base + 2, wrist if wrist is not None else joint("forearm", side, "tail"), 1.0 if wrist is not None else 0.5)
    for side, base in (("R", 8), ("L", 11)):
        put(base, joint("thigh", side))
        knee = joint("shin", side)
        put(base + 1, knee if knee is not None else joint("thigh", side, "tail"), 1.0 if knee is not None else 0.5)
        ankle = joint("foot", side)
        put(base + 2, ankle if ankle is not None else joint("shin", side, "tail"), 1.0 if ankle is not None else 0.5)
    put(14, joint("eye", "R"))
    put(15, joint("eye", "L"))
    mapping = {f"{role}.{side}" if side else role: found[0].name for (role, side), found in sorted(
        chosen.items(), key=lambda item: (item[0][0], item[0][1] or ""))}
    if approximated:
        mapping["_approximated"] = approximated
    return points, mapping


def _hsv_rgb(hue: float) -> tuple:
    """Full-saturation, full-value HSV to 8-bit RGB (the hand-edge rainbow)."""
    h = (hue % 1.0) * 6.0
    i = int(h)
    f = h - i
    q, t = 1.0 - f, f
    r, g, b = ((1, t, 0), (q, 1, 0), (0, 1, t), (0, q, 1), (t, 0, 1), (1, 0, q))[i % 6]
    return int(r * 255), int(g * 255), int(b * 255)


_DISC_OFFSETS: dict = {}


def _disc(canvas, x, y, radius, colour) -> None:
    """Fill the pixels within ``radius`` of (x, y); one vectorised write per disc."""
    import numpy as np

    offsets = _DISC_OFFSETS.get(radius)
    if offsets is None:
        span = np.arange(-radius, radius + 1)
        dy, dx = np.meshgrid(span, span, indexing="ij")
        inside = dx * dx + dy * dy <= radius * radius
        offsets = _DISC_OFFSETS[radius] = (dy[inside], dx[inside])
    height, width = canvas.shape[:2]
    py, px = offsets[0] + y, offsets[1] + x
    keep = (px >= 0) & (px < width) & (py >= 0) & (py < height)
    canvas[py[keep], px[keep]] = colour


def _openpose(out_dir: str, camera: dict, np, prefix: str = "") -> dict:
    scene = bpy.context.scene
    width, height = camera["resolution"]
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    stick = max(2, int(round(width / 128)))
    people = []
    report = []
    for obj in sorted(scene.objects, key=lambda o: o.name):
        if obj.type != "ARMATURE":
            continue
        points, mapping = _openpose_points(obj, camera)
        found = sum(1 for point in points if point[2] > 0)
        report.append({"object": obj.name, "keypoints": found, "bones": mapping})
        if found < 4:
            continue
        hands = {}
        for side, wrist_index in (("L", 7), ("R", 4)):
            wrist = points[wrist_index]
            wrist_bone = next((b for b in obj.pose.bones if classify_bone(b.name) == ("hand", side)), None)
            wrist_world = obj.matrix_world @ wrist_bone.head if wrist_bone is not None else None
            hand, used = _hand_points(obj, camera, side, wrist_world if wrist[2] > 0 else None)
            hands[side] = hand
            if used:
                report[-1].setdefault("fingers", {})[side] = used
        r_shoulder, l_shoulder = points[2], points[5]
        facing = None
        if r_shoulder[2] and l_shoulder[2]:
            spread = l_shoulder[0] - r_shoulder[0]
            facing = "side" if abs(spread) < 0.02 * width else ("camera" if spread > 0 else "away")
        report[-1]["facing"] = facing
        person = {"pose_keypoints_2d": [_r(value, 3) for point in points for value in point]}
        for side, key in (("L", "hand_left_keypoints_2d"), ("R", "hand_right_keypoints_2d")):
            if hands.get(side):
                person[key] = [_r(value, 3) for point in hands[side] for value in point]
        people.append(person)
        for index, (a, b) in enumerate(OPENPOSE_LIMBS):
            pa, pb = points[a - 1], points[b - 1]
            if pa[2] > 0 and pb[2] > 0:
                colour = tuple(int(c * 0.6) for c in OPENPOSE_COLOURS[index])
                steps = int(max(abs(pb[0] - pa[0]), abs(pb[1] - pa[1]))) + 1
                for i in range(steps + 1):
                    t = i / steps
                    _disc(canvas, int(round(pa[0] + (pb[0] - pa[0]) * t)), int(round(pa[1] + (pb[1] - pa[1]) * t)),
                          stick // 2, colour)
        for index, point in enumerate(points):
            if point[2] > 0:
                _disc(canvas, int(round(point[0])), int(round(point[1])), stick, OPENPOSE_COLOURS[index])
        for hand in hands.values():
            for index, (a, b) in enumerate(HAND_EDGES if hand else ()):
                pa, pb = hand[a], hand[b]
                if pa[2] > 0 and pb[2] > 0:
                    colour = _hsv_rgb(index / len(HAND_EDGES))
                    steps = int(max(abs(pb[0] - pa[0]), abs(pb[1] - pa[1]))) + 1
                    for i in range(steps + 1):
                        t = i / steps
                        _disc(canvas, int(round(pa[0] + (pb[0] - pa[0]) * t)), int(round(pa[1] + (pb[1] - pa[1]) * t)),
                              max(1, stick // 4), colour)
            for point in hand:
                if point[2] > 0:
                    _disc(canvas, int(round(point[0])), int(round(point[1])), max(1, stick // 2), (0, 0, 255))
    document = {"version": 1.3, "canvas_width": width, "canvas_height": height, "people": people,
                "bodyrig": {"frame": scene.frame_current, "keypoint_names": list(OPENPOSE_NAMES), "armatures": report,
                            "approximated": ["nose (mid-head; no face bones)"], "camera": camera,
                            "hand_layout": "OpenPose hand-21: 0 wrist, then base..tip for thumb, index, middle, ring, pinky"}}
    with open(os.path.join(out_dir, prefix + "openpose.json"), "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
    _png(os.path.join(out_dir, prefix + "openpose.png"), width, height, _rows(canvas, np), color_type=2, bit_depth=8)
    return {"people": len(people), "armatures": report}


MAX_FRAMES = 600


def parse_frames(text: str) -> list:
    """``START:END:STEP`` (inclusive end) to a list of frame numbers; empty text means none."""
    if not text:
        return []
    parts = text.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"frames must be START:END[:STEP], got {text!r}")
    start, end = int(parts[0]), int(parts[1])
    step = int(parts[2]) if len(parts) == 3 else 1
    if step < 1 or end < start:
        raise ValueError(f"invalid frame range {text!r}")
    frames = list(range(start, end + 1, step))
    if len(frames) > MAX_FRAMES:
        raise ValueError(f"at most {MAX_FRAMES} frames, got {len(frames)}")
    return frames


def _union_bounds(frames: list, out_dir: str = ""):
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects = list(scene.objects)
    shapes = _bone_shapes(objects)
    low, high = [math.inf] * 3, [-math.inf] * 3
    for index, frame in enumerate(frames):
        if out_dir:
            _progress(out_dir, "bounds", index, len(frames))  # keeps the host's no-progress check satisfied
        scene.frame_set(frame)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for obj in objects:
            if obj.type == "MESH" and _renderable(obj, shapes):
                a, b = _world_bounds(obj, depsgraph)
                low = [min(low[i], a[i]) for i in range(3)]
                high = [max(high[i], b[i]) for i in range(3)]
    if not all(math.isfinite(v) for v in low + high):
        return None
    return {"min": _vec(low), "max": _vec(high)}


def _conditioning_pass(out_dir: str, camera: dict, kinds: set, np, prefix: str) -> dict:
    outputs = {}
    if "pose" in kinds:
        outputs["pose"] = _pose(out_dir, camera, np, prefix)
    if "openpose" in kinds:
        outputs["openpose"] = _openpose(out_dir, camera, np, prefix)
    if kinds & {"depth", "normal"}:
        outputs["depth_normal"] = _depth_normal(out_dir, camera, kinds, np, prefix)
    return outputs


def main(argv: list[str]) -> int:
    started = time.perf_counter()
    args = _args(argv)
    out_dir = os.path.dirname(os.path.abspath(args.output))
    document: dict = {"contract": CONTRACT, "warnings": [], "timings_ms": {}}
    try:
        step = time.perf_counter()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        document["security"] = _harden_preferences()
        document["timings_ms"]["reset"] = _ms(step)

        step = time.perf_counter()
        _progress(out_dir, "import")
        document["importer"] = _import(os.path.abspath(args.input), args.format, os.path.abspath(args.staging_root))
        document["security"].update(_harden_preferences())
        document["timings_ms"]["import"] = _ms(step)

        scene = bpy.context.scene
        scene.frame_set(scene.frame_start)
        step = time.perf_counter()
        _progress(out_dir, "collect")
        document["scene"], warnings = _collect(args.staging_root)
        document["warnings"].extend(warnings)
        document["timings_ms"]["collect"] = _ms(step)

        kinds = {k for k in args.conditioning.split(",") if k}
        if kinds:
            import numpy as np

            step = time.perf_counter()
            frames = parse_frames(args.frames)
            resolution = max(16, min(args.resolution, 2048))
            bounds = _union_bounds(frames, out_dir) if frames else document["scene"]["bounds_world"]
            if bounds is None:
                document["conditioning"] = {"skipped": "no mesh bounds"}
            elif not frames:
                _progress(out_dir, "conditioning", 0, 1)
                scene.frame_set(scene.frame_start)
                camera = _camera(bounds, resolution, args.yaw)
                document["conditioning"] = {"camera": camera,
                                            "outputs": _conditioning_pass(out_dir, camera, kinds, np, "")}
            else:
                camera = _camera(bounds, resolution, args.yaw)
                skip = 0
                resume = None
                if args.resume_from:
                    # Frames below resume_from were finished by an earlier, stopped run and are kept by
                    # the host. Reuse them only if this run frames the sequence identically.
                    applied = 0 < args.resume_from < len(frames) and \
                        camera_sha256(camera) == args.resume_camera_sha256
                    skip = args.resume_from if applied else 0
                    resume = {"requested": args.resume_from, "applied": bool(applied)}
                    if not applied:
                        document["warnings"].append("resume not applied: the sequence camera differs; "
                                                    "all frames rendered")
                sequence = []
                for index, frame in enumerate(frames):
                    if index < skip:
                        sequence.append({"index": index, "frame": frame, "outputs": None, "resumed": True})
                        continue
                    _progress(out_dir, "conditioning", index, len(frames), camera)
                    scene.frame_set(frame)
                    outputs = _conditioning_pass(out_dir, camera, kinds, np, f"f{index:06d}_")
                    sequence.append({"index": index, "frame": frame, "outputs": outputs})
                _progress(out_dir, "conditioning", len(frames), len(frames), camera)
                document["conditioning"] = {"camera": camera, "frames": frames, "sequence": sequence,
                                            "outputs": next((s["outputs"] for s in sequence if s["outputs"]), {})}
                if resume is not None:
                    document["conditioning"]["resume"] = resume
            document["timings_ms"]["conditioning"] = _ms(step)
        document["blender"] = {
            "version": bpy.app.version_string,
            "build_hash": bpy.app.build_hash.decode("ascii", "replace") if isinstance(bpy.app.build_hash, bytes) else str(bpy.app.build_hash),
            "background": bool(bpy.app.background),
        }
        code = 0
    except Exception as exc:  # reported to the host, which marks the asset FAILED
        document["error"] = {"type": type(exc).__name__, "message": str(exc)[:2000],
                             "trace": traceback.format_exc(limit=8)[-4000:]}
        code = 3
    document["timings_ms"]["total"] = _ms(started)
    document["complete"] = True
    partial = args.output + ".partial"
    with open(partial, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
    os.replace(partial, args.output)  # the host only ever sees a complete document
    return code


if __name__ == "__main__":
    # The result is written and closed before this; the host's wall-clock
    # limit is the backstop if a teardown ever hangs anyway.
    hard_exit(main(sys.argv))
