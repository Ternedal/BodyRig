from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_manifest_binds_critical_payload_hashes() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "bodyrig-runtime-assets-v1.schema.json").read_text(encoding="utf-8")
    )
    required = set(schema["required"])
    assert {"avatar_sha256", "bodyprint_sha256"} <= required
    assert schema["properties"]["avatar_sha256"]["pattern"] == "^[0-9a-f]{64}$"
    assert schema["properties"]["bodyprint_sha256"]["pattern"] == "^[0-9a-f]{64}$"

    materialize = (ROOT / "bodyrig" / "materialize.py").read_text(encoding="utf-8")
    assert '"avatar_sha256": _sha256_file(avatar_path)' in materialize
    assert '"bodyprint_sha256": _sha256_file(bodyprint_path)' in materialize
    assert materialize.index('avatar_path = temp / "avatar.vrm"') < materialize.index(
        '"avatar_sha256": _sha256_file(avatar_path)'
    )


def test_reference_renderer_rechecks_runtime_payload_hashes_point_of_use() -> None:
    loader = (
        ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigAvatarLoader.cs"
    ).read_text(encoding="utf-8")
    probe = (
        ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigRendererProbe.cs"
    ).read_text(encoding="utf-8")

    assert "public string avatar_sha256;" in loader
    assert "public string bodyprint_sha256;" in loader
    assert 'RequireSha256(avatarPath, manifest.avatar_sha256, "avatar.vrm");' in loader
    assert loader.count('RequireSha256(bodyprintPath, manifest.bodyprint_sha256, "bodyprint.json");') >= 2
    assert 'LoadAvatarPathAsync(avatarPath, manifest.avatar_sha256, cancellationToken)' in loader
    assert loader.index('RequireSha256(fullPath, expectedSha256, "avatar.vrm");') < loader.index(
        "_active = candidate;"
    )
    assert "ActiveAvatarSha256 = manifest.avatar_sha256.ToLowerInvariant();" in loader
    assert "ActiveBodyprintSha256 = manifest.bodyprint_sha256.ToLowerInvariant();" in loader

    assert "var avatarHash = Sha256File(avatarPath);" in probe
    assert "var bodyprintHash = Sha256File(bodyprintPath);" in probe
    assert "loader.ActiveAvatarSha256" in probe
    assert "loader.ActiveBodyprintSha256" in probe
    assert "avatar_sha256 = avatarHash" in probe
    assert "bodyprint_sha256 = bodyprintHash" in probe
    assert probe.index("var avatarHash = Sha256File(avatarPath);") < probe.index(
        "var report = new ProbeReport"
    )
