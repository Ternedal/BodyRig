"""Hip/groin skin-weight transfer from a reference body, INSIDE Blender (#1401).

Staged next to ``blender_vrm_worker.py``; only called when the host passes
``--weight-reference``. Third-party rigs often weight the pelvis/thigh/groin
area badly (whole patches bound to the hips bone), so the body tears or
collapses when the legs move. This takes those weights from a reference body
with a good rig (for example the owner's own twin, or a Daz/MPFB base):

1. both skeletons are mapped with ``humanoid_names``; hips, head and the region
   bones must be found in both, otherwise nothing is changed;
2. the reference is aligned to the target: uniform scale from the hips→head
   distance, translation of the hips. No rotation: both are upright Z-up after
   import (assumption, reported);
3. region vertices of the target are the ones whose weights on the region bones
   sum to at least ``threshold``;
4. for each region vertex, the nearest reference surface point (BVH, rest
   pose) gives barycentric-interpolated region weights;
5. the region's total weight per vertex is kept and redistributed in the
   reference's proportions; weights on other bones are untouched, so every
   vertex keeps its total;
6. if the median distance to the reference surface is too large relative to
   the hips→head distance, the reference does not fit: nothing is changed.

Works on meshes with shape keys (no modifier is applied). The reference objects
are deleted afterwards so they never reach the VRM.
"""

from __future__ import annotations

import statistics

import bpy
from mathutils import Matrix
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc

import humanoid_names

DEFAULT_REGION = ("hips", "spine", "left_upper_leg", "right_upper_leg")


def _bound_meshes(armature) -> list:
    return [o for o in bpy.data.objects if o.type == "MESH" and
            any(m.type == "ARMATURE" and m.object == armature for m in o.modifiers)]


def _bone_world(armature, name: str):
    return armature.matrix_world @ armature.data.bones[name].head_local


def _alignment(target_arm, target_map: dict, ref_arm, ref_map: dict) -> tuple[Matrix, float, dict]:
    """Matrix taking reference world coordinates into target world coordinates."""
    t_hips, t_head = _bone_world(target_arm, target_map["hips"]), _bone_world(target_arm, target_map["head"])
    r_hips, r_head = _bone_world(ref_arm, ref_map["hips"]), _bone_world(ref_arm, ref_map["head"])
    t_len, r_len = (t_head - t_hips).length, (r_head - r_hips).length
    if t_len <= 1e-6 or r_len <= 1e-6:
        raise ValueError("degenerate hips/head distance")
    scale = t_len / r_len
    matrix = Matrix.Translation(t_hips) @ Matrix.Scale(scale, 4) @ Matrix.Translation(-r_hips)
    return matrix, t_len, {"scale": round(scale, 5), "hips_to_head_target": round(t_len, 5),
                           "rotation": "none (both assumed upright after import)"}


class _Reference:
    """BVH trees of the reference meshes in target space, with per-vertex region weights."""

    def __init__(self, meshes: list, ref_map: dict, region: tuple, to_target: Matrix) -> None:
        name_to_key = {ref_map[key]: key for key in region if key in ref_map}
        self.parts = []
        for obj in meshes:
            mesh = obj.data
            world = to_target @ obj.matrix_world
            verts = [world @ v.co for v in mesh.vertices]  # rest pose: basis coordinates
            polys = [tuple(p.vertices) for p in mesh.polygons]
            if not polys:
                continue
            group_key = {g.index: name_to_key[g.name] for g in obj.vertex_groups if g.name in name_to_key}
            weights = []
            for v in mesh.vertices:
                row = dict.fromkeys(region, 0.0)
                for g in v.groups:
                    key = group_key.get(g.group)
                    if key:
                        row[key] += g.weight
                weights.append(row)
            self.parts.append((BVHTree.FromPolygons(verts, polys), verts, polys, weights))
        if not self.parts:
            raise ValueError("the reference has no skinned faces")

    def lookup(self, co):
        best = None
        for tree, verts, polys, weights in self.parts:
            hit = tree.find_nearest(co)
            if hit[0] is not None and (best is None or hit[3] < best[0]):
                best = (hit[3], hit[0], hit[2], verts, polys, weights)
        if best is None:
            return None, None
        distance, location, face, verts, polys, weights = best
        corners = polys[face]
        factors = poly_3d_calc([verts[i] for i in corners], location)
        mixed = dict.fromkeys(weights[corners[0]], 0.0)
        for factor, index in zip(factors, corners):
            for key, value in weights[index].items():
                mixed[key] += factor * value
        return distance, mixed


def transfer(target_arm, target_map: dict, ref_objects: list, *, region: tuple = DEFAULT_REGION,
             threshold: float = 0.5, max_distance_ratio: float = 0.15) -> dict:
    """Transfer region weights onto the target; returns a report. Never raises for a bad fit."""
    report: dict = {"applied": False, "region": list(region), "threshold": threshold,
                    "max_distance_ratio": max_distance_ratio}
    ref_arms = [o for o in ref_objects if o.type == "ARMATURE"]
    if not ref_arms:
        report["reason"] = "the reference has no armature"
        return report
    ref_arm = max(ref_arms, key=lambda a: len(a.data.bones))
    ref_map = humanoid_names.map_bones(b.name for b in ref_arm.data.bones)
    needed = {"hips", "head", *region}
    missing_ref = sorted(k for k in needed if k not in ref_map)
    missing_target = sorted(k for k in needed if k not in target_map)
    if missing_ref or missing_target:
        report["reason"] = (f"bones not found: reference {missing_ref or '-'}, target {missing_target or '-'}")
        return report
    to_target, unit, report["alignment"] = _alignment(target_arm, target_map, ref_arm, ref_map)
    try:
        reference = _Reference(_bound_meshes(ref_arm), ref_map, region, to_target)
    except ValueError as exc:
        report["reason"] = str(exc)
        return report

    # Pass 1: find region vertices and their reference weights; do not write yet.
    plan = []
    distances = []
    for obj in _bound_meshes(target_arm):
        groups = {key: obj.vertex_groups.get(target_map[key]) for key in region}
        index_key = {g.index: key for key, g in groups.items() if g is not None}
        world = obj.matrix_world
        for v in obj.data.vertices:
            current = dict.fromkeys(region, 0.0)
            for g in v.groups:
                key = index_key.get(g.group)
                if key:
                    current[key] += g.weight
            mass = sum(current.values())
            if mass < threshold:
                continue
            distance, mixed = reference.lookup(world @ v.co)
            if mixed is None:
                continue
            distances.append(distance)
            total = sum(mixed.values())
            if total <= 1e-6:
                continue  # the reference has no region weight here: keep the source weights
            plan.append((obj, v.index, mass, current, {k: mass * w / total for k, w in mixed.items()}))
    report["region_vertices"] = len(distances)
    if not distances:
        report["reason"] = "no target vertex is in the region"
        return report
    median_ratio = statistics.median(distances) / unit
    report["median_distance_ratio"] = round(median_ratio, 4)
    if median_ratio > max_distance_ratio:
        report["reason"] = "the reference does not fit the target (median surface distance too large)"
        return report

    # Pass 2: write.
    changed = 0
    moved = dict.fromkeys(region, 0.0)
    for obj, index, _mass, before, after in plan:
        for key in region:
            group = obj.vertex_groups.get(target_map[key]) or obj.vertex_groups.new(name=target_map[key])
            value = after[key]
            if value > 1e-6:
                group.add([index], value, "REPLACE")
            elif before[key] > 0:
                group.remove([index])
            moved[key] += value - before[key]
        if any(abs(after[k] - before[k]) > 1e-4 for k in region):
            changed += 1
    report.update(applied=True, changed_vertices=changed,
                  weight_moved={k: round(v, 3) for k, v in moved.items()})
    return report


def remove_objects(objects: list) -> None:
    """Delete the reference objects and their now-unused data, so nothing reaches the VRM."""
    data = []
    for obj in objects:
        if obj.data is not None:
            data.append(obj.data)
        bpy.data.objects.remove(obj, do_unlink=True)
    for block in data:
        if block.users == 0:
            for collection in (bpy.data.meshes, bpy.data.armatures):
                if block.name in collection and collection[block.name] == block:
                    collection.remove(block)
                    break
