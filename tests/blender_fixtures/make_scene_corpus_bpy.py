"""Build the scene-inspector test corpus with Blender itself.

Run inside Blender (``blender --background --factory-startup --python THIS -- OUT``)
or with the ``bpy`` module (``python THIS -- OUT``). Writes into OUT:

- ``sample.blend``, ``sample.fbx``, ``sample.glb``, ``sample.gltf`` (+ .bin, texture),
  ``sample.obj`` (+ .mtl): one skinned mesh with a 3-bone armature, two shape
  keys, a material with an image texture and one action (bone + shape keys);
- ``autorun.blend``: a registered text block and a scripted driver that would
  create ``autorun-marker.txt`` in OUT if Blender ever executed them;
- ``outside-texture.fbx``: a cube whose texture is referenced by an ABSOLUTE path to
  ``../outside-texture.png`` (next to OUT, outside any staging); the inspector must
  never open it;
- ``humanoid.glb`` and ``humanoid.fbx``: a box-limbed humanoid with a Mixamo-style
  rig (Hips, Spine, Neck, Head, Left/Right Shoulder, Arm, ForeArm, Hand, UpLeg,
  Leg, Foot, and three bones per finger) facing -Y, whose left arm swings over
  frames 1-24; used for the OpenPose body/hand mapping and frame sequences;
- ``expected.json``: the counts the inspector must report.

Everything is generated; no third-party asset is involved.
"""

from __future__ import annotations

import json
import os
import sys

import bpy


def _out_dir() -> str:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(argv) != 1:
        raise SystemExit("usage: make_scene_corpus_bpy.py -- OUT_DIR")
    path = os.path.abspath(argv[0])
    os.makedirs(path, exist_ok=True)
    return path


def _build(out: str) -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 24

    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.3, depth=2.0, location=(0.0, 0.0, 1.0))
    body = bpy.context.active_object
    body.name = "Body"
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=6)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.shade_smooth()

    armature_data = bpy.data.armatures.new("Rig")
    rig = bpy.data.objects.new("Rig", armature_data)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    previous = None
    for name, head, tail in (("root", 0.0, 0.7), ("spine", 0.7, 1.4), ("head", 1.4, 2.0)):
        bone = armature_data.edit_bones.new(name)
        bone.head, bone.tail = (0.0, 0.0, head), (0.0, 0.0, tail)
        if previous is not None:
            bone.parent = previous
            bone.use_connect = True
        previous = bone
    bpy.ops.object.mode_set(mode="OBJECT")

    groups = {name: body.vertex_groups.new(name=name) for name in ("root", "spine", "head")}
    for vertex in body.data.vertices:
        z = vertex.co.z + 1.0
        name = "root" if z < 0.7 else ("spine" if z < 1.4 else "head")
        groups[name].add([vertex.index], 1.0, "REPLACE")
    modifier = body.modifiers.new("Armature", "ARMATURE")
    modifier.object = rig
    body.parent = rig

    body.shape_key_add(name="Basis")
    bulge = body.shape_key_add(name="Bulge", from_mix=False)
    squash = body.shape_key_add(name="Squash", from_mix=False)
    for index, vertex in enumerate(body.data.vertices):
        co = vertex.co
        bulge.data[index].co = (co.x * 1.3, co.y * 1.3, co.z)
        squash.data[index].co = (co.x, co.y, co.z * 0.8)

    image = bpy.data.images.new("SkinTex", 32, 32)
    image.generated_type = "UV_GRID"
    image.filepath_raw = os.path.join(out, "skin.png")
    image.file_format = "PNG"
    image.save()
    material = bpy.data.materials.new("Skin")
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    shader = material.node_tree.nodes["Principled BSDF"]
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    body.data.materials.append(material)

    rig.animation_data_create()
    pose_bone = rig.pose.bones["spine"]
    pose_bone.rotation_mode = "XYZ"
    for frame, angle in ((1, 0.0), (12, 0.6), (24, 0.0)):
        pose_bone.rotation_euler = (angle, 0.0, 0.0)
        pose_bone.keyframe_insert("rotation_euler", frame=frame)
    for frame, value in ((1, 0.0), (12, 1.0), (24, 0.0)):
        bulge.value = value
        bulge.keyframe_insert("value", frame=frame)
    scene.frame_set(1)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "sample.blend"), compress=False)
    bpy.ops.export_scene.fbx(filepath=os.path.join(out, "sample.fbx"), bake_anim=True, path_mode="RELATIVE")
    bpy.ops.export_scene.gltf(filepath=os.path.join(out, "sample.glb"), export_format="GLB")
    bpy.ops.export_scene.gltf(filepath=os.path.join(out, "sample.gltf"), export_format="GLTF_SEPARATE")
    bpy.ops.wm.obj_export(filepath=os.path.join(out, "sample.obj"), export_materials=True)


def _build_autorun(out: str) -> None:
    marker = os.path.join(out, "autorun-marker.txt").replace("\\", "/")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    text = bpy.data.texts.new("autorun.py")
    text.write(f"open({marker!r}, 'w').write('text block executed')\n")
    text.use_module = True
    driver = cube.driver_add("location", 0).driver
    driver.type = "SCRIPTED"
    driver.expression = f"__import__('builtins').open({marker!r}, 'w').write('driver executed') or 0.0"
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "autorun.blend"), compress=False)


def _build_outside_texture(out: str) -> None:
    outside = os.path.join(os.path.dirname(out), "outside-texture.png")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    image = bpy.data.images.new("OutsideTex", 8, 8)
    image.filepath_raw = outside
    image.file_format = "PNG"
    image.save()
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    material = bpy.data.materials.new("Outside")
    material.use_nodes = True
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    material.node_tree.links.new(texture.outputs["Color"], material.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    cube.data.materials.append(material)
    bpy.ops.export_scene.fbx(filepath=os.path.join(out, "outside-texture.fbx"), path_mode="ABSOLUTE")


HUMANOID_BONES = (  # name, parent, head, tail (character faces -Y, its left is +X)
    ("Hips", None, (0, 0, 1.0), (0, 0, 1.1)),
    ("Spine", "Hips", (0, 0, 1.1), (0, 0, 1.45)),
    ("Neck", "Spine", (0, 0, 1.5), (0, 0, 1.6)),
    ("Head", "Neck", (0, 0, 1.6), (0, 0, 1.85)),
    ("LeftShoulder", "Spine", (0.05, 0, 1.45), (0.18, 0, 1.45)),
    ("LeftArm", "LeftShoulder", (0.18, 0, 1.45), (0.45, 0, 1.45)),
    ("LeftForeArm", "LeftArm", (0.45, 0, 1.45), (0.7, 0, 1.45)),
    ("LeftHand", "LeftForeArm", (0.7, 0, 1.45), (0.8, 0, 1.45)),
    ("RightShoulder", "Spine", (-0.05, 0, 1.45), (-0.18, 0, 1.45)),
    ("RightArm", "RightShoulder", (-0.18, 0, 1.45), (-0.45, 0, 1.45)),
    ("RightForeArm", "RightArm", (-0.45, 0, 1.45), (-0.7, 0, 1.45)),
    ("RightHand", "RightForeArm", (-0.7, 0, 1.45), (-0.8, 0, 1.45)),
    ("LeftUpLeg", "Hips", (0.1, 0, 1.0), (0.1, 0, 0.55)),
    ("LeftLeg", "LeftUpLeg", (0.1, 0, 0.55), (0.1, 0, 0.1)),
    ("LeftFoot", "LeftLeg", (0.1, 0, 0.1), (0.1, -0.12, 0.02)),
    ("RightUpLeg", "Hips", (-0.1, 0, 1.0), (-0.1, 0, 0.55)),
    ("RightLeg", "RightUpLeg", (-0.1, 0, 0.55), (-0.1, 0, 0.1)),
    ("RightFoot", "RightLeg", (-0.1, 0, 0.1), (-0.1, -0.12, 0.02)),
)


def _finger_bones() -> list:
    """Three Mixamo-style bones per finger on both hands (thumb lower and in front)."""
    bones = []
    for side, sign in (("Left", 1.0), ("Right", -1.0)):
        for finger, (z, y, start) in {"Thumb": (-0.03, -0.03, 0.74), "Index": (0.03, 0.0, 0.8),
                                       "Middle": (0.01, 0.0, 0.8), "Ring": (-0.01, 0.0, 0.8),
                                       "Pinky": (-0.03, 0.0, 0.8)}.items():
            parent = f"{side}Hand"
            for segment in (1, 2, 3):
                x0 = start + 0.025 * (segment - 1)
                name = f"{side}Hand{finger}{segment}"
                bones.append((name, parent, (sign * x0, y, 1.45 + z), (sign * (x0 + 0.025), y, 1.45 + z)))
                parent = name
    return bones


def _build_humanoid(out: str) -> None:
    import bmesh
    from mathutils import Vector

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 24
    data = bpy.data.armatures.new("HumanoidRig")
    rig = bpy.data.objects.new("HumanoidRig", data)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for name, parent, head, tail in list(HUMANOID_BONES) + _finger_bones():
        bone = data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        if parent:
            bone.parent = data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")

    mesh = bpy.data.meshes.new("HumanoidBody")
    body = bpy.data.objects.new("HumanoidBody", mesh)
    scene.collection.objects.link(body)
    bm = bmesh.new()
    owners = []
    for name, _parent, head, tail in HUMANOID_BONES:
        if name == "Hips":
            continue
        a, b = Vector(head), Vector(tail)
        centre, size = (a + b) / 2, (b - a)
        half = Vector((max(abs(size.x) / 2, 0.05), max(abs(size.y) / 2, 0.05), max(abs(size.z) / 2, 0.05)))
        result = bmesh.ops.create_cube(bm, size=1.0)
        for vertex in result["verts"]:
            vertex.co = centre + Vector((vertex.co.x * 2 * half.x, vertex.co.y * 2 * half.y, vertex.co.z * 2 * half.z))
            owners.append(name)
    bm.to_mesh(mesh)
    bm.free()
    groups = {}
    for index, name in enumerate(owners):
        groups.setdefault(name, body.vertex_groups.new(name=name) if name not in body.vertex_groups else body.vertex_groups[name])
        groups[name].add([index], 1.0, "REPLACE")
    modifier = body.modifiers.new("Armature", "ARMATURE")
    modifier.object = rig
    body.parent = rig

    rig.animation_data_create()
    arm = rig.pose.bones["LeftArm"]
    arm.rotation_mode = "XYZ"
    for frame, angle in ((1, 0.0), (12, 1.2), (24, 0.0)):
        arm.rotation_euler = (0.0, 0.0, angle)
        arm.keyframe_insert("rotation_euler", frame=frame)
    scene.frame_set(1)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=os.path.join(out, "humanoid.glb"), export_format="GLB")
    bpy.ops.export_scene.fbx(filepath=os.path.join(out, "humanoid.fbx"), bake_anim=True)


def main() -> None:
    out = _out_dir()
    _build(out)
    _build_autorun(out)
    _build_outside_texture(out)
    _build_humanoid(out)
    expected = {"bones": 3, "shape_keys": 2, "armatures": 1, "min_triangles": 100, "materials_min": 1}
    with open(os.path.join(out, "expected.json"), "w", encoding="utf-8") as handle:
        json.dump(expected, handle, indent=2)
    print("corpus:", sorted(os.listdir(out)), flush=True)


main()
# Skip Blender's C-level teardown: it can hang after exporters (Linux) and
# crashes on os._exit (Windows). Everything is written and closed here.
sys.stdout.flush()
sys.stderr.flush()
if os.name == "nt":
    import ctypes

    ctypes.windll.kernel32.TerminateProcess(ctypes.c_void_p(-1), ctypes.c_uint(0))  # current process
os._exit(0)
