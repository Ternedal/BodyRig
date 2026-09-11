from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "contracts" / "bodyrig-runtime-assets-v1.schema.json"
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
LOADER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigAvatarLoader.cs"
MATERIALIZER = REPO / "bodyrig" / "materialize.py"


def _payload_schema() -> dict[str, object]:
    contract = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return contract["properties"]["payloads"]


def test_runtime_schema_requires_both_authoritative_payload_memberships() -> None:
    payloads = _payload_schema()
    required = {payloads["contains"]["const"]}
    required.update(
        clause["contains"]["const"]
        for clause in payloads["allOf"]
    )
    assert required == {"avatar.vrm", "bodyprint.json"}
    assert payloads["minItems"] == 4
    assert payloads["maxItems"] == 10
    assert payloads["uniqueItems"] is True
    assert required <= set(payloads["items"]["enum"])


def test_runtime_renderer_and_materializer_require_same_authoritative_payloads() -> None:
    shim = SHIM.read_text(encoding="utf-8")
    helper = shim[
        shim.index("private static void ValidateRuntimeManifestPayloads") :
        shim.index("private static List<string> ParseStringArray")
    ]
    assert '!unique.Contains("avatar.vrm") || !unique.Contains("bodyprint.json")' in helper

    loader = LOADER.read_text(encoding="utf-8")
    assert 'Array.IndexOf(manifest.payloads, "avatar.vrm") < 0 ||' in loader
    assert 'Array.IndexOf(manifest.payloads, "bodyprint.json") < 0' in loader

    materializer = MATERIALIZER.read_text(encoding="utf-8")
    assert 'materialized runtime is missing required avatar/bodyprint payload' in materializer
