from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-fidelity-component-gap-plan"
VERSION = 1
VISIBILITY_FORMAT = "bodyrig-component-visibility-probe"
VISIBILITY_SEMANTICS = "component-presence-and-runtime-visibility-not-visual-quality-acceptance"
SEMANTICS = "physical-component-gap-planning-not-visual-or-release-acceptance"
REQUIRED_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("hair", "BodyRigSourceHairReview"),
    ("eyes", "BodyRigSourceEyeReview"),
    ("face-secondary", "BodyRigFaceSecondaryReview"),
    ("fingernails", "BodyRigFingernailPlates"),
    ("toenails", "BodyRigToenailPlates"),
)
ENTRY_FIELDS = {
    "label",
    "node_name",
    "present_in_avatar_bytes",
    "instantiated",
    "active_in_hierarchy",
    "visible_skinned_renderer",
    "visible_renderer_count",
}
REPORT_FIELDS = {
    "format",
    "version",
    "observed_at",
    "bodyrig_revision",
    "platform",
    "body_id",
    "package_sha256",
    "avatar_sha256",
    "required_component_count",
    "present_component_count",
    "visible_component_count",
    "all_required_present_and_visible",
    "components",
    "human_visual_authority_required",
    "production_activation",
    "semantics",
}


class FidelityComponentGapError(ValueError):
    pass


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FidelityComponentGapError(f"{label} is missing or symlinked: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FidelityComponentGapError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FidelityComponentGapError(f"{label} must be an object")
    return value


def _sha256(value: Any, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise FidelityComponentGapError(f"{field} must be a canonical lowercase SHA-256")
    return text


def _git_sha(value: Any, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise FidelityComponentGapError(f"{field} must be a canonical lowercase Git SHA")
    return text


def _nonempty(value: Any, *, field: str, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise FidelityComponentGapError(f"{field} is invalid")
    return value.strip()


def _integer(value: Any, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FidelityComponentGapError(f"{field} is invalid")
    return value


def validate_visibility_report(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != REPORT_FIELDS:
        raise FidelityComponentGapError("component visibility probe fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != VISIBILITY_FORMAT or isinstance(version, bool) or version != 1:
        raise FidelityComponentGapError("component visibility probe format/version mismatch")
    if value.get("semantics") != VISIBILITY_SEMANTICS:
        raise FidelityComponentGapError("component visibility probe semantics mismatch")
    if value.get("human_visual_authority_required") is not True or value.get("production_activation") is not False:
        raise FidelityComponentGapError("component visibility probe crossed its authority boundary")

    revision = _git_sha(value.get("bodyrig_revision"), field="bodyrig_revision")
    observed_at = _nonempty(value.get("observed_at"), field="observed_at", maximum=100)
    platform = value.get("platform")
    if platform not in {"windows-unity-univrm", "android-quest-class"}:
        raise FidelityComponentGapError("component visibility platform is invalid")
    body_id = _nonempty(value.get("body_id"), field="body_id", maximum=160)
    package_sha = _sha256(value.get("package_sha256"), field="package_sha256")
    avatar_sha = _sha256(value.get("avatar_sha256"), field="avatar_sha256")

    required_count = _integer(value.get("required_component_count"), field="required_component_count")
    present_count = _integer(value.get("present_component_count"), field="present_component_count")
    visible_count = _integer(value.get("visible_component_count"), field="visible_component_count")
    if required_count != len(REQUIRED_COMPONENTS):
        raise FidelityComponentGapError("component visibility required_component_count is invalid")

    raw_components = value.get("components")
    if not isinstance(raw_components, list) or len(raw_components) != len(REQUIRED_COMPONENTS):
        raise FidelityComponentGapError("component visibility probe must contain all required components exactly once")

    expected_nodes = dict(REQUIRED_COMPONENTS)
    components: dict[str, dict[str, Any]] = {}
    for raw in raw_components:
        if not isinstance(raw, Mapping) or set(raw) != ENTRY_FIELDS:
            raise FidelityComponentGapError("component visibility entry fields must match v1 exactly")
        label = raw.get("label")
        if not isinstance(label, str) or label not in expected_nodes or label in components:
            raise FidelityComponentGapError("component visibility label is invalid or duplicated")
        if raw.get("node_name") != expected_nodes[label]:
            raise FidelityComponentGapError(f"component visibility node mismatch for {label}")
        flags: dict[str, bool] = {}
        for field in (
            "present_in_avatar_bytes",
            "instantiated",
            "active_in_hierarchy",
            "visible_skinned_renderer",
        ):
            flag = raw.get(field)
            if not isinstance(flag, bool):
                raise FidelityComponentGapError(f"component visibility {label}.{field} must be boolean")
            flags[field] = flag
        renderer_count = _integer(raw.get("visible_renderer_count"), field=f"{label}.visible_renderer_count")
        if flags["instantiated"] and not flags["present_in_avatar_bytes"]:
            raise FidelityComponentGapError(f"component visibility {label} is instantiated without source presence")
        if flags["active_in_hierarchy"] and not flags["instantiated"]:
            raise FidelityComponentGapError(f"component visibility {label} is active without instantiation")
        if flags["visible_skinned_renderer"] and not flags["active_in_hierarchy"]:
            raise FidelityComponentGapError(f"component visibility {label} is visible without an active hierarchy")
        if flags["visible_skinned_renderer"] != (renderer_count > 0):
            raise FidelityComponentGapError(f"component visibility {label} renderer count disagrees with visibility flag")
        components[label] = {
            "label": label,
            "node_name": expected_nodes[label],
            **flags,
            "visible_renderer_count": renderer_count,
        }

    observed_present = sum(1 for item in components.values() if item["present_in_avatar_bytes"])
    observed_visible = sum(1 for item in components.values() if item["visible_skinned_renderer"])
    observed_complete = all(
        item["present_in_avatar_bytes"]
        and item["instantiated"]
        and item["active_in_hierarchy"]
        and item["visible_skinned_renderer"]
        and item["visible_renderer_count"] >= 1
        for item in components.values()
    )
    if present_count != observed_present or visible_count != observed_visible:
        raise FidelityComponentGapError("component visibility aggregate counts do not match component entries")
    aggregate = value.get("all_required_present_and_visible")
    if not isinstance(aggregate, bool) or aggregate is not observed_complete:
        raise FidelityComponentGapError("component visibility aggregate completeness disagrees with component entries")

    return {
        "format": VISIBILITY_FORMAT,
        "version": 1,
        "observed_at": observed_at,
        "bodyrig_revision": revision,
        "platform": platform,
        "body_id": body_id,
        "package_sha256": package_sha,
        "avatar_sha256": avatar_sha,
        "required_component_count": required_count,
        "present_component_count": present_count,
        "visible_component_count": visible_count,
        "all_required_present_and_visible": observed_complete,
        "components": components,
        "human_visual_authority_required": True,
        "production_activation": False,
        "semantics": VISIBILITY_SEMANTICS,
    }


def build_gap_plan(report: Mapping[str, Any], *, render_set: Mapping[str, Any] | None = None) -> dict[str, Any]:
    visibility = validate_visibility_report(report)
    if render_set is not None:
        if not isinstance(render_set, Mapping):
            raise FidelityComponentGapError("fidelity render set must be an object")
        if render_set.get("body_id") != visibility["body_id"]:
            raise FidelityComponentGapError("component visibility body_id differs from fidelity render set")
        if _sha256(render_set.get("package_sha256"), field="render_set.package_sha256") != visibility["package_sha256"]:
            raise FidelityComponentGapError("component visibility package differs from fidelity render set")

    ordered_labels = [label for label, _node in REQUIRED_COMPONENTS]
    drawable = [label for label in ordered_labels if visibility["components"][label]["visible_skinned_renderer"]]
    missing = [label for label in ordered_labels if label not in drawable]
    actions: list[dict[str, Any]] = []

    hair_eye_missing = [label for label in ("hair", "eyes") if label in missing]
    if hair_eye_missing:
        actions.append(
            {
                "id": "retained-source-hair-eye-composition",
                "components": hair_eye_missing,
                "operator_input_required": False,
                "implementation_required": False,
                "reason": "Rebuild the comparison-only source hair+eye runtime from the retained reconstruction and require Unity drawability before rescoring.",
            }
        )
    if "face-secondary" in missing:
        actions.append(
            {
                "id": "face-secondary-review-composition",
                "components": ["face-secondary"],
                "operator_input_required": False,
                "implementation_required": False,
                "reason": "Run the existing comparison-only face-secondary runtime composer for mouth/teeth/eyelash geometry on the same review avatar without promotion or release authority.",
            }
        )
    hfn_missing = [label for label in ("fingernails", "toenails") if label in missing]
    if hfn_missing:
        actions.append(
            {
                "id": "source-bound-hfn-continuation",
                "components": hfn_missing,
                "operator_input_required": True,
                "implementation_required": False,
                "reason": "Continue the exact source-bound HFN candidate; capture/UV evidence may be required before geometry materialization.",
            }
        )
    if not missing:
        actions.append(
            {
                "id": "human-visual-qa",
                "components": ordered_labels,
                "operator_input_required": True,
                "implementation_required": False,
                "reason": "All machine-required components are physically drawable; visual quality still requires human review and does not imply release acceptance.",
            }
        )

    return {
        "format": FORMAT,
        "version": VERSION,
        "bodyrig_revision": visibility["bodyrig_revision"],
        "body_id": visibility["body_id"],
        "package_sha256": visibility["package_sha256"],
        "state": "machine-component-complete-human-review-required" if not missing else "composition-required",
        "drawable_components": drawable,
        "missing_components": missing,
        "next_actions": actions,
        "strict_machine_scoring_ready": not missing,
        "human_visual_authority_required": True,
        "production_activation": False,
        "semantics": SEMANTICS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan the next BodyRig fidelity component-composition step from physical Unity evidence.")
    parser.add_argument("--visibility-probe", required=True)
    parser.add_argument("--render-set", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        visibility_path = Path(args.visibility_probe).expanduser().resolve()
        report = _read_object(visibility_path, label="component visibility probe")
        render_set = None
        if args.render_set:
            render_set = _read_object(Path(args.render_set).expanduser().resolve(), label="fidelity render set")
        result = build_gap_plan(report, render_set=render_set)
        out = Path(args.out).expanduser().resolve()
        if out.exists():
            raise FidelityComponentGapError(f"component gap-plan output already exists: {out}")
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except (FidelityComponentGapError, OSError) as exc:
        print(f"BodyRig fidelity component gap plan: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
