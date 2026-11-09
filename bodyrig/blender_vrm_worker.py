"""VRM 1.0 export that runs INSIDE Blender (``blender --python`` or the ``bpy`` module).

The host side is ``bodyrig.vrm_export``: it stages the asset, scrubs the
environment, bounds the process (``bodyrig.process_limits``) and validates what
this script writes. It copies this file next to ``blender_scene_worker.py``,
``humanoid_names.py`` and ``vrm_paths.py`` into the job directory, so the
hardening helpers are shared with the scene inspector (#1396) rather than
duplicated.

Steps, all inside the staging root:

1. factory reset with an empty scene, auto-run forced off;
2. enable the two add-ons from the read-only ``--addons-dir`` only
   (VRM Add-on for Blender, XNALara-io-Tools); nothing from the asset or from
   user directories;
3. import: XPS/XNALara via the add-on, FBX with images confined to the staging
   root, glTF/GLB/VRM, ``.blend`` with ``use_scripts=False``;
4. humanoid mapping: fast name table first (``humanoid_names``), the VRM add-on's
   structure search only when required bones are still missing;
5. materials the VRM exporter cannot read (XPS shader groups) are replaced by
   Principled BSDF with the best diffuse texture, so textures are not dropped;
   missing textures are relinked from the staging root only, fail closed:
   no linked file or folder, containment re-checked right before reload, and
   nothing from outside the root is ever packed (``vrm_paths``);
6. textures larger than ``--max-texture`` are scaled down and packed;
7. VRM meta is set to private: only the author, no redistribution, no
   modification, personal non-profit;
8. export to ``--output-vrm``, then the contract document to ``--output``.

Output contract: ``bodyrig-vrm-worker-v1``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # staged siblings only (-I drops this)

import bpy  # noqa: E402  (provided by Blender)

import blender_scene_worker as shared  # noqa: E402  (staged copy of bodyrig/blender_scene_worker.py)
import humanoid_names  # noqa: E402  (staged copy of bodyrig/humanoid_names.py)
import vrm_paths  # noqa: E402  (staged copy of bodyrig/vrm_paths.py)

CONTRACT = "bodyrig-vrm-worker-v1"
VRM_ADDON = "io_scene_vrm"
XPS_ADDON = "XNALara-io-Tools"  # the fork registers modules under this exact package name
XPS_FORMATS = ("xps", "mesh", "ascii")
DIFFUSE_HINT = re.compile(r"(diffuse|albedo|base.?colou?r|_d\b|_d\.|_col\b|_c\.)", re.IGNORECASE)
SKIP_HINT = re.compile(r"(normal|_n\.|bump|spec|_s\.|rough|metal|mask|light|_ao\b|emiss)", re.IGNORECASE)


def _args(argv: list[str]) -> argparse.Namespace:
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    parser = argparse.ArgumentParser(prog="blender_vrm_worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--format", required=True)
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--addons-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--output-vrm", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--max-texture", type=int, default=2048)
    parser.add_argument("--weight-reference", default="", help="optional reference body model (#1401)")
    parser.add_argument("--weight-reference-format", default="")
    parser.add_argument("--weight-reference-root", default="")
    return parser.parse_args(rest)


def _ms(start: float) -> int:
    return int(round((time.perf_counter() - start) * 1000))


# --- add-ons -------------------------------------------------------------------------------

def _enable_addons(addons_dir: str) -> dict:
    import addon_utils

    addons_dir = os.path.abspath(addons_dir)
    if addons_dir not in sys.path:
        sys.path.append(addons_dir)
    report = {}
    for module in (VRM_ADDON, XPS_ADDON):
        path = os.path.join(addons_dir, module)
        if not os.path.isfile(os.path.join(path, "__init__.py")):
            report[module] = {"enabled": False, "reason": "not installed in --addons-dir"}
            continue
        # default_set=True: the VRM exporter reads its own add-on preferences and fails without
        # them. The user config lives in the job directory (child_env), so nothing is persisted.
        mod = addon_utils.enable(module, default_set=True, persistent=False)
        loaded_from = os.path.abspath(getattr(mod, "__file__", "") or "")
        report[module] = {"enabled": mod is not None, "from_addons_dir": shared._inside(loaded_from, addons_dir)}
        if mod is not None and not report[module]["from_addons_dir"]:
            raise RuntimeError(f"{module} resolved outside --addons-dir: {loaded_from}")
    if not report[VRM_ADDON]["enabled"]:
        raise RuntimeError("VRM Add-on for Blender is required (run the VRM export setup)")
    return report


# --- import --------------------------------------------------------------------------------

def _import(path: str, fmt: str, staging_root: str, addons: dict) -> dict:
    if fmt in XPS_FORMATS:
        if not addons.get(XPS_ADDON, {}).get("enabled"):
            raise RuntimeError("XPS import needs XNALara-io-Tools in --addons-dir")
        bpy.ops.xps_tools.import_model(filepath=path, joinMeshParts=True, joinMeshRips=True,
                                       connectBones=True, autoIk=False)
        return {"module": XPS_ADDON}
    if fmt == "vrm":
        bpy.ops.import_scene.vrm(filepath=path)
        return {"module": VRM_ADDON}
    return shared._import(path, fmt, staging_root)  # .blend use_scripts=False, FBX images confined


# --- humanoid ------------------------------------------------------------------------------

def _pick_armature():
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not armatures:
        return None

    def users(armature) -> int:
        return sum(1 for o in bpy.data.objects if o.type == "MESH"
                   and any(m.type == "ARMATURE" and m.object == armature for m in o.modifiers))

    armatures.sort(key=lambda a: (users(a), len(a.data.bones)), reverse=True)
    return armatures[0]


def _human_bones(armature):
    return armature.data.vrm_addon_extension.vrm1.humanoid.human_bones


def _current_mapping(human_bones) -> dict:
    out = {}
    for key in dir(human_bones):
        if key.startswith("_"):
            continue
        slot = getattr(human_bones, key, None)
        node = getattr(slot, "node", None)
        bone_name = getattr(node, "bone_name", "") if node is not None else ""
        if bone_name:
            out[key] = bone_name
    return out


def _fill(human_bones, mapping: dict) -> list:
    used = set(_current_mapping(human_bones).values())
    filled = []
    for key, bone in mapping.items():
        slot = getattr(human_bones, key, None)
        if slot is None or slot.node.bone_name or bone in used:
            continue
        slot.node.bone_name = bone
        used.add(bone)
        filled.append(key)
    return filled


def _assign_humanoid(armature) -> dict:
    armature.data.vrm_addon_extension.spec_version = "1.0"
    bpy.context.view_layer.objects.active = armature
    human_bones = _human_bones(armature)
    by_name = humanoid_names.map_bones(bone.name for bone in armature.data.bones)
    method = "names"
    if humanoid_names.missing_required(by_name):
        method = "vrm_addon_structure"
        bpy.ops.vrm.assign_vrm1_humanoid_human_bones_automatically(armature_object_name=armature.name)
    filled = _fill(human_bones, by_name)
    mapping = _current_mapping(human_bones)
    return {"method": method, "mapping": mapping, "filled_by_names": filled,
            "missing_required": humanoid_names.missing_required(mapping)}


# --- materials and textures ----------------------------------------------------------------

def _drop_image_source(image) -> None:
    """Forget a file outside the staging root, including pixels already in memory."""
    image.filepath = ""
    free = getattr(image, "buffers_free", None)
    if free is not None:
        free()


def _image_path(image) -> str:
    return os.path.abspath(bpy.path.abspath(image.filepath)) if image.filepath else ""


def _relink_images(staging_root: str) -> dict:
    """Relink missing images by file name, from the staging root only (fail closed, #1399 review).

    The index skips linked files and folders; every candidate is checked again with
    ``vrm_paths.contained`` immediately before ``reload()``, so a path that stopped
    being safe after indexing is never read.
    """
    index = vrm_paths.image_index(staging_root)
    relinked = rejected = 0
    for image in bpy.data.images:
        if image.source != "FILE" or image.packed_file:
            continue
        current = _image_path(image)
        if current and vrm_paths.contained(current, staging_root) and os.path.isfile(current):
            continue
        base = os.path.basename((image.filepath or image.name).replace("\\", "/")).lower()
        hit = index.get(base) or index.get(os.path.splitext(base)[0])
        if hit and vrm_paths.contained(hit, staging_root) and os.path.isfile(hit):  # re-check at the boundary
            image.filepath = hit
            image.reload()
            relinked += 1
        elif current:
            _drop_image_source(image)  # never read or pack anything outside the staging root
            rejected += 1
    return {"relinked_images": relinked, "rejected_image_paths": rejected}


def _fix_materials() -> int:
    fixed = 0
    for material in bpy.data.materials:
        tree = material.node_tree
        if tree is None:
            continue
        outputs = [n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"]
        output = next((n for n in outputs if n.is_active_output), outputs[0] if outputs else None)
        surface = output.inputs["Surface"] if output else None
        if surface is not None and surface.is_linked and surface.links[0].from_node.type == "BSDF_PRINCIPLED":
            continue
        images = [n for n in tree.nodes if n.type == "TEX_IMAGE" and n.image]
        pick = (next((n for n in images if DIFFUSE_HINT.search(n.image.name)), None)
                or next((n for n in images if not SKIP_HINT.search(n.image.name)), None)
                or (images[0] if images else None))
        if output is None:
            output = tree.nodes.new("ShaderNodeOutputMaterial")
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
        tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
        if pick is not None:
            tree.links.new(pick.outputs["Color"], bsdf.inputs["Base Color"])
        fixed += 1
    return fixed


def _pack_and_shrink(max_size: int, staging_root: str) -> dict:
    packed = shrunk = 0
    for image in bpy.data.images:
        if image.source != "FILE" or not image.has_data:
            continue
        if not image.packed_file:
            path = _image_path(image)
            if not path or not vrm_paths.contained(path, staging_root):
                _drop_image_source(image)  # only pack pixels that came from the staging root
                continue
        width, height = image.size[0], image.size[1]
        if max(width, height) > max_size > 0:
            scale = max_size / max(width, height)
            image.scale(max(1, int(width * scale)), max(1, int(height * scale)))
            shrunk += 1
        if not image.packed_file:
            image.pack()
            packed += 1
    return {"packed": packed, "downscaled": shrunk}


def _set_private_meta(armature, name: str) -> None:
    meta = armature.data.vrm_addon_extension.vrm1.meta
    meta.vrm_name = name[:100]
    if not len(meta.authors):
        meta.authors.add()
    meta.authors[0].value = "private"
    meta.avatar_permission = "onlyAuthor"
    meta.commercial_usage = "personalNonProfit"
    meta.allow_redistribution = False
    meta.modification = "prohibited"


# --- optional weight transfer (#1401) -------------------------------------------------------

def _append_blend_objects(path: str) -> None:
    """Append every object of a .blend into the current scene (auto-run stays off)."""
    with bpy.data.libraries.load(path, link=False) as (source, target):
        target.objects = list(source.objects)
    for obj in target.objects:
        if obj is not None and obj.name not in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.link(obj)


def _weight_transfer(armature, mapping: dict, args: argparse.Namespace, document: dict) -> dict:
    """Import the reference, transfer hip/groin weights, delete the reference again.

    Never fails the export: a reference that cannot be imported or does not fit
    leaves the source weights as they were, with the reason in the report.
    """
    import blender_vrm_weights  # staged sibling; imported only when used

    root = os.path.abspath(args.weight_reference_root)
    before = set(bpy.data.objects)
    report: dict
    try:
        path = os.path.abspath(args.weight_reference)
        if not shared._inside(path, root):
            raise RuntimeError("reference is outside its staging root")
        if args.weight_reference_format == "blend":
            _append_blend_objects(path)  # open_mainfile would replace the target scene
        else:
            _import(path, args.weight_reference_format, root, document["addons"])
        document["security"].update(shared._harden_preferences())
    except Exception as exc:  # reported, export continues with the source weights
        report = {"applied": False, "reason": f"reference import failed: {type(exc).__name__}: {exc}"[:500]}
    else:
        reference = [o for o in bpy.data.objects if o not in before]
        try:
            report = blender_vrm_weights.transfer(armature, mapping, reference)
        finally:
            blender_vrm_weights.remove_objects([o for o in bpy.data.objects if o not in before])
    leftovers = [o.name for o in bpy.data.objects if o not in before]
    if leftovers:
        raise RuntimeError(f"reference objects left in the scene: {leftovers[:5]}")
    purge = getattr(bpy.data, "orphans_purge", None)
    if purge is not None:
        purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    if not report.get("applied"):
        document["warnings"].append(f"weight transfer not applied: {report.get('reason')}")
    return report


# --- main ----------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    started = time.perf_counter()
    args = _args(argv)
    staging_root = os.path.abspath(args.staging_root)
    document: dict = {"contract": CONTRACT, "warnings": [], "timings_ms": {}}
    try:
        for target in (args.output, args.output_vrm):
            if not shared._inside(os.path.dirname(os.path.abspath(target)), os.path.dirname(staging_root)):
                raise RuntimeError("outputs must stay inside the job directory")
        step = time.perf_counter()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        document["security"] = shared._harden_preferences()
        document["addons"] = _enable_addons(args.addons_dir)
        document["timings_ms"]["reset"] = _ms(step)

        step = time.perf_counter()
        document["importer"] = _import(os.path.abspath(args.input), args.format, staging_root, document["addons"])
        document["security"].update(shared._harden_preferences())
        document["timings_ms"]["import"] = _ms(step)

        step = time.perf_counter()
        armature = _pick_armature()
        if armature is None:
            raise RuntimeError("the asset has no armature")
        document["bones"] = len(armature.data.bones)
        humanoid = _assign_humanoid(armature)
        document["humanoid"] = humanoid
        document["timings_ms"]["humanoid"] = _ms(step)
        if humanoid["missing_required"]:
            raise RuntimeError("missing required humanoid bones: " + ", ".join(humanoid["missing_required"]))

        if args.weight_reference:
            step = time.perf_counter()
            document["weight_transfer"] = _weight_transfer(armature, humanoid["mapping"], args, document)
            document["timings_ms"]["weight_transfer"] = _ms(step)

        step = time.perf_counter()
        document["materials"] = _relink_images(staging_root)
        document["materials"]["replaced_with_principled"] = _fix_materials()
        document["materials"].update(_pack_and_shrink(args.max_texture, staging_root))
        document["timings_ms"]["materials"] = _ms(step)

        step = time.perf_counter()
        _set_private_meta(armature, args.name)
        partial = args.output_vrm + ".partial"
        result = bpy.ops.export_scene.vrm(filepath=partial, armature_object_name=armature.name,
                                          ignore_warning=True)
        if "FINISHED" not in result or not os.path.isfile(partial):
            raise RuntimeError(f"the VRM validator refused the export: {sorted(result)}")
        os.replace(partial, args.output_vrm)
        document["vrm"] = {"bytes": os.path.getsize(args.output_vrm)}
        document["timings_ms"]["export"] = _ms(step)
        document["blender"] = {"version": bpy.app.version_string, "background": bool(bpy.app.background)}
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
    os.replace(partial, args.output)
    return code


if __name__ == "__main__":
    shared.hard_exit(main(sys.argv))
