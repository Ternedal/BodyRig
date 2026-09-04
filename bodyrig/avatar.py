from __future__ import annotations

import binascii
import json
import math
import struct
import zlib
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

VRM_EXTENSION = "VRMC_vrm"
VRM_SPEC_VERSION = "1.0"

REQUIRED_HUMAN_BONES = (
    "hips",
    "spine",
    "head",
    "leftUpperLeg",
    "leftLowerLeg",
    "leftFoot",
    "rightUpperLeg",
    "rightLowerLeg",
    "rightFoot",
    "leftUpperArm",
    "leftLowerArm",
    "leftHand",
    "rightUpperArm",
    "rightLowerArm",
    "rightHand",
)


class AvatarError(ValueError):
    pass


@dataclass(frozen=True)
class AvatarFitResult:
    avatar_vrm: bytes
    thumbnail_png: bytes
    adapter: str
    revision: str


class AvatarFitter(Protocol):
    name: str
    revision: str

    def fit(self, bodyprint: Mapping[str, Any], *, name: str) -> AvatarFitResult: ...


def parse_glb_json(data: bytes) -> dict[str, Any]:
    if len(data) < 20 or data[:4] != b"glTF":
        raise AvatarError("avatar: invalid GLB magic")
    if int.from_bytes(data[4:8], "little") != 2:
        raise AvatarError("avatar: GLB version must be 2")
    if int.from_bytes(data[8:12], "little") != len(data):
        raise AvatarError("avatar: GLB declared length mismatch")
    offset = 12
    document: dict[str, Any] | None = None
    while offset < len(data):
        if offset + 8 > len(data):
            raise AvatarError("avatar: truncated GLB chunk header")
        chunk_length = int.from_bytes(data[offset : offset + 4], "little")
        chunk_type = data[offset + 4 : offset + 8]
        offset += 8
        end = offset + chunk_length
        if end > len(data):
            raise AvatarError("avatar: truncated GLB chunk")
        chunk = data[offset:end]
        offset = end
        if chunk_type == b"JSON":
            if document is not None:
                raise AvatarError("avatar: multiple JSON chunks")
            try:
                decoded = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AvatarError("avatar: invalid glTF JSON") from exc
            if not isinstance(decoded, dict):
                raise AvatarError("avatar: glTF JSON must be an object")
            document = decoded
    if document is None:
        raise AvatarError("avatar: missing GLB JSON chunk")
    return document


def validate_vrm1(data: bytes) -> dict[str, Any]:
    document = parse_glb_json(data)
    asset = document.get("asset")
    if not isinstance(asset, dict) or asset.get("version") != "2.0":
        raise AvatarError("avatar: glTF asset.version must be 2.0")
    used = document.get("extensionsUsed")
    if not isinstance(used, list) or VRM_EXTENSION not in used:
        raise AvatarError("avatar: VRMC_vrm must be listed in extensionsUsed")
    extensions = document.get("extensions")
    if not isinstance(extensions, dict):
        raise AvatarError("avatar: missing extensions")
    vrm = extensions.get(VRM_EXTENSION)
    if not isinstance(vrm, dict) or vrm.get("specVersion") != VRM_SPEC_VERSION:
        raise AvatarError("avatar: missing VRM 1.0 extension")

    meta = vrm.get("meta")
    if not isinstance(meta, dict):
        raise AvatarError("avatar: missing VRM meta")
    name = meta.get("name")
    authors = meta.get("authors")
    license_url = meta.get("licenseUrl")
    if not isinstance(name, str) or not name.strip():
        raise AvatarError("avatar: VRM meta.name is required")
    if not isinstance(authors, list) or not authors or not all(isinstance(item, str) and item.strip() for item in authors):
        raise AvatarError("avatar: VRM meta.authors is required")
    if not isinstance(license_url, str) or not license_url.strip():
        raise AvatarError("avatar: VRM meta.licenseUrl is required")

    nodes = document.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise AvatarError("avatar: glTF nodes are required")
    humanoid = vrm.get("humanoid")
    if not isinstance(humanoid, dict):
        raise AvatarError("avatar: missing VRM humanoid")
    human_bones = humanoid.get("humanBones")
    if not isinstance(human_bones, dict):
        raise AvatarError("avatar: missing VRM humanBones")

    seen_nodes: set[int] = set()
    for bone_name in REQUIRED_HUMAN_BONES:
        entry = human_bones.get(bone_name)
        if not isinstance(entry, dict) or set(entry) != {"node"}:
            raise AvatarError(f"avatar: missing/invalid required humanoid bone {bone_name}")
        node_index = entry["node"]
        if isinstance(node_index, bool) or not isinstance(node_index, int) or not 0 <= node_index < len(nodes):
            raise AvatarError(f"avatar: invalid node for humanoid bone {bone_name}")
        if node_index in seen_nodes:
            raise AvatarError("avatar: humanoid bones must reference unique nodes")
        seen_nodes.add(node_index)
        node = nodes[node_index]
        if not isinstance(node, dict):
            raise AvatarError(f"avatar: node for {bone_name} must be an object")
        scale = node.get("scale")
        if scale is not None:
            if (
                not isinstance(scale, list)
                or len(scale) != 3
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0 for value in scale)
            ):
                raise AvatarError(f"avatar: humanoid bone {bone_name} must have positive finite scale")
    return document


def _pad4(data: bytes, pad_byte: bytes) -> bytes:
    return data + pad_byte * ((-len(data)) % 4)


def _glb(document: Mapping[str, Any], binary: bytes) -> bytes:
    json_chunk = _pad4(
        json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"),
        b" ",
    )
    bin_chunk = _pad4(binary, b"\x00")
    chunks = struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
    if bin_chunk:
        chunks += struct.pack("<I4s", len(bin_chunk), b"BIN\x00") + bin_chunk
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


def _thumbnail_png(width: int = 128, height: int = 128) -> bytes:
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            # Neutral transparent-background silhouette. This is deliberately a
            # placeholder and does not claim source-derived face identity.
            nx = (x - width / 2) / width
            ny = y / height
            head = nx * nx + ((ny - 0.22) / 0.12) ** 2 < 0.025
            torso = 0.34 < ny < 0.72 and abs(nx) < 0.15 + 0.04 * (0.72 - ny)
            legs = ny >= 0.69 and (abs(nx - 0.065) < 0.055 or abs(nx + 0.065) < 0.055)
            arms = 0.39 < ny < 0.68 and abs(nx) < 0.29 and not torso
            alpha = 255 if head or torso or legs or arms else 0
            row.extend((210, 210, 210, alpha))
        rows.append(bytes(row))
    raw = b"".join(rows)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(raw, 9)) + _png_chunk(b"IEND", b"")


def _cube_geometry() -> tuple[bytes, list[dict[str, Any]], list[dict[str, Any]]]:
    positions = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    ]
    indices = [
        0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6,
        0, 4, 5, 0, 5, 1, 3, 2, 6, 3, 6, 7,
        1, 5, 6, 1, 6, 2, 0, 3, 7, 0, 7, 4,
    ]
    pos_bytes = b"".join(struct.pack("<fff", *p) for p in positions)
    idx_offset = len(pos_bytes)
    idx_bytes = b"".join(struct.pack("<H", i) for i in indices)
    binary = pos_bytes + idx_bytes
    buffer_views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962},
        {"buffer": 0, "byteOffset": idx_offset, "byteLength": len(idx_bytes), "target": 34963},
    ]
    accessors = [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": len(positions),
            "type": "VEC3",
            "min": [-0.5, -0.5, -0.5],
            "max": [0.5, 0.5, 0.5],
        },
        {"bufferView": 1, "componentType": 5123, "count": len(indices), "type": "SCALAR"},
    ]
    return binary, buffer_views, accessors


class ProceduralAvatarFitter:
    """Deterministic V1 placeholder avatar whose proportions come from BodyPrint.

    The fitter intentionally does not claim face/hair/clothing identity fidelity.
    Its job is to prove the portable BodyPrint -> VRM 1.0 runtime path while the
    higher-fidelity reconstruction adapter remains replaceable.
    """

    name = "procedural-vrm1"
    revision = "builtin-v1"

    @staticmethod
    def _shape(bodyprint: Mapping[str, Any]) -> dict[str, float]:
        if bodyprint.get("format") != "modelrig-bodyprint" or bodyprint.get("version") != 1:
            raise AvatarError("bodyprint: unsupported format/version")
        raw = bodyprint.get("shape")
        if not isinstance(raw, dict):
            raise AvatarError("bodyprint.shape is required for avatar fitting")
        required = ("shoulder_to_height", "hip_to_height", "arm_to_height", "leg_to_height")
        shape: dict[str, float] = {}
        for key in required:
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or not 0.0 < float(value) <= 1.0:
                raise AvatarError(f"bodyprint.shape.{key} is required and must be in (0,1]")
            shape[key] = float(value)
        height_scale = raw.get("height_scale", 1.0)
        if isinstance(height_scale, bool) or not isinstance(height_scale, (int, float)) or not math.isfinite(float(height_scale)) or not 0.0 < float(height_scale) <= 4.0:
            raise AvatarError("bodyprint.shape.height_scale must be in (0,4]")
        shape["height_scale"] = float(height_scale)
        return shape

    def fit(self, bodyprint: Mapping[str, Any], *, name: str) -> AvatarFitResult:
        if not isinstance(name, str) or not name.strip() or len(name) > 160:
            raise AvatarError("avatar name must contain 1..160 characters")
        shape = self._shape(bodyprint)
        height = 1.70 * shape["height_scale"]
        shoulder_width = height * shape["shoulder_to_height"]
        hip_width = height * shape["hip_to_height"]
        arm_length = height * shape["arm_to_height"]
        leg_length = height * shape["leg_to_height"]

        # Skeleton positions use local translations. Required humanoid bones are
        # deliberately never non-uniformly scaled; dimensions are expressed by
        # bone placement and separate visual child meshes.
        nodes: list[dict[str, Any]] = []
        human_bones: dict[str, dict[str, int]] = {}

        def bone(bone_name: str, translation: list[float], parent: int | None = None) -> int:
            idx = len(nodes)
            nodes.append({"name": bone_name, "translation": translation})
            human_bones[bone_name] = {"node": idx}
            if parent is not None:
                nodes[parent].setdefault("children", []).append(idx)
            return idx

        def visual(label: str, parent: int, translation: list[float], scale: list[float]) -> int:
            idx = len(nodes)
            nodes.append({"name": label, "translation": translation, "scale": scale, "mesh": 0})
            nodes[parent].setdefault("children", []).append(idx)
            return idx

        hips = bone("hips", [0.0, leg_length, 0.0])
        spine_len = max(0.22 * height, height - leg_length - 0.18 * height)
        spine = bone("spine", [0.0, 0.18 * spine_len, 0.0], hips)
        chest = bone("chest", [0.0, 0.42 * spine_len, 0.0], spine)
        neck = bone("neck", [0.0, 0.30 * spine_len, 0.0], chest)
        head = bone("head", [0.0, 0.12 * height, 0.0], neck)

        upper_leg = max(0.22 * height, 0.52 * leg_length)
        lower_leg = max(0.18 * height, leg_length - upper_leg)
        foot_len = 0.13 * height
        for side, sign in (("left", 1.0), ("right", -1.0)):
            upper_leg_name = f"{side}UpperLeg"
            lower_leg_name = f"{side}LowerLeg"
            foot_name = f"{side}Foot"
            upper = bone(upper_leg_name, [sign * hip_width * 0.33, -0.02 * height, 0.0], hips)
            lower = bone(lower_leg_name, [0.0, -upper_leg, 0.0], upper)
            foot = bone(foot_name, [0.0, -lower_leg, 0.04 * height], lower)
            visual(f"{upper_leg_name}Visual", upper, [0.0, -upper_leg / 2, 0.0], [0.075 * height, upper_leg, 0.085 * height])
            visual(f"{lower_leg_name}Visual", lower, [0.0, -lower_leg / 2, 0.0], [0.065 * height, lower_leg, 0.075 * height])
            visual(f"{foot_name}Visual", foot, [0.0, -0.025 * height, foot_len / 2], [0.08 * height, 0.055 * height, foot_len])

        upper_arm = max(0.16 * height, 0.52 * arm_length)
        lower_arm = max(0.14 * height, arm_length - upper_arm)
        for side, sign in (("left", 1.0), ("right", -1.0)):
            shoulder_name = f"{side}Shoulder"
            upper_arm_name = f"{side}UpperArm"
            lower_arm_name = f"{side}LowerArm"
            hand_name = f"{side}Hand"
            shoulder = bone(shoulder_name, [sign * shoulder_width * 0.42, 0.06 * spine_len, 0.0], chest)
            upper = bone(upper_arm_name, [sign * shoulder_width * 0.08, 0.0, 0.0], shoulder)
            lower = bone(lower_arm_name, [sign * upper_arm, 0.0, 0.0], upper)
            hand = bone(hand_name, [sign * lower_arm, 0.0, 0.0], lower)
            visual(f"{upper_arm_name}Visual", upper, [sign * upper_arm / 2, 0.0, 0.0], [upper_arm, 0.07 * height, 0.07 * height])
            visual(f"{lower_arm_name}Visual", lower, [sign * lower_arm / 2, 0.0, 0.0], [lower_arm, 0.06 * height, 0.06 * height])
            visual(f"{hand_name}Visual", hand, [sign * 0.045 * height, 0.0, 0.0], [0.09 * height, 0.075 * height, 0.035 * height])

        visual("PelvisVisual", hips, [0.0, 0.04 * height, 0.0], [hip_width, 0.16 * height, 0.16 * height])
        visual("TorsoVisual", spine, [0.0, 0.42 * spine_len, 0.0], [shoulder_width * 0.90, 0.72 * spine_len, 0.18 * height])
        visual("HeadVisual", head, [0.0, 0.06 * height, 0.0], [0.15 * height, 0.18 * height, 0.15 * height])

        binary, buffer_views, accessors = _cube_geometry()
        document: dict[str, Any] = {
            "asset": {"version": "2.0", "generator": "BodyRig procedural-vrm1"},
            "extensionsUsed": [VRM_EXTENSION],
            "extensionsRequired": [VRM_EXTENSION],
            "extensions": {
                VRM_EXTENSION: {
                    "specVersion": VRM_SPEC_VERSION,
                    "meta": {
                        "name": name.strip(),
                        "version": "1",
                        "authors": ["BodyRig"],
                        "licenseUrl": "https://vrm.dev/licenses/1.0/",
                        "avatarPermission": "onlyAuthor",
                        "commercialUsage": "personalNonProfit",
                        "creditNotation": "required",
                        "allowRedistribution": False,
                        "modification": "prohibited",
                    },
                    "humanoid": {"humanBones": human_bones},
                }
            },
            "scene": 0,
            "scenes": [{"nodes": [hips]}],
            "nodes": nodes,
            "meshes": [{"name": "BodyRigPlaceholderCube", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
            "materials": [{"name": "BodyRigPlaceholderMaterial", "pbrMetallicRoughness": {"baseColorFactor": [0.72, 0.72, 0.74, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9}}],
            "buffers": [{"byteLength": len(binary)}],
            "bufferViews": buffer_views,
            "accessors": accessors,
            "extras": {
                "bodyrig": {
                    "placeholder": True,
                    "sourceDerivedShape": shape,
                    "fitter": {"adapter": self.name, "revision": self.revision},
                }
            },
        }
        avatar = _glb(document, binary)
        validate_vrm1(avatar)
        return AvatarFitResult(avatar, _thumbnail_png(), self.name, self.revision)
