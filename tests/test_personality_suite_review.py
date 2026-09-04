from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig.person_assembly import build_assembly
from bodyrig.person_audition import audio_path, write_audition
from bodyrig.person_profiles import (
    add_body_revision,
    add_personality_revision,
    add_voice_revision,
    create_profile,
)
from bodyrig.personality_audition_suite import build_audition_suite
from bodyrig.personality_suite_review import (
    PersonalitySuiteReviewError,
    review_path,
    seal_suite_review,
    suite_review_sha256,
    verify_suite_review,
)

MODEL = "fixture-model"
RUNTIME = {
    "modelrig_service": "modelrig-server",
    "modelrig_version": "modelrig-test-1",
    "voicerig_service": "voicerig",
    "voicerig_version": "voicerig-test-1",
}


def _profile(root: Path) -> dict:
    profile = create_profile(root, display_name="Anna")
    person_id = profile["person_id"]
    add_body_revision(
        root,
        person_id,
        body_id="anna-body-0001",
        package_sha256="a" * 64,
        package_path=r"C:\BodyRig\anna.mrbody",
        feedback="fixture",
    )
    add_voice_revision(
        root,
        person_id,
        voice_id="anna-voice-0001",
        voice_package="anna.mrvoice",
        package_sha256="b" * 64,
        feedback="fixture",
    )
    profile = add_personality_revision(
        root,
        person_id,
        instructions="Du er Anna. Svar naturligt og uden at opfinde minder.",
        default_language="da",
        style_notes="rolig, tør og varm",
        feedback="fixture",
    )
    return profile


def _assembly(profile: dict) -> dict:
    return build_assembly(
        profile,
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
    )


def _auditions(
    root: Path,
    profile: dict,
    *,
    wrong_prompt: str | None = None,
    wrong_model_probe: str | None = None,
    wrong_modelrig_version_probe: str | None = None,
    wrong_voicerig_version_probe: str | None = None,
) -> dict[str, str]:
    assembly = _assembly(profile)
    result: dict[str, str] = {}
    for probe in build_audition_suite("da")["probes"]:
        prompt = wrong_prompt if probe["id"] == "small-mishap" and wrong_prompt is not None else probe["prompt"]
        model = "other-model" if probe["id"] == wrong_model_probe else MODEL
        runtime = dict(RUNTIME)
        if probe["id"] == wrong_modelrig_version_probe:
            runtime["modelrig_version"] = "modelrig-test-2"
        if probe["id"] == wrong_voicerig_version_probe:
            runtime["voicerig_version"] = "voicerig-test-2"
        receipt = write_audition(
            root,
            person_id=profile["person_id"],
            assembly_fingerprint=assembly["assembly_fingerprint"],
            model=model,
            prompt=prompt,
            reply=f"Svar for {probe['id']}",
            audio=b"RIFF" + bytes([len(result)]) + b"\x00" * 63,
            **runtime,
        )
        result[probe["id"]] = receipt["audition_id"]
    return result


def _seal(root: Path, profile: dict, audition_ids: dict[str, str]) -> dict:
    assembly = _assembly(profile)
    return seal_suite_review(
        root,
        person_id=profile["person_id"],
        body_revision="body-r0001",
        voice_revision="voice-r0001",
        personality_revision="personality-r0001",
        assembly_fingerprint=assembly["assembly_fingerprint"],
        model=MODEL,
        default_language="da",
        audition_ids=audition_ids,
    )


def test_suite_review_seals_exact_six_probe_execution_without_activation_authority(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    audition_ids = _auditions(tmp_path, profile)

    review = _seal(tmp_path, profile, audition_ids)

    assert review["format"] == "bodyrig-personality-suite-review"
    assert review["version"] == 1
    assert review["modelrig_version"] == "modelrig-test-1"
    assert review["voicerig_version"] == "voicerig-test-1"
    assert review["human_review_required"] is True
    assert review["activation_authority"] is False
    assert [item["probe_id"] for item in review["probe_results"]] == [
        probe["id"] for probe in build_audition_suite("da")["probes"]
    ]
    assert review_path(tmp_path, profile["person_id"], review["review_id"]).is_file()
    assert len(suite_review_sha256(tmp_path, person_id=profile["person_id"], review_id=review["review_id"])) == 64
    assert verify_suite_review(tmp_path, person_id=profile["person_id"], review_id=review["review_id"]) == review


def test_suite_review_rejects_missing_duplicate_or_wrong_probe_execution(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    audition_ids = _auditions(tmp_path, profile)

    missing = dict(audition_ids)
    missing.pop("take-initiative")
    with pytest.raises(PersonalitySuiteReviewError, match="exact suite probe ids"):
        _seal(tmp_path, profile, missing)

    duplicate = dict(audition_ids)
    duplicate["take-initiative"] = duplicate["small-mishap"]
    with pytest.raises(PersonalitySuiteReviewError, match="distinct audition"):
        _seal(tmp_path, profile, duplicate)


def test_suite_review_rejects_wrong_prompt_or_model(tmp_path: Path) -> None:
    prompt_root = tmp_path / "prompt"
    prompt_profile = _profile(prompt_root)
    wrong_prompt = _auditions(prompt_root, prompt_profile, wrong_prompt="Et andet prompt")
    with pytest.raises(PersonalitySuiteReviewError, match="prompt does not match"):
        _seal(prompt_root, prompt_profile, wrong_prompt)

    model_root = tmp_path / "model"
    model_profile = _profile(model_root)
    wrong_model = _auditions(model_root, model_profile, wrong_model_probe="gentle-disagreement")
    with pytest.raises(PersonalitySuiteReviewError, match="different ModelRig model"):
        _seal(model_root, model_profile, wrong_model)


def test_suite_review_rejects_mixed_execution_runtime_versions(tmp_path: Path) -> None:
    mr_root = tmp_path / "modelrig-version"
    mr_profile = _profile(mr_root)
    mixed_modelrig = _auditions(
        mr_root,
        mr_profile,
        wrong_modelrig_version_probe="take-initiative",
    )
    with pytest.raises(PersonalitySuiteReviewError, match="ModelRig runtime version changed during suite"):
        _seal(mr_root, mr_profile, mixed_modelrig)

    vr_root = tmp_path / "voicerig-version"
    vr_profile = _profile(vr_root)
    mixed_voicerig = _auditions(
        vr_root,
        vr_profile,
        wrong_voicerig_version_probe="unknown-memory-boundary",
    )
    with pytest.raises(PersonalitySuiteReviewError, match="VoiceRig runtime version changed during suite"):
        _seal(vr_root, vr_profile, mixed_voicerig)


def test_suite_review_detects_post_seal_audio_tamper(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    audition_ids = _auditions(tmp_path, profile)
    review = _seal(tmp_path, profile, audition_ids)

    target_id = audition_ids["unknown-memory-boundary"]
    audio_path(tmp_path, profile["person_id"], target_id).write_bytes(b"RIFF" + b"tampered" + b"\x00" * 64)

    with pytest.raises(PersonalitySuiteReviewError, match="audio"):
        verify_suite_review(tmp_path, person_id=profile["person_id"], review_id=review["review_id"])


def test_suite_review_rejects_fingerprint_for_different_personality_revision(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    old_assembly = _assembly(profile)
    audition_ids = _auditions(tmp_path, profile)
    add_personality_revision(
        tmp_path,
        profile["person_id"],
        instructions="Du er Anna v2.",
        default_language="da",
        style_notes="v2",
        feedback="second candidate",
    )

    with pytest.raises(PersonalitySuiteReviewError, match="fingerprint"):
        seal_suite_review(
            tmp_path,
            person_id=profile["person_id"],
            body_revision="body-r0001",
            voice_revision="voice-r0001",
            personality_revision="personality-r0002",
            assembly_fingerprint=old_assembly["assembly_fingerprint"],
            model=MODEL,
            default_language="da",
            audition_ids=audition_ids,
        )
