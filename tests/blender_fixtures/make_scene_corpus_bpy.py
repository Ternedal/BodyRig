"""Build the scene-inspector test corpus with Blender itself.

Run inside Blender (``blender --background --factory-startup --python THIS -- OUT``)
or with the ``bpy`` module (``python THIS -- OUT``). Writes into OUT:

- ``sample.blend``, ``sample.fbx``, ``sample.glb``, ``sample.gltf`` (+ .bin, texture),
  ``sample.obj`` (+ .mtl): one skinned mesh with a 3-bone armature, two shape
  keys, a material with an image texture and one action (bone + shape keys);
- ``autorun.blend``: a registered text block and a scripted driver that would
  create ``autorun-marker.txt`` in OUT if Blender ever executed them;
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


def main() -> None:
    out = _out_dir()
    _build(out)
    _build_autorun(out)
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

    ctypes.windll.kernel32.TerminateProcess(ctypes.windll.kernel32.GetCurrentProcess(), 0)
os._exit(0)
