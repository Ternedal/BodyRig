#!/usr/bin/env python
"""BodyRig fidelity evaluator revision 5 silhouette correction.

Revision 4 normalized sampled body widths by the subject bounding-box width.
That made the silhouette metric depend on horizontal arm span: the same torso in
an A/T/rest pose could look much narrower than a source frame with relaxed arms.

Revision 5 deliberately reuses the complete revision-4 evaluator and changes
only width-profile normalization to subject height.  The controlled BodyPrint
fields driven by these hints are shoulder_to_height and hip_to_height, so height
is also the dimensionally correct normalization authority.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


BASE_PATH = Path(__file__).resolve().with_name("opencv_fidelity_evaluator.py")


def _load_base() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_bodyrig_opencv_fidelity_evaluator_v4", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load BodyRig fidelity evaluator revision 4 base")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_BASE = _load_base()


def width_profile(cv2: Any, mask: Any) -> list[float]:
    """Return sampled subject widths as fractions of subject height.

    Height normalization makes the torso profile invariant to unrelated
    horizontal arm span while retaining scale invariance between source capture
    and canonical render.  Values therefore correspond to the semantics of the
    BodyPrint shoulder_to_height / hip_to_height controls.
    """

    subject = _BASE.crop_mask_to_subject(cv2, mask)
    height, _width = subject.shape[:2]
    rows = (0.12, 0.20, 0.28, 0.36, 0.46, 0.56, 0.66, 0.78, 0.90)
    result: list[float] = []
    for fraction in rows:
        center = min(height - 1, max(0, int(round((height - 1) * fraction))))
        y0, y1 = max(0, center - 2), min(height, center + 3)
        values: list[float] = []
        for row in subject[y0:y1]:
            xs = (row > 0).nonzero()[0]
            if len(xs):
                values.append((int(xs[-1]) - int(xs[0]) + 1) / float(height))
        result.append(sum(values) / len(values) if values else 0.0)
    return result


def main() -> int:
    _BASE.REVISION = "5"
    _BASE.width_profile = width_profile
    return int(_BASE.main())


if __name__ == "__main__":
    raise SystemExit(main())
