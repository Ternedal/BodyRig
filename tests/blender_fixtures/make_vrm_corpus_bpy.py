"""Build the VRM export test corpus with the pinned bpy (run with the bpy venv's python -I).

    <bpy-python> -I tests/blender_fixtures/make_vrm_corpus_bpy.py -- <out-dir>

Every model is the same abstract capsule figure (one box per bone, no anatomy)
with a 19-bone humanoid skeleton, named in four rig families:

- ``xps_pack.zip``: native XNALara ``figure.mesh.ascii`` + ``textures/skin.png``
  (texture in a sub-folder on purpose: the worker must relink it);
- ``xps_names.fbx``: the XPS names exported as FBX with a 4096 px texture;
- ``valve.blend`` / ``daz.blend``: ValveBiped and Daz Genesis names;
- ``anon.blend``: ``Bone.000``... names (forces the VRM add-on structure search);
- ``no_armature.glb``: a mesh with no skeleton (must fail cleanly).
"""

from __future__ import annotations

import os
import sys
import zipfile

import bpy
import bmesh
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)

# (xps name, ValveBiped name, Daz name, parent index, head, tail) in Blender Z-up metres
BONES: list[tuple] = [
    ("root hips", "ValveBiped.Bip01_Pelvis", "hip", None, (0, 0, 1.0), (0, 0, 1.1)),
    ("spine lower", "ValveBiped.Bip01_Spine", "abdomenLower", 0, (0, 0, 1.1), (0, 0, 1.25)),
    ("spine middle", "ValveBiped.Bip01_Spine1", "chestUpper", 1, (0, 0, 1.25), (0, 0, 1.4)),
    ("head neck lower", "ValveBiped.Bip01_Neck1", "neckLower", 2, (0, 0, 1.4), (0, 0, 1.5)),
    ("head", "ValveBiped.Bip01_Head1", "head", 3, (0, 0, 1.5), (0, 0, 1.7)),
]
for side, s, d, x in (("left", "L", "l", 1), ("right", "R", "r", -1)):
    i = len(BONES)
    BONES += [
        (f"arm {side} shoulder 1", f"ValveBiped.Bip01_{s}_Clavicle", f"{d}Collar", 2, (0.03 * x, 0, 1.38), (0.15 * x, 0, 1.38)),
        (f"arm {side} shoulder 2", f"ValveBiped.Bip01_{s}_UpperArm", f"{d}ShldrBend", i, (0.15 * x, 0, 1.38), (0.42 * x, 0, 1.38)),
        (f"arm {side} elbow", f"ValveBiped.Bip01_{s}_Forearm", f"{d}ForearmBend", i + 1, (0.42 * x, 0, 1.38), (0.68 * x, 0, 1.38)),
        (f"arm {side} wrist", f"ValveBiped.Bip01_{s}_Hand", f"{d}Hand", i + 2, (0.68 * x, 0, 1.38), (0.76 * x, 0, 1.38)),
        (f"leg {side} thigh", f"ValveBiped.Bip01_{s}_Thigh", f"{d}ThighBend", 0, (0.1 * x, 0, 1.0), (0.1 * x, 0, 0.55)),
        (f"leg {side} knee", f"ValveBiped.Bip01_{s}_Calf", f"{d}Shin", i + 4, (0.1 * x, 0, 0.55), (0.1 * x, 0, 0.1)),
        (f"leg {side} ankle", f"ValveBiped.Bip01_{s}_Foot", f"{d}Foot", i + 5, (0.1 * x, 0, 0.1), (0.1 * x, -0.12, 0.02)),
    ]
NAMING = {"xps": 0, "valve": 1, "daz": 2}
R = 0.03
INSET = 0.01
BOX_TRIS = ((0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6),
            (3, 0, 4), (3, 4, 7), (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7))


def boxes(scale: float = 1.0, offset=(0.0, 0.0, 0.0)):
    """(vertex list [(co, bone index)], triangles) for the capsule figure.

    The first four vertices of every box sit at the bone head, the next four at the tail.
    """
    verts, tris = [], []
    for index, bone in enumerate(BONES):
        base = len(verts)
        head, tail = Vector(bone[4]), Vector(bone[5])
        inset = (tail - head).normalized() * INSET
        for end in (head + inset, tail - inset):  # boxes never touch: nearest-surface lookups stay unambiguous
            for dx, dy in ((-R, -R), (R, -R), (R, R), (-R, R)):
                co = ((end[0] + dx) * scale + offset[0], (end[1] + dy) * scale + offset[1],
                      end[2] * scale + offset[2])
                verts.append((co, index))
        tris += [(base + a, base + b, base + c) for a, b, c in BOX_TRIS]
    return verts, tris


def skin_image(size: int):
    image = bpy.data.images.new("skin", size, size)
    image.generated_color = (0.8, 0.6, 0.5, 1.0)
    return image


THIGHS = [i for i, bone in enumerate(BONES) if bone[0].endswith("thigh")]


def build(naming: str, texture_size: int = 64, texture_file: str | None = None, *, scale: float = 1.0,
          mesh_offset=(0.0, 0.0, 0.0), groin: str = "none"):
    """``groin``: "none" (each box on its own bone), "bad" (thigh tops 100 % hips, the
    tearing groin of many third-party rigs) or "good" (thigh tops 50/50 hips/thigh)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    data = bpy.data.armatures.new("Skeleton")
    armature = bpy.data.objects.new("Skeleton", data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    edit = []
    for index, bone in enumerate(BONES):
        name = f"Bone.{index:03d}" if naming == "anon" else bone[NAMING[naming]]
        eb = data.edit_bones.new(name)
        eb.head = tuple(c * scale for c in bone[4])
        eb.tail = tuple(c * scale for c in bone[5])
        if bone[3] is not None:
            eb.parent = edit[bone[3]]
        edit.append(eb)
    names = [eb.name for eb in edit]
    bpy.ops.object.mode_set(mode="OBJECT")
    verts, tris = boxes(scale, mesh_offset)
    mesh = bpy.data.meshes.new("Body")
    mesh.from_pydata([v[0] for v in verts], [], tris)
    mesh.update()
    body = bpy.data.objects.new("Body", mesh)
    bpy.context.scene.collection.objects.link(body)
    for index, name in enumerate(names):
        body.vertex_groups.new(name=name).add([i for i, v in enumerate(verts) if v[1] == index], 1.0, "REPLACE")
    if groin != "none":
        hips = body.vertex_groups[names[0]]
        for thigh in THIGHS:
            tops = [i for i, v in enumerate(verts) if v[1] == thigh][:4]
            share = 1.0 if groin == "bad" else 0.5
            hips.add(tops, share, "REPLACE")
            if groin == "bad":
                body.vertex_groups[names[thigh]].remove(tops)
            else:
                body.vertex_groups[names[thigh]].add(tops, 1.0 - share, "REPLACE")
    body.parent = armature
    body.modifiers.new("Armature", "ARMATURE").object = armature
    material = bpy.data.materials.new("Skin")
    material.use_nodes = True
    tex = material.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = skin_image(texture_size)
    material.node_tree.links.new(tex.outputs["Color"], material.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    mesh.materials.append(material)
    if texture_file:  # the FBX exporter only embeds images that have a file behind them
        tex.image.filepath_raw = texture_file
        tex.image.file_format = "PNG"
        tex.image.save()
        tex.image.source = "FILE"
    else:
        tex.image.pack()


def write_xps_ascii(path: str) -> None:
    """Native XNALara ascii (Y-up), with the root's parent written as -1 like real files."""
    def yup(p):
        return f"{p[0]:f} {p[2]:f} {-p[1]:f}"
    lines = [str(len(BONES))]
    for bone in BONES:
        lines += [bone[0], str(-1 if bone[3] is None else bone[3]), yup(bone[4])]
    verts, tris = boxes()
    lines += ["1", "body", "1", "1", "skin.png", "0", str(len(verts))]
    for co, index in verts:
        lines += [yup(co), "0 1 0", "255 255 255 255", "0.5 0.5", f"{index} 0 0 0", "1 0 0 0"]
    lines += [str(len(tris))] + [f"{a} {b} {c}" for a, b, c in tris]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    texture_dir = os.path.join(OUT, "fbx_textures")
    os.makedirs(texture_dir, exist_ok=True)
    build("xps", texture_size=4096, texture_file=os.path.join(texture_dir, "skin_4k.png"))
    bpy.ops.export_scene.fbx(filepath=os.path.join(OUT, "xps_names.fbx"), add_leaf_bones=False,
                             path_mode="COPY", embed_textures=True)
    for naming in ("valve", "daz", "anon"):
        build(naming)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, f"{naming}.blend"), compress=True)

    # Weight transfer (#1401): a target with a tearing groin, and references.
    for filename, naming, kwargs in (
        ("weights_target_bad.blend", "xps", {"groin": "bad"}),
        ("weights_ref_good.blend", "daz", {"groin": "good"}),
        ("weights_ref_scaled.blend", "valve", {"groin": "good", "scale": 1.8}),
        ("weights_ref_offset.blend", "daz", {"groin": "good", "mesh_offset": (1.5, 0.0, 0.0)}),
        ("weights_ref_anon.blend", "anon", {"groin": "good"}),
    ):
        build(naming, **kwargs)
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, filename), compress=True)

    pack = os.path.join(OUT, "xps_pack")
    os.makedirs(os.path.join(pack, "textures"), exist_ok=True)
    write_xps_ascii(os.path.join(pack, "figure.mesh.ascii"))
    image = skin_image(64)
    image.filepath_raw = os.path.join(pack, "textures", "skin.png")
    image.file_format = "PNG"
    image.save()
    with zipfile.ZipFile(os.path.join(OUT, "xps_pack.zip"), "w", zipfile.ZIP_DEFLATED) as bundle:
        for folder, _dirs, files in os.walk(pack):
            for name in files:
                full = os.path.join(folder, name)
                bundle.write(full, os.path.relpath(full, pack))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "no_armature.glb"))
    print("vrm corpus ready", flush=True)


main()
# Skip Blender's C-level teardown: it can hang after exporters (Linux) and
# crashes on os._exit (Windows). Everything is written and closed here.
sys.stdout.flush()
sys.stderr.flush()
if os.name == "nt":
    import ctypes

    ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), ctypes.c_uint(0))  # current process
os._exit(0)
