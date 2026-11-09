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
  B=z towards the camera), background 0.

The conditioning camera is a fixed orthographic front view (looking along +Y,
Z up) framed on the union of the mesh bounds. Depth and normals come from
ray casts against the evaluated meshes, so no render engine and no GPU are
involved.
"""

from __future__ import annotations

import argparse
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
    return parser.parse_args(rest)


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


def _import(path: str, fmt: str) -> dict:
    if fmt == "blend":
        bpy.ops.wm.open_mainfile(filepath=path, load_ui=False, use_scripts=False)
        return {"module": "wm.open_mainfile", "use_scripts": False}
    if fmt == "fbx":
        info = _bundled_importer("io_scene_fbx")
        bpy.ops.import_scene.fbx(filepath=path)
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


def _camera(bounds: dict, resolution: int) -> dict:
    low, high = bounds["min"], bounds["max"]
    center = [(low[i] + high[i]) / 2.0 for i in range(3)]
    scale = max(high[0] - low[0], high[2] - low[2]) * 1.1 or 1.0
    depth_span = max(high[1] - low[1], 1e-6)
    origin_y = low[1] - 1.0
    return {
        "type": "orthographic",
        "view": "front",
        "forward": [0.0, 1.0, 0.0],
        "up": [0.0, 0.0, 1.0],
        "center": _vec(center),
        "ortho_scale": _r(scale),
        "origin_y": _r(origin_y),
        "max_distance": _r(depth_span + 2.0),
        "resolution": [resolution, resolution],
        "pixel_origin": "top-left",
    }


def _project(camera: dict, point) -> list[float]:
    scale = camera["ortho_scale"]
    width, height = camera["resolution"]
    cx, _, cz = camera["center"]
    u = (point[0] - (cx - scale / 2.0)) / scale * width
    v = ((cz + scale / 2.0) - point[2]) / scale * height
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


def _pose(out_dir: str, camera: dict, np) -> dict:
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
    with open(os.path.join(out_dir, "pose.json"), "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
    _png(os.path.join(out_dir, "pose.png"), width, height, _rows(canvas, np), color_type=2, bit_depth=8)
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


def _depth_normal(out_dir: str, camera: dict, kinds: set, np) -> dict:
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    data = _world_triangles(np)
    if data is None:
        return {"skipped": "no visible mesh"}
    verts, tris, corner_normals = data
    tree = BVHTree.FromPolygons(verts.tolist(), tris.tolist(), all_triangles=True)
    width, height = camera["resolution"]
    scale = camera["ortho_scale"]
    cx, _, cz = camera["center"]
    origin_y = camera["origin_y"]
    max_distance = camera["max_distance"]
    direction = Vector((0.0, 1.0, 0.0))
    distance = np.full((height, width), np.nan)
    hit_index = np.full((height, width), -1, dtype=np.int64)
    hit_point = np.zeros((height, width, 3))
    face_normal = np.zeros((height, width, 3))
    step = scale / width
    left = cx - scale / 2.0 + step / 2.0
    top = cz + scale / 2.0 - step / 2.0
    for row in range(height):
        z = top - row * step
        for col in range(width):
            location, normal, index, dist = tree.ray_cast(Vector((left + col * step, origin_y, z)), direction, max_distance)
            if location is not None:
                distance[row, col] = dist
                hit_index[row, col] = index
                hit_point[row, col] = location
                face_normal[row, col] = normal
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
        _png(os.path.join(out_dir, "depth.png"), width, height, _rows(depth.astype(">u2").view(np.uint8), np),
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
        # camera space for the front view: x right = world x, y up = world z, z towards camera = -world y
        camera_space = np.stack([normals[..., 0], normals[..., 2], -normals[..., 1]], axis=-1)
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        rgb[hits] = np.clip(np.round((camera_space[hits] + 1.0) * 0.5 * 255.0), 0, 255).astype(np.uint8)
        _png(os.path.join(out_dir, "normal.png"), width, height, _rows(rgb, np), color_type=2, bit_depth=8)
    return result


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
        document["importer"] = _import(os.path.abspath(args.input), args.format)
        document["security"].update(_harden_preferences())
        document["timings_ms"]["import"] = _ms(step)

        scene = bpy.context.scene
        scene.frame_set(scene.frame_start)
        step = time.perf_counter()
        document["scene"], warnings = _collect(args.staging_root)
        document["warnings"].extend(warnings)
        document["timings_ms"]["collect"] = _ms(step)

        kinds = {k for k in args.conditioning.split(",") if k}
        if kinds:
            import numpy as np

            step = time.perf_counter()
            bounds = document["scene"]["bounds_world"]
            if bounds is None:
                document["conditioning"] = {"skipped": "no mesh bounds"}
            else:
                camera = _camera(bounds, max(16, min(args.resolution, 2048)))
                conditioning = {"camera": camera, "outputs": {}}
                if "pose" in kinds:
                    conditioning["outputs"]["pose"] = _pose(out_dir, camera, np)
                if kinds & {"depth", "normal"}:
                    conditioning["outputs"]["depth_normal"] = _depth_normal(out_dir, camera, kinds, np)
                document["conditioning"] = conditioning
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
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, sort_keys=True)
    return code


if __name__ == "__main__":
    _code = main(sys.argv)
    # Exit without Blender's C-level teardown: the bpy module can hang there
    # after some importers ran (observed with bpy 4.5.15 on Linux), and the
    # result is already written and closed. The host's wall-clock limit is
    # the backstop if this ever stops working.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_code)
