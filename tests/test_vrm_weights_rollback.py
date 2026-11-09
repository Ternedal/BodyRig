"""Weight transfer failure paths (#1402 review by ChatGPT, P2).

Runs the real ``blender_vrm_worker._weight_transfer`` and
``blender_vrm_weights._apply_plan`` against a fake ``bpy``/``mathutils``:

- a reference that imports part-way and then fails is removed, and the export goes on;
- a transfer that fails before writing, or while writing, never aborts the export;
- a write that fails part-way is rolled back exactly (weights and created groups);
- if cleanup or rollback cannot be completed, the failure is strict.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import types
from pathlib import Path

import pytest

WORKER_DIR = str(Path(__file__).resolve().parents[1] / "bodyrig")
STAGED = ("blender_vrm_worker", "blender_vrm_weights", "blender_scene_worker", "humanoid_names", "vrm_paths")


# --- fakes with Blender's semantics ---------------------------------------------------------

class FakeGroup:
    def __init__(self, name: str, fail_after: list | None = None):
        self.name = name
        self.weights: dict[int, float] = {}
        self.fail_after = fail_after  # shared countdown: raise when it reaches zero

    def _tick(self):  # fails exactly once, on the countdown's write; later writes (the restore) work
        if self.fail_after is not None:
            self.fail_after[0] -= 1
            if self.fail_after[0] == -1:
                raise RuntimeError("injected write failure")

    def add(self, indices, weight, mode):
        self._tick()
        for i in indices:
            self.weights[i] = weight

    def remove(self, indices):  # Blender: non-members are ignored (prints, does not raise)
        self._tick()
        for i in indices:
            self.weights.pop(i, None)


class FakeGroups:
    def __init__(self, obj, fail_after=None):
        self.obj = obj
        self.items: list[FakeGroup] = []
        self.fail_after = fail_after
        self.fail_remove = False

    def get(self, name):
        return next((g for g in self.items if g.name == name), None)

    def new(self, name):
        group = FakeGroup(name, self.fail_after)
        self.items.append(group)
        return group

    def remove(self, group):
        if self.fail_remove:
            raise RuntimeError("injected group removal failure")
        self.items.remove(group)


class FakeObject:
    def __init__(self, name, fail_after=None):
        self.name = name
        self.data = None
        self.type = "MESH"
        self.vertex_groups = FakeGroups(self, fail_after)


class FakeObjects(list):
    fail = False

    def remove(self, obj, do_unlink=True):  # noqa: D401 - mimics bpy.data.objects.remove
        if FakeObjects.fail:
            raise RuntimeError("injected object removal failure")
        super().remove(obj)


@pytest.fixture()
def staged(monkeypatch):
    fake_bpy = types.ModuleType("bpy")
    fake_bpy.data = types.SimpleNamespace(objects=FakeObjects(), images=[], meshes=[], armatures=[])
    fake_bpy.path = types.SimpleNamespace(abspath=lambda p: p)
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    mathutils = types.ModuleType("mathutils")
    mathutils.Matrix = object
    bvh = types.ModuleType("mathutils.bvhtree")
    bvh.BVHTree = object
    interp = types.ModuleType("mathutils.interpolate")
    interp.poly_3d_calc = lambda *a: None
    for name, module in (("mathutils", mathutils), ("mathutils.bvhtree", bvh), ("mathutils.interpolate", interp)):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.syspath_prepend(WORKER_DIR)
    for name in STAGED:
        monkeypatch.delitem(sys.modules, name, raising=False)
    worker = importlib.import_module("blender_vrm_worker")
    weights = importlib.import_module("blender_vrm_weights")
    FakeObjects.fail = False
    yield worker, weights, fake_bpy
    FakeObjects.fail = False
    for name in STAGED:
        sys.modules.pop(name, None)


def _args(tmp_path: Path, fmt: str = "fbx") -> argparse.Namespace:
    root = tmp_path / "ref"
    root.mkdir(exist_ok=True)
    (root / "twin.fbx").write_bytes(b"x")
    return argparse.Namespace(weight_reference=str(root / "twin.fbx"), weight_reference_format=fmt,
                              weight_reference_root=str(root))


def _document() -> dict:
    return {"addons": {}, "security": {}, "warnings": []}


# --- worker: cleanup on every path ----------------------------------------------------------

def test_partial_import_failure_is_cleaned_up_and_export_continues(staged, tmp_path, monkeypatch):
    worker, _weights, bpy = staged
    target = FakeObject("Body")
    bpy.data.objects.append(target)

    def half_import(path, fmt, root, addons):
        bpy.data.objects.extend([FakeObject("RefArmature"), FakeObject("RefBody")])
        raise RuntimeError("corrupt reference")

    monkeypatch.setattr(worker, "_import", half_import)
    document = _document()
    report = worker._weight_transfer(target, {}, _args(tmp_path), document)
    assert report["applied"] is False and "reference import failed" in report["reason"]
    assert list(bpy.data.objects) == [target]
    assert any("not applied" in w for w in document["warnings"])


@pytest.mark.parametrize("error, expected", [
    ("rolled_back", "rolled back"),
    ("before_write", "before writing"),
])
def test_transfer_failure_never_aborts_and_always_cleans_up(staged, tmp_path, monkeypatch, error, expected):
    worker, weights, bpy = staged
    target = FakeObject("Body")
    bpy.data.objects.append(target)
    monkeypatch.setattr(worker, "_import", lambda *a: bpy.data.objects.append(FakeObject("RefBody")))
    monkeypatch.setattr(worker.shared, "_harden_preferences", lambda: {})

    def failing_transfer(*_a, **_k):
        if error == "rolled_back":
            raise weights.TransferRolledBack("RuntimeError: disk full")
        raise ValueError("degenerate hips/head distance")

    monkeypatch.setattr(weights, "transfer", failing_transfer)
    report = worker._weight_transfer(target, {}, _args(tmp_path), _document())
    assert report["applied"] is False and expected in report["reason"]
    assert report.get("rolled_back", False) is (error == "rolled_back")
    assert list(bpy.data.objects) == [target]


def test_cleanup_that_cannot_be_proven_is_a_hard_failure(staged, tmp_path, monkeypatch):
    worker, weights, bpy = staged
    target = FakeObject("Body")
    bpy.data.objects.append(target)
    monkeypatch.setattr(worker, "_import", lambda *a: bpy.data.objects.append(FakeObject("RefBody")))
    monkeypatch.setattr(worker.shared, "_harden_preferences", lambda: {})
    monkeypatch.setattr(weights, "transfer", lambda *a, **k: {"applied": True})
    FakeObjects.fail = True
    with pytest.raises(RuntimeError, match="could not remove the reference objects"):
        worker._weight_transfer(target, {}, _args(tmp_path), _document())


# --- weights: transactional write -----------------------------------------------------------

REGION = ("hips", "left_upper_leg")
TARGET_MAP = {"hips": "root hips", "left_upper_leg": "leg left thigh"}


def _body(fail_after: int | None):
    countdown = [fail_after] if fail_after is not None else None
    body = FakeObject("Body", countdown)
    hips = body.vertex_groups.new("root hips")
    hips.weights = {0: 1.0, 1: 1.0, 2: 1.0, 3: 0.4}
    other = body.vertex_groups.new("leg left knee")  # outside the region: never touched
    other.weights = {3: 0.6}
    # "leg left thigh" does not exist yet: the transfer has to create it
    plan = [(body, i, 1.0 if i < 3 else 0.4,
             {"hips": 1.0 if i < 3 else 0.4, "left_upper_leg": 0.0},
             {"hips": 0.5 if i < 3 else 0.2, "left_upper_leg": 0.5 if i < 3 else 0.2}) for i in range(4)]
    return body, plan


def _snapshot(body) -> dict:
    return {g.name: dict(g.weights) for g in body.vertex_groups.items}


def test_apply_plan_writes_everything(staged):
    _worker, weights, _bpy = staged
    body, plan = _body(fail_after=None)
    changed, moved = weights._apply_plan(plan, REGION, TARGET_MAP)
    assert changed == 4 and round(moved["hips"], 3) == -1.7 and round(moved["left_upper_leg"], 3) == 1.7
    assert _snapshot(body)["leg left thigh"] == {0: 0.5, 1: 0.5, 2: 0.5, 3: 0.2}
    assert _snapshot(body)["leg left knee"] == {3: 0.6}


@pytest.mark.parametrize("fail_after", [0, 1, 2, 3, 5, 7])  # fail on every possible write position
def test_apply_plan_failure_is_rolled_back_exactly(staged, fail_after):
    _worker, weights, _bpy = staged
    body, plan = _body(fail_after=None)
    original = _snapshot(body)
    countdown = [fail_after]
    for group in body.vertex_groups.items:
        group.fail_after = countdown
    body.vertex_groups.fail_after = countdown
    with pytest.raises(weights.TransferRolledBack, match="injected write failure"):
        weights._apply_plan(plan, REGION, TARGET_MAP)
    assert _snapshot(body) == original  # same weights, and the created group is gone


def test_rollback_that_cannot_complete_is_not_reported_as_rolled_back(staged):
    _worker, weights, _bpy = staged
    body, plan = _body(fail_after=None)
    countdown = [4]
    for group in body.vertex_groups.items:
        group.fail_after = countdown
    body.vertex_groups.fail_after = countdown
    body.vertex_groups.fail_remove = True  # the created group cannot be removed again
    with pytest.raises(RuntimeError) as err:
        weights._apply_plan(plan, REGION, TARGET_MAP)
    assert not isinstance(err.value, weights.TransferRolledBack)
